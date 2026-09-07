"""End-to-end star map test, instrumented step by step.

The previous test typed a destination but never selected it, so it could not
tell us what selecting actually does. This one performs each step
separately and captures the screen in between, which answers the questions
the design still has open:

Answered by the first run: clicking a row IS the selection — no Enter — and
the mobiGlas animation is slower than any fixed delay worth hard-coding, so
opening the map and typing are now both verified rather than waited out.

Still open, and what this run measures:

  * how long the camera zoom really needs before R will register
  * does CANCEL ROUTE appear, and what does the panel say was routed?
  * how much wall-clock time each OCR read costs

    python test_starmap.py                  walk through step by step
    python test_starmap.py --auto           run the real route_to() in one go
    python test_starmap.py --dest "daymar"  use a different destination
    python test_starmap.py --auto --voice  speak the responses out loud

Captures are saved beside this script as starmap_step*.png.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

import starmap
import win_input as wi
import win_ocr


HERE = Path(__file__).resolve().parent


def banner(text):
    print()
    print("=" * 68)
    print(f"  {text}")
    print("=" * 68)


def countdown(seconds, message):
    print(f"\n{message}")
    for remaining in range(seconds, 0, -1):
        print(f"   {remaining}...", end="\r", flush=True)
        time.sleep(1)
    print("   go!        ")


def pause(question):
    return input(f"\n{question} [Enter to continue, q to quit]: ").strip().lower() != "q"


def snapshot(controller, label, regions=("dropdown",)):
    """Capture and read the named regions, printing what each contains."""
    output = {}
    for name in regions:
        region = controller.settings[name]
        save = HERE / f"starmap_{label}_{name}.png"
        data = win_ocr.ocr_region(
            region["left"], region["top"], region["width"], region["height"],
            save_path=str(save),
        )
        output[name] = data

        lines = [l["text"] for l in data.get("lines", [])]
        print(f"\n   [{name}] brightness {data.get('mean_brightness')}"
              f"  read in {data.get('elapsed', '?')}s")
        if data.get("error"):
            print(f"      ERROR: {data['error']}")
        elif not lines:
            print("      (no text)")
        else:
            for text in lines:
                print(f"      {text}")
        print(f"      saved: {save.name}")
    return output


def walkthrough(controller, destination):
    banner("Instrumented star map walkthrough")
    print(f"   Destination : {destination}")
    print(f"   Current system: {controller.current_system}")
    print()
    print("   Have Star Citizen running, seated in your ship, mobiGlas CLOSED.")
    print("   Each step pauses so you can watch what happens on screen.")

    if not pause("Ready?"):
        return None

    # --- 1. open the map -------------------------------------------------
    banner("Step 1 — F2, poll until the map is really up, then click search")
    print("   The first run failed here: a fixed 1s delay was shorter than")
    print("   the mobiGlas animation, so the click was swallowed. Now it")
    print("   polls the HUD keybind list instead of guessing.")
    countdown(8, "Switch to Star Citizen:")

    opened = controller.open_map(announce=False)
    print(f"\n   open_map() -> {opened}")
    if not opened:
        snapshot(controller, "1_failed", regions=("verify_region", "search_field"))
        print("\n   Map never appeared. Send me starmap_1_failed_*.png")
        return False

    snapshot(controller, "1_opened", regions=("search_field",))
    print("\n   Expect the search field to show its placeholder, focused.")
    if not pause("Did the map open and the search bar take focus?"):
        return None

    # --- 2. type ---------------------------------------------------------
    banner("Step 2 — type the destination, then read it back")
    countdown(6, "Switch back to Star Citizen:")

    typed_ok = controller.enter_destination(destination)
    print(f"\n   enter_destination() -> {typed_ok}")
    snapshot(controller, "2_typed", regions=("search_field",))
    if not typed_ok:
        print("\n   The text never reached the field. Send me the captures.")
        return False

    data = snapshot(controller, "2_results")

    rows = starmap.parse_results(data["dropdown"].get("lines", []))
    print(f"\n   Parsed {len(rows)} result row(s):")
    for row in rows:
        marker = " (has distance)" if row["has_distance"] else ""
        print(f"      {row['text']:<24} under {row['system']}{marker}")

    if not rows:
        print("\n   No rows parsed — stopping. Send me starmap_2_typed_dropdown.png")
        return False

    chosen, why = starmap.pick_row(rows, destination, controller.current_system)
    if chosen is None:
        print(f"\n   Could not pick a row: {why}")
        return False

    x, y = win_ocr.line_center(chosen["line"])
    print(f"\n   Would click: '{chosen['text']}' under {chosen['system']}")
    print(f"   Reason     : {why}")
    print(f"   Click point: ({x}, {y})")
    if not pause("Is that the row you would have picked?"):
        return None

    # --- 3. click the row ------------------------------------------------
    banner("Step 3 — click that row (selects the target and flies the camera)")
    print(f"   Then waiting {controller.settings['delay_select']}s for the zoom")
    print("   to settle. No Enter — clicking is the selection.")
    countdown(6, "Switch back to Star Citizen:")
    wi.click_at(x, y, physical=True)
    time.sleep(controller.settings["delay_select"])
    snapshot(controller, "3_clicked", regions=("destination_region", "verify_region"))
    print("\n   Expect the camera to have flown to the destination and the")
    print("   right-hand panel to name it.")
    if not pause("Continue?"):
        return None

    # --- 4. R to route ---------------------------------------------------
    banner("Step 4 — press R to plot the course")
    countdown(6, "Switch back to Star Citizen:")
    wi.tap_keybind("r")
    time.sleep(controller.settings["delay_route"])
    snapshot(controller, "4_routed", regions=("verify_region", "destination_region"))

    routed = controller.verify_route()
    print(f"\n   CANCEL ROUTE present: {'YES — course is set' if routed else 'NO'}")

    name, eta = controller.read_destination()
    print(f"   Panel destination   : {name or '(not read)'}")
    print(f"   Panel ETA           : {eta or '(not read)'}")

    if routed:
        spoken = f"Course set to {name or chosen['text'].title()}."
        if eta:
            spoken = f"Course set to {name or chosen['text'].title()}. {eta}."
        print(f"\n   Would say: \"{spoken}\"")

    return routed


def automatic(controller, destination):
    banner("Automatic run — the real route_to()")
    print("   Have Star Citizen running, seated, mobiGlas CLOSED.")
    if not pause("Ready?"):
        return None

    countdown(8, "Switch to Star Citizen and do not touch anything:")

    started = time.time()
    ok, message = controller.route_to(destination)
    elapsed = time.time() - started

    banner("Result")
    print(f"   {'SUCCESS' if ok else 'FAILED'}: {message}")
    print(f"   Took {elapsed:.1f}s end to end.")
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", default="nyx gateway")
    parser.add_argument("--system", default="Stanton")
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--voice", action="store_true",
                        help="actually speak the responses through Windows TTS")
    parser.add_argument("--enter", action="store_true",
                        help="also press Enter after clicking (not normally needed)")
    args = parser.parse_args()

    spoken = args.dest
    resolved = starmap.normalize_destination(spoken)
    print()
    print("Kabutopz Voice Protocol — star map test")
    print(f"   heard '{spoken}' -> typing '{resolved}'")

    log = lambda text, kind="info": print(f"   [{kind}] {text}")

    def speak(text):
        print(f"   [speak] {text}")
        if not args.voice:
            return
        # Same PowerShell System.Speech route the app itself uses, so this
        # exercises the real audio path rather than a stand-in.
        safe = text.replace("'", "''")
        try:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                 "-Command",
                 "Add-Type -AssemblyName System.Speech; "
                 "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                 f"$s.Speak('{safe}')"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:
            print(f"   [speak failed] {exc}")

    controller = starmap.StarMapController(
        settings={
            "current_system": args.system.title(),
            "press_enter_after_click": args.enter,
        },
        speak=speak,
        log=log,
    )

    if args.auto:
        result = automatic(controller, resolved)
    else:
        result = walkthrough(controller, resolved)

    banner("Done")
    if result is None:
        print("   Stopped early.")
        return 1
    if result:
        print("   Course was set and verified.")
        print("   Send me the output so I can lock in the delays.")
        return 0

    print("   Course was not confirmed.")
    print("   Send me the output plus the starmap_*.png captures.")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
