"""Mouse positioning diagnostic — replaces test 4 of test_win_input.py.

The first run showed inconsistent errors, which usually means the mouse was
physically moved mid-test rather than that the maths is wrong. This version
detects that instead of guessing: it checks the cursor is at rest before each
move, retries a point that gets disturbed, and reports interference
separately from real error.

It also sweeps a 9-point grid and tests both coordinate spaces, so one run
settles whether logical or physical addressing should be used.

    python test_mouse_diagnostic.py

DO NOT TOUCH THE MOUSE once it starts. Keyboard only.
"""

import sys
import time

import win_input as wi

SETTLE = 0.35          # let the cursor arrive before reading it
STILL_TOLERANCE = 1    # logical px of drift still counted as "at rest"
MAX_ATTEMPTS = 4


def banner(text):
    print()
    print("=" * 68)
    print(f"  {text}")
    print("=" * 68)


def cursor_is_at_rest(physical):
    """True if the cursor is not being moved by hand right now."""
    first = wi.get_cursor_pos(physical=physical)
    time.sleep(0.12)
    second = wi.get_cursor_pos(physical=physical)
    drift = max(abs(second[0] - first[0]), abs(second[1] - first[1]))
    limit = STILL_TOLERANCE * (3 if physical else 1)
    return drift <= limit, drift


def probe(x, y, physical):
    """Move to a point and measure the error, retrying if disturbed.

    Returns ``(error, got, attempts, disturbed)``.
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        at_rest, _ = cursor_is_at_rest(physical)
        if not at_rest:
            time.sleep(0.8)
            continue

        wi.move_mouse_to(x, y, physical=physical)
        time.sleep(SETTLE)
        got = wi.get_cursor_pos(physical=physical)

        # If the cursor is still drifting after the move, a hand is on it
        # and this reading cannot be trusted.
        still, _ = cursor_is_at_rest(physical)
        if not still:
            time.sleep(0.8)
            continue

        error = max(abs(got[0] - x), abs(got[1] - y))
        return error, got, attempt, False

    return None, None, MAX_ATTEMPTS, True


def sweep(label, physical):
    banner(label)

    left, top, width, height = wi.screen_metrics(physical=physical)
    print(f"   Addressing a {width} x {height} space at ({left}, {top})")
    print()

    points = []
    for fy in (0.15, 0.50, 0.85):
        for fx in (0.15, 0.50, 0.85):
            points.append((
                left + int(round((width - 1) * fx)),
                top + int(round((height - 1) * fy)),
            ))

    errors = []
    disturbed = 0
    tolerance = 3 if physical else 2

    for x, y in points:
        error, got, attempts, was_disturbed = probe(x, y, physical)

        if was_disturbed:
            disturbed += 1
            print(f"   ({x:>5}, {y:>5})  ->  SKIPPED, mouse kept moving")
            continue

        errors.append(error)
        flag = "ok" if error <= tolerance else "OFF"
        retry = f"  (retried {attempts - 1}x)" if attempts > 1 else ""
        print(f"   ({x:>5}, {y:>5})  ->  ({got[0]:>5}, {got[1]:>5})   "
              f"err {error:>4}  [{flag}]{retry}")

    print()
    if not errors:
        print("   No usable readings — the mouse was moving the whole time.")
        return None, disturbed

    worst = max(errors)
    average = sum(errors) / len(errors)
    print(f"   Readings: {len(errors)}/9   worst {worst} px   average {average:.1f} px")
    if disturbed:
        print(f"   Skipped {disturbed} point(s) because the mouse was being moved.")
    return worst, disturbed


def main():
    print()
    print("Mouse positioning diagnostic")
    print()

    scale_x, scale_y = wi.dpi_scale()
    lw, lh = wi.screen_metrics()[2:]
    pw, ph = wi.screen_metrics(physical=True)[2:]
    print(f"   Logical space : {lw} x {lh}   (what Windows reports to this app)")
    print(f"   Physical space: {pw} x {ph}   (what a screenshot captures)")
    print(f"   Scaling       : {scale_x:.2f}x")
    print()
    print("   >>> TAKE YOUR HAND OFF THE MOUSE AND LEAVE IT ALONE. <<<")
    print("   The cursor will move on its own. Any nudge corrupts a reading,")
    print("   though the test now detects that and retries rather than")
    print("   reporting a false failure.")
    print()
    input("   Press Enter when your hand is off the mouse: ")

    origin = wi.get_cursor_pos()

    logical_worst, logical_skipped = sweep(
        "A. Logical coordinates", physical=False
    )
    physical_worst, physical_skipped = sweep(
        "B. Physical coordinates — the space the screenshots use", physical=True
    )

    wi.move_mouse_to(*origin)

    banner("Verdict")

    def verdict(name, worst, skipped, tolerance):
        if worst is None:
            print(f"   {name}: no usable readings")
            return False
        if worst <= tolerance:
            print(f"   {name}: ACCURATE (worst {worst} px)")
            return True
        print(f"   {name}: INACCURATE (worst {worst} px)")
        return False

    ok_logical = verdict("Logical ", logical_worst, logical_skipped, 2)
    ok_physical = verdict("Physical", physical_worst, physical_skipped, 3)

    print()
    if ok_logical and ok_physical:
        print("   Both work. The star map will use physical coordinates, so the")
        print("   numbers measured from your screenshots are used directly with")
        print("   no conversion.")
    elif ok_physical:
        print("   Physical addressing works. That is the one the star map needs.")
    elif ok_logical:
        print("   Logical works but physical does not — send me this output.")
    else:
        print("   Neither is accurate. Send me this output; if points were")
        print("   skipped, try once more without touching the mouse at all.")

    total_skipped = logical_skipped + physical_skipped
    if total_skipped:
        print()
        print(f"   Note: {total_skipped} point(s) skipped due to mouse movement.")
        print("   If that number is high, the readings above are less reliable.")

    return 0 if (ok_logical or ok_physical) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
