"""Screen capture + OCR check — run this one WITH Star Citizen open.

This settles the three things the star map feature depends on:

  1. Does Windows have an OCR language pack?
  2. Does screen capture work in Fullscreen, or come back black?
  3. Can it read the mobiGlas search results well enough to pick a row?

Every capture is saved as a PNG next to this script, so if a step reads
badly you can look at exactly what the OCR saw.

    python test_ocr.py
"""

import sys
import time
from pathlib import Path

import win_ocr
import win_input as wi


HERE = Path(__file__).resolve().parent

# Measured from Nate's 3840x2160 screenshots.
SEARCH_BAR = (760, 272)
DROPDOWN_REGION = (390, 325, 750, 880)      # left, top, width, height
VERIFY_REGION = (3140, 1430, 470, 320)      # the CANCEL ROUTE keybind block
DESTINATION_REGION = (2680, 620, 720, 100)  # quantum travel destination name


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
    print("   capturing...   ")


def confirm(question):
    return input(f"\n{question} [y/N]: ").strip().lower().startswith("y")


def show_lines(data, limit=40):
    lines = data.get("lines", [])
    if not lines:
        print("   (no text recognised)")
        return

    print(f"   {len(lines)} line(s) read:")
    print()
    print(f"   {'text':<42} {'click point':>16}")
    print(f"   {'-' * 42} {'-' * 16}")
    for line in lines[:limit]:
        x, y = win_ocr.line_center(line)
        text = line["text"]
        if len(text) > 40:
            text = text[:39] + "…"
        print(f"   {text:<42} {f'({x}, {y})':>16}")
    if len(lines) > limit:
        print(f"   ... and {len(lines) - limit} more")


def report_capture(data):
    brightness = data.get("mean_brightness", 0)
    print(f"   Mean brightness: {brightness}")
    if data.get("black"):
        print()
        print("   >>> BLACK FRAME <<<")
        print("   The capture came back empty. In exclusive Fullscreen the")
        print("   desktop compositor may refuse to hand over the game's")
        print("   surface. Switching Star Citizen to Borderless Windowed")
        print("   almost always fixes this.")
        return False
    return True


def test_ocr_available():
    banner("1. Is Windows OCR available?")
    print("   No game needed for this one.")

    available, description = win_ocr.ocr_status()
    print(f"\n   {description}")

    if not available:
        print()
        print("   Add an OCR language pack under:")
        print("   Settings > Time & Language > Language & region >")
        print("   English > three dots > Language options > Optional features")
        print("   ('Optical character recognition')")
    return available


def test_desktop_capture():
    banner("2. Capture and read ordinary desktop text")
    print("   Proves the pipeline works before the game complicates it.")
    print("   Open Notepad with some text visible.")

    if not confirm("Ready?"):
        print("   Skipped.")
        return True

    countdown(5, "Bring Notepad to the front:")

    left, top, width, height = wi.screen_metrics(physical=True)
    save = HERE / "ocr_test_desktop.png"
    data = win_ocr.ocr_region(
        left + width // 4, top + height // 4,
        width // 2, height // 2,
        save_path=str(save),
    )

    if not data.get("ok"):
        print(f"\n   FAILED: {data.get('error')}")
        return False

    report_capture(data)
    show_lines(data, limit=15)
    print(f"\n   Saved: {save.name}")
    return bool(data.get("lines"))


def test_fullscreen_capture():
    banner("3. Can we capture Star Citizen at all? — THE BIG QUESTION")
    print("   Start Star Citizen, get in your ship, and press F2 so the")
    print("   Star Map is open. Leave the search bar empty.")

    if not confirm("Is the Star Map open?"):
        print("   Skipped.")
        return None

    countdown(8, "Switch to Star Citizen now:")

    left, top, width, height = wi.screen_metrics(physical=True)
    save = HERE / "ocr_test_starmap_full.png"
    data = win_ocr.capture_region(left, top, width, height, save_path=str(save))

    if not data.get("ok"):
        print(f"\n   FAILED: {data.get('error')}")
        return False

    ok = report_capture(data)
    print(f"   Saved: {save.name}")
    if ok:
        print("\n   Capture works in your current window mode.")
    return ok


def test_search_bar_click():
    banner("4. Click the search bar at the measured coordinates")
    print(f"   Will click ({SEARCH_BAR[0]}, {SEARCH_BAR[1]}) in physical pixels,")
    print("   then type 'nyx gateway'.")

    if not confirm("Star Map still open with an empty search bar?"):
        print("   Skipped.")
        return None

    countdown(8, "Switch to Star Citizen now:")

    wi.click_at(*SEARCH_BAR, physical=True)
    time.sleep(0.4)
    wi.type_text("nyx gateway", interval=0.04)
    time.sleep(1.2)

    save = HERE / "ocr_test_dropdown.png"
    data = win_ocr.ocr_region(*DROPDOWN_REGION, save_path=str(save))

    if not data.get("ok"):
        print(f"\n   FAILED: {data.get('error')}")
        return False

    report_capture(data)
    show_lines(data)
    print(f"\n   Saved: {save.name}")

    lines = data.get("lines", [])
    headers = [l["text"] for l in lines if "SYSTEM" in l["text"].upper()]
    matches = [l["text"] for l in lines if "GATEWAY" in l["text"].upper()]

    print()
    print(f"   System headers found : {headers or 'none'}")
    print(f"   Gateway rows found   : {matches or 'none'}")

    if headers and matches:
        print()
        print("   Both the group headers and the result rows are readable.")
        print("   That is everything the row picker needs.")
        return True

    print()
    print("   Did not find both headers and rows. Look at the saved PNG —")
    print("   if the text is there but unread, the capture region may need")
    print("   nudging; send me the file.")
    return False


def test_route_verification():
    banner("5. Route verification region")
    print("   Reads the bottom-right keybind list. 'CANCEL ROUTE' appears")
    print("   there only when a course is actually plotted.")
    print()
    print("   Plot a course first (select a destination, Enter, then R).")

    if not confirm("Is a course plotted with the map still open?"):
        print("   Skipped.")
        return None

    countdown(8, "Switch to Star Citizen now:")

    save = HERE / "ocr_test_verify.png"
    data = win_ocr.ocr_region(*VERIFY_REGION, save_path=str(save))
    if not data.get("ok"):
        print(f"\n   FAILED: {data.get('error')}")
        return False

    report_capture(data)
    show_lines(data)

    text = " ".join(l["text"].upper() for l in data.get("lines", []))
    found = "CANCEL ROUTE" in text.replace("  ", " ")
    print(f"\n   'CANCEL ROUTE' present: {'YES' if found else 'NO'}")

    dest_save = HERE / "ocr_test_destination.png"
    dest = win_ocr.ocr_region(*DESTINATION_REGION, save_path=str(dest_save))
    if dest.get("ok"):
        print()
        print("   Destination panel:")
        show_lines(dest, limit=6)

    print(f"\n   Saved: {save.name}, {dest_save.name}")
    return found


def main():
    print()
    print("Kabutopz Voice Protocol — capture & OCR check")
    print("Captures are saved beside this script as ocr_test_*.png")

    results = {}

    results["OCR available"] = test_ocr_available()
    if not results["OCR available"]:
        print("\n   Stopping — nothing else can work without OCR.")
        return 1

    results["desktop capture"] = test_desktop_capture()
    results["game capture"] = test_fullscreen_capture()

    if results["game capture"] is False:
        print("\n   Skipping the rest until capture works.")
    else:
        results["search + dropdown"] = test_search_bar_click()
        results["route verification"] = test_route_verification()

    banner("Summary")
    for name, value in results.items():
        mark = {True: "PASS", False: "FAIL", None: "skip"}[value]
        print(f"   {mark}  {name}")

    print()
    print("   Send me this output plus any ocr_test_*.png that look wrong.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
