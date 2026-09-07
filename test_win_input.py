"""Standalone check for the new win_input primitives.

Run this BEFORE trying anything in Star Citizen. It verifies mouse
positioning, clicking, and text entry against an ordinary Windows app, so
that if something misbehaves later in game you already know whether the
primitives themselves are sound.

    python test_win_input.py

Tests 1-3 are read-only and safe. Tests 4-6 move the mouse and type, so
they ask before running and give you time to focus a target window.
"""

import sys
import time

import win_input as wi


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
    print("   go!      ")


def confirm(question):
    return input(f"\n{question} [y/N]: ").strip().lower().startswith("y")


def test_screen_metrics():
    banner("1. Screen geometry")
    left, top, width, height = wi.screen_metrics()
    print(f"   Virtual desktop : {width} x {height} at ({left}, {top})")

    scale_x, scale_y = wi.dpi_scale()
    print(f"   Display scaling : {scale_x:.2f}x horizontal, {scale_y:.2f}x vertical")

    if abs(scale_x - 1.0) > 0.01:
        physical_w = int(round(width * scale_x))
        physical_h = int(round(height * scale_y))
        print()
        print("   NOTE: Windows scaling is on. This app reports coordinates in")
        print(f"   a {width}x{height} space, while the real panel is")
        print(f"   {physical_w}x{physical_h}. Both numbers are correct; they")
        print("   just belong to different coordinate systems. Calibration")
        print("   captures and mouse clicks both use the reported space, so")
        print("   they agree with each other.")
    else:
        print("   No display scaling. Reported pixels are physical pixels.")
    return True


def test_cursor_position():
    banner("2. Cursor position")
    print("   Move the mouse around. Reading position for 3 seconds...")
    seen = set()
    end = time.time() + 3.0
    while time.time() < end:
        seen.add(wi.get_cursor_pos())
        time.sleep(0.1)

    sample = wi.get_cursor_pos()
    print(f"   Final position  : {sample}")
    print(f"   Distinct samples: {len(seen)}")

    if len(seen) <= 1:
        print("   (Did not see the cursor move. Fine if you left it still.)")
    return True


def test_calibration_capture():
    banner("3. Calibration capture — the STAR MAP page will use this")
    if not confirm("Practice capturing a position?"):
        print("   Skipped.")
        return True

    countdown(5, "Hover the mouse over anything you like. Capturing in:")
    x, y = wi.get_cursor_pos()
    print(f"\n   Captured: x={x}, y={y}")
    print("   That is exactly what the Capture Position button will store.")
    return True


def test_mouse_move():
    banner("4. Absolute mouse movement")
    if not confirm("Move the mouse cursor automatically?"):
        print("   Skipped.")
        return True

    left, top, width, height = wi.screen_metrics()
    origin = wi.get_cursor_pos()

    targets = [
        ("center", left + width // 2, top + height // 2),
        ("upper left area", left + width // 4, top + height // 4),
        ("lower right area", left + (width * 3) // 4, top + (height * 3) // 4),
    ]

    worst = 0
    for name, x, y in targets:
        wi.move_mouse_to(x, y)
        time.sleep(0.4)
        got_x, got_y = wi.get_cursor_pos()
        error = max(abs(got_x - x), abs(got_y - y))
        worst = max(worst, error)
        status = "ok" if error <= 2 else "OFF"
        print(f"   {name:<18} asked ({x}, {y})  got ({got_x}, {got_y})  [{status}]")

    wi.move_mouse_to(*origin)
    print(f"\n   Worst error: {worst} px")

    if worst > 2:
        print("   Larger than expected. Usually display scaling or a second")
        print("   monitor. Report the numbers above and we will adjust.")
        return False

    print("   Positioning is accurate.")
    return True


def test_typing_plan():
    """Check the shift sequencing without pressing a single key.

    Typing "HUR-L5" into Star Citizen produced "HUR_L%": shift was toggled
    per character, and with only milliseconds between its down and up events
    two characters could land in the same game frame and share one sampled
    shift state, so the unshifted "-" and "5" inherited the shift belonging
    to "R" and "L". Shift is now held across a run and released once.
    """
    banner("5. Typing plan — shift sequencing (no keys pressed)")

    inverse = {value: key for key, value in wi._TYPE_MAP.items()}
    ok = True

    for text in ["HUR-L5", "CRU-L5", "Lorville", "Grim Hex", "microTech",
                 "Area 18", "ArcCorp", "Nyx Gateway", "New Babbage"]:
        shift = False
        typed = ""
        transitions = 0
        for kind, value in wi.plan_typing(text):
            if kind == "shift":
                shift = value
                transitions += 1
            elif kind == "key":
                typed += inverse[(value, shift)]
            else:
                typed += value

        good = typed == text and not shift
        ok = ok and good
        print(f"   {'PASS' if good else 'FAIL'}  {text!r:14} "
              f"-> {typed!r} ({transitions} shift transitions)")
        if not good and shift:
            print("          shift was still held at the end")

    # The specific regression: the characters after an uppercase run must be
    # typed with shift explicitly up.
    steps = list(wi.plan_typing("HUR-L5"))
    shift = False
    unshifted = []
    for kind, value in steps:
        if kind == "shift":
            shift = value
        elif not shift:
            unshifted.append(value)
    good = unshifted == ["-", "5"]
    ok = ok and good
    print(f"   {'PASS' if good else 'FAIL'}  \"HUR-L5\": unshifted keys are "
          f"{unshifted} (want ['-', '5'])")

    return ok


def test_typing():
    banner("6. Text entry — THIS IS THE IMPORTANT ONE")
    print("   Star Citizen accepting synthetic text is the single biggest")
    print("   unknown in the star map feature. Test it here first.")
    print()
    print("   Open Notepad (or any text box) and click into it.")

    if not confirm("Ready to type into the focused window?"):
        print("   Skipped.")
        return True

    countdown(5, "Click into the text field now. Typing in:")

    samples = ["pyro gateway", "Daymar", "Grim Hex", "microTech",
               "NYX GATEWAY", "HUR-L5", "CRU-L5"]
    for text in samples:
        wi.type_text(text, interval=0.03)
        wi.tap_keybind("enter")
        time.sleep(0.25)

    print("\n   Expected to appear, one per line:")
    for text in samples:
        print(f"     {text}")
    print()
    print("   Check capitalisation and spaces carefully. Missing characters")
    print("   mean the interval needs raising above 0.03s.")

    return confirm("Did all seven lines appear correctly?")


def test_clear_field():
    banner("7. Clearing a field")
    print("   Uses ctrl+a then delete, for re-searching without stale text.")

    if not confirm("Test clearing the focused text field?"):
        print("   Skipped.")
        return True

    countdown(5, "Click into the text field again. Clearing in:")
    wi.type_text("this text should disappear", interval=0.03)
    time.sleep(0.6)
    wi.clear_text_field()
    time.sleep(0.3)
    wi.type_text("field was cleared", interval=0.03)

    return confirm("Does the field now read exactly 'field was cleared'?")


def main():
    print()
    print("Kabutopz Voice Protocol — win_input primitive check")
    print("Nothing here touches Star Citizen. Ctrl+C aborts at any time.")

    tests = [
        ("screen metrics", test_screen_metrics),
        ("cursor position", test_cursor_position),
        ("calibration capture", test_calibration_capture),
        ("mouse movement", test_mouse_move),
        ("typing plan", test_typing_plan),
        ("text entry", test_typing),
        ("field clearing", test_clear_field),
    ]

    results = {}
    for name, function in tests:
        try:
            results[name] = function()
        except KeyboardInterrupt:
            print("\n\nAborted.")
            return 1
        except Exception as exc:
            print(f"\n   ERROR in {name}: {exc}")
            results[name] = False

    banner("Summary")
    for name, passed in results.items():
        print(f"   {'PASS' if passed else 'FAIL'}  {name}")

    failed = [name for name, passed in results.items() if not passed]
    if failed:
        print(f"\n   Needs attention: {', '.join(failed)}")
        print("   Send me this output and I will adjust before step 4.")
        return 1

    print("\n   All good. The star map feature can be built on these.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
