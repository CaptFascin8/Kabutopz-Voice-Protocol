"""Minimal outbound-only Windows input simulation.

This module intentionally uses the documented Windows SendInput API instead
of third-party packages that install global keyboard or mouse hooks. The app
only needs to send configured commands to the foreground game window.
"""

import ctypes
import re
import threading
import time
from ctypes import wintypes


if not hasattr(ctypes, "windll"):
    raise RuntimeError("Kabutopz Voice Protocol input requires Windows.")


ULONG_PTR = (
    ctypes.c_ulonglong
    if ctypes.sizeof(ctypes.c_void_p) == 8
    else ctypes.c_ulong
)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    )


class INPUT_DATA(ctypes.Union):
    _fields_ = (
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
        ("hi", HARDWAREINPUT),
    )


class INPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = (("type", wintypes.DWORD), ("data", INPUT_DATA))


INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MAPVK_VK_TO_VSC = 0

KEYEVENTF_UNICODE = 0x0004

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000
WHEEL_DELTA = 120

# GetSystemMetrics indices. The VIRTUALSCREEN family covers every monitor as
# one rectangle; SM_CXSCREEN alone only describes the primary display, which
# is the classic reason synthetic clicks land on the wrong monitor.
SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

# GetDeviceCaps indices, used to detect Windows display scaling without
# changing this process's DPI awareness.
HORZRES = 8
VERTRES = 10
DESKTOPVERTRES = 117
DESKTOPHORZRES = 118


_VK_NAMES = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "shift": 0x10,
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "pause": 0x13,
    "caps lock": 0x14,
    "escape": 0x1B,
    "esc": 0x1B,
    "space": 0x20,
    "page up": 0x21,
    "page down": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "insert": 0x2D,
    "delete": 0x2E,
    "left windows": 0x5B,
    "right windows": 0x5C,
    "num multiply": 0x6A,
    "num plus": 0x6B,
    "num minus": 0x6D,
    "num decimal": 0x6E,
    "num divide": 0x6F,
    "num lock": 0x90,
    "scroll lock": 0x91,
    "left shift": 0xA0,
    "right shift": 0xA1,
    "left ctrl": 0xA2,
    "right ctrl": 0xA3,
    "left control": 0xA2,
    "right control": 0xA3,
    "left alt": 0xA4,
    "right alt": 0xA5,
    ";": 0xBA,
    "=": 0xBB,
    ",": 0xBC,
    "-": 0xBD,
    ".": 0xBE,
    "/": 0xBF,
    "`": 0xC0,
    "[": 0xDB,
    "\\": 0xDC,
    "]": 0xDD,
    "'": 0xDE,
}

for number in range(10):
    _VK_NAMES[str(number)] = 0x30 + number
    _VK_NAMES[f"num {number}"] = 0x60 + number
    _VK_NAMES[f"numpad {number}"] = 0x60 + number

for letter in "abcdefghijklmnopqrstuvwxyz":
    _VK_NAMES[letter] = ord(letter.upper())

for number in range(1, 25):
    _VK_NAMES[f"f{number}"] = 0x6F + number


_EXTENDED_KEYS = {
    "right alt",
    "right ctrl",
    "right control",
    "left windows",
    "right windows",
    "insert",
    "delete",
    "home",
    "end",
    "page up",
    "page down",
    "left",
    "right",
    "up",
    "down",
    "num divide",
    "num lock",
}


class POINT(ctypes.Structure):
    _fields_ = (("x", wintypes.LONG), ("y", wintypes.LONG))


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SendInput.argtypes = (
    wintypes.UINT,
    ctypes.POINTER(INPUT),
    ctypes.c_int,
)
_user32.SendInput.restype = wintypes.UINT
_user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
_user32.MapVirtualKeyW.restype = wintypes.UINT
_user32.RegisterHotKey.argtypes = (
    wintypes.HWND,
    ctypes.c_int,
    wintypes.UINT,
    wintypes.UINT,
)
_user32.RegisterHotKey.restype = wintypes.BOOL
_user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.UnregisterHotKey.restype = wintypes.BOOL
_user32.GetMessageW.argtypes = (
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
)
_user32.GetMessageW.restype = ctypes.c_int

_user32.GetCursorPos.argtypes = (ctypes.POINTER(POINT),)
_user32.GetCursorPos.restype = wintypes.BOOL
_user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
_user32.GetSystemMetrics.restype = ctypes.c_int
_user32.GetDC.argtypes = (wintypes.HWND,)
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
_user32.ReleaseDC.restype = ctypes.c_int

_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
_gdi32.GetDeviceCaps.argtypes = (wintypes.HDC, ctypes.c_int)
_gdi32.GetDeviceCaps.restype = ctypes.c_int

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD
_user32.PostThreadMessageW.argtypes = (
    wintypes.DWORD,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
_user32.PostThreadMessageW.restype = wintypes.BOOL

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012


def _normalize_key_name(name):
    normalized = re.sub(r"\s+", " ", str(name).strip().lower())
    aliases = {
        "lalt": "left alt",
        "ralt": "right alt",
        "lctrl": "left ctrl",
        "rctrl": "right ctrl",
        "lshift": "left shift",
        "rshift": "right shift",
        "pgup": "page up",
        "pgdn": "page down",
        "del": "delete",
        "ins": "insert",
        "win": "left windows",
        "windows": "left windows",
    }
    return aliases.get(normalized, normalized)


def resolve_key(name):
    """Return ``(virtual_key, is_extended)`` for a configured key name."""
    normalized = _normalize_key_name(name)
    try:
        return _VK_NAMES[normalized], normalized in _EXTENDED_KEYS
    except KeyError as exc:
        raise ValueError(f"Unsupported key name: {name}") from exc


def _send(packet):
    if _user32.SendInput(1, ctypes.byref(packet), ctypes.sizeof(INPUT)) != 1:
        raise ctypes.WinError(ctypes.get_last_error())


def _key_event(name, key_up=False):
    virtual_key, extended = resolve_key(name)
    scan_code = _user32.MapVirtualKeyW(virtual_key, MAPVK_VK_TO_VSC)
    flags = KEYEVENTF_SCANCODE
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    if key_up:
        flags |= KEYEVENTF_KEYUP
    _send(
        INPUT(
            type=INPUT_KEYBOARD,
            ki=KEYBDINPUT(
                wVk=0,
                wScan=scan_code,
                dwFlags=flags,
                time=0,
                dwExtraInfo=0,
            ),
        )
    )


def _key_parts(keybind):
    parts = [_normalize_key_name(part) for part in str(keybind).split("+")]
    parts = [part for part in parts if part]
    if not parts:
        raise ValueError("Keybind cannot be empty.")
    for part in parts:
        resolve_key(part)
    return parts


def parse_global_hotkey(keybind):
    """Translate a keybind like ``ctrl+shift+f8`` for RegisterHotKey."""
    parts = _key_parts(keybind)
    modifiers = 0
    modifier_keys = {
        "alt": MOD_ALT,
        "left alt": MOD_ALT,
        "right alt": MOD_ALT,
        "ctrl": MOD_CONTROL,
        "control": MOD_CONTROL,
        "left ctrl": MOD_CONTROL,
        "right ctrl": MOD_CONTROL,
        "left control": MOD_CONTROL,
        "right control": MOD_CONTROL,
        "shift": MOD_SHIFT,
        "left shift": MOD_SHIFT,
        "right shift": MOD_SHIFT,
        "left windows": MOD_WIN,
        "right windows": MOD_WIN,
    }

    main_keys = []
    for part in parts:
        if part in modifier_keys:
            modifiers |= modifier_keys[part]
        else:
            main_keys.append(part)

    if len(main_keys) != 1:
        raise ValueError(
            "Use one main key, for example F8 or Ctrl+Shift+V."
        )

    virtual_key, _ = resolve_key(main_keys[0])
    return modifiers | MOD_NOREPEAT, virtual_key


class GlobalHotkey:
    """A small global Windows hotkey listener with no keyboard hook."""

    _HOTKEY_ID = 0x4B56

    def __init__(self, keybind, callback):
        self.keybind = str(keybind).strip().lower()
        self.callback = callback
        self.modifiers, self.virtual_key = parse_global_hotkey(self.keybind)
        self._thread = None
        self._thread_id = None
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._error = None

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="KabutopzVoiceToggleHotkey",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=1.5):
            raise RuntimeError("Timed out while registering the toggle keybind.")
        if self._error is not None:
            raise self._error

    def _run(self):
        try:
            self._thread_id = _kernel32.GetCurrentThreadId()
            if not _user32.RegisterHotKey(
                None,
                self._HOTKEY_ID,
                self.modifiers,
                self.virtual_key,
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            self._ready.set()

            message = wintypes.MSG()
            while _user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == WM_HOTKEY:
                    self.callback()
        except Exception as exc:
            self._error = exc
            self._ready.set()
        finally:
            if self._thread_id is not None:
                _user32.UnregisterHotKey(None, self._HOTKEY_ID)
            self._stopped.set()

    def stop(self):
        if self._thread_id is not None:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._stopped.wait(timeout=1.0)


def press_keybind(keybind):
    parts = _key_parts(keybind)
    pressed = []
    try:
        for part in parts:
            _key_event(part)
            pressed.append(part)
    except Exception:
        for part in reversed(pressed):
            _key_event(part, key_up=True)
        raise
    return parts


def release_keybind(parts):
    for part in reversed(parts):
        _key_event(part, key_up=True)


# "toggle quantum" (tap B) did nothing in game while "engage quantum"
# (the same key held 1.2s) always worked. A 40ms press is under one frame
# at 25fps, so the game's input poll can miss the whole event. 90ms
# survives a bad frame and is still far below Star Citizen's tap/hold
# threshold, so a tap is never mistaken for a hold.
def tap_keybind(keybind, tap_seconds=0.09):
    parts = press_keybind(keybind)
    try:
        time.sleep(tap_seconds)
    finally:
        release_keybind(parts)


def hold_keybind(keybind, hold_seconds):
    parts = press_keybind(keybind)
    try:
        time.sleep(float(hold_seconds))
    finally:
        release_keybind(parts)


def _mouse_event(flags, data=0, dx=0, dy=0):
    _send(
        INPUT(
            type=INPUT_MOUSE,
            mi=MOUSEINPUT(
                dx=int(dx),
                dy=int(dy),
                mouseData=data,
                dwFlags=flags,
                time=0,
                dwExtraInfo=0,
            ),
        )
    )


def click_mouse(button):
    normalized = _normalize_key_name(button)
    if normalized == "left":
        down_flag, up_flag = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
    elif normalized == "right":
        down_flag, up_flag = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
    else:
        raise ValueError(f"Unsupported mouse button: {button}")
    _mouse_event(down_flag)
    time.sleep(0.04)
    _mouse_event(up_flag)


def scroll_wheel(direction):
    amount = -WHEEL_DELTA if str(direction).lower() == "down" else WHEEL_DELTA
    _mouse_event(MOUSEEVENTF_WHEEL, ctypes.c_ulong(amount).value)


def tap_mouse_combo(keybind):
    normalized = str(keybind).strip().lower()
    match = re.fullmatch(r"(?:(.+)\+)?(left|right) mouse", normalized)
    if not match:
        raise ValueError(f"Unsupported mouse combo: {keybind}")

    modifier, button = match.groups()
    pressed = press_keybind(modifier) if modifier else []
    try:
        click_mouse(button)
    finally:
        if pressed:
            release_keybind(pressed)


# ---------------------------------------------------------------------------
# Screen geometry, cursor position, and display scaling.
#
# Nothing here changes this process's DPI awareness on purpose. Making the
# app DPI-aware would fix coordinate math but shrink the whole tkinter UI on
# a scaled display, so instead we measure the scale factor and let callers
# convert when they need physical pixels (for example when handing a capture
# region to an external screenshot tool).
# ---------------------------------------------------------------------------


def screen_metrics(physical=False):
    """Return the virtual desktop as ``(left, top, width, height)``.

    The virtual desktop is the bounding rectangle of every monitor. On a
    single-monitor machine this is just ``(0, 0, width, height)``.

    By default this is the *logical* space Windows reports to this
    DPI-unaware process — 1280x720 on a 4K display at 300% scaling. Pass
    ``physical=True`` for real device pixels, which is the space
    screenshots and OCR results live in.
    """
    left = _user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    top = _user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = _user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    height = _user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

    if width <= 0 or height <= 0:
        # Fall back to the primary display if the virtual metrics are
        # unavailable, which can happen on unusual driver setups.
        left, top = 0, 0
        width = _user32.GetSystemMetrics(SM_CXSCREEN)
        height = _user32.GetSystemMetrics(SM_CYSCREEN)

    if width <= 0 or height <= 0:
        raise RuntimeError("Could not determine the screen size.")

    if physical:
        scale_x, scale_y = dpi_scale()
        return (
            int(round(left * scale_x)),
            int(round(top * scale_y)),
            int(round(width * scale_x)),
            int(round(height * scale_y)),
        )

    return left, top, width, height


def to_physical(x, y):
    """Convert logical (Windows-reported) coordinates to device pixels."""
    scale_x, scale_y = dpi_scale()
    return int(round(x * scale_x)), int(round(y * scale_y))


def to_logical(x, y):
    """Convert device pixels to logical (Windows-reported) coordinates."""
    scale_x, scale_y = dpi_scale()
    if scale_x == 0 or scale_y == 0:
        return int(x), int(y)
    return int(round(x / scale_x)), int(round(y / scale_y))


def get_cursor_pos(physical=False):
    """Return the mouse cursor position as ``(x, y)``.

    Logical coordinates by default; ``physical=True`` returns device
    pixels, matching what a screenshot would show.
    """
    point = POINT()
    if not _user32.GetCursorPos(ctypes.byref(point)):
        raise ctypes.WinError(ctypes.get_last_error())
    if physical:
        return to_physical(point.x, point.y)
    return point.x, point.y


def dpi_scale():
    """Return ``(scale_x, scale_y)`` between reported and physical pixels.

    Returns ``(1.0, 1.0)`` when Windows display scaling is off or when this
    process is already DPI-aware. On a 4K display set to 150% scaling from a
    DPI-unaware process this returns roughly ``(1.5, 1.5)``.
    """
    hdc = _user32.GetDC(None)
    if not hdc:
        return 1.0, 1.0
    try:
        logical_x = _gdi32.GetDeviceCaps(hdc, HORZRES)
        logical_y = _gdi32.GetDeviceCaps(hdc, VERTRES)
        physical_x = _gdi32.GetDeviceCaps(hdc, DESKTOPHORZRES)
        physical_y = _gdi32.GetDeviceCaps(hdc, DESKTOPVERTRES)
    finally:
        _user32.ReleaseDC(None, hdc)

    if logical_x <= 0 or logical_y <= 0:
        return 1.0, 1.0
    return physical_x / float(logical_x), physical_y / float(logical_y)


def move_mouse_to(x, y, physical=False):
    """Move the cursor to an absolute desktop position.

    Coordinates are logical by default. Pass ``physical=True`` to use
    device pixels, which is what screenshot measurements and OCR bounding
    boxes are expressed in.

    The normalization below is proportional, so it produces the same
    result in either space as long as the point and the screen metrics
    agree — which is exactly why both are read with the same flag.
    """
    left, top, width, height = screen_metrics(physical=physical)
    if width < 2 or height < 2:
        raise RuntimeError("Screen is too small to address absolutely.")

    # SendInput absolute coordinates are normalized to 0-65535 across the
    # whole virtual desktop, not measured in pixels.
    norm_x = int(round((int(x) - left) * 65535.0 / (width - 1)))
    norm_y = int(round((int(y) - top) * 65535.0 / (height - 1)))
    norm_x = max(0, min(65535, norm_x))
    norm_y = max(0, min(65535, norm_y))

    _mouse_event(
        MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
        0,
        norm_x,
        norm_y,
    )


def click_at(x, y, button="left", settle_seconds=0.06, physical=False):
    """Move to ``(x, y)`` and click, giving the target time to hover-focus."""
    move_mouse_to(x, y, physical=physical)
    time.sleep(max(0.0, float(settle_seconds)))
    click_mouse(button)


# ---------------------------------------------------------------------------
# Text entry.
#
# Scancodes first, because that is exactly how every keybind in this app is
# already delivered and games are known to accept it. KEYEVENTF_UNICODE is
# only used for characters with no scancode, since some games ignore it.
# ---------------------------------------------------------------------------

_TYPE_MAP = {}

for _character in "abcdefghijklmnopqrstuvwxyz0123456789":
    _TYPE_MAP[_character] = (_character, False)

for _character in "abcdefghijklmnopqrstuvwxyz":
    _TYPE_MAP[_character.upper()] = (_character, True)

_TYPE_MAP[" "] = ("space", False)
_TYPE_MAP["\t"] = ("tab", False)
_TYPE_MAP["\n"] = ("enter", False)

for _character in ";=,-./`[]\\'":
    _TYPE_MAP[_character] = (_character, False)

for _character, _base in {
    "!": "1", "@": "2", "#": "3", "$": "4", "%": "5",
    "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
    "_": "-", "+": "=", "{": "[", "}": "]", "|": "\\",
    ":": ";", '"': "'", "<": ",", ">": ".", "?": "/", "~": "`",
}.items():
    _TYPE_MAP[_character] = (_base, True)

del _character


def type_unicode(text):
    """Send characters as Unicode packets. Some games ignore these."""
    for character in str(text):
        for key_up in (False, True):
            flags = KEYEVENTF_UNICODE
            if key_up:
                flags |= KEYEVENTF_KEYUP
            _send(
                INPUT(
                    type=INPUT_KEYBOARD,
                    ki=KEYBDINPUT(
                        wVk=0,
                        wScan=ord(character),
                        dwFlags=flags,
                        time=0,
                        dwExtraInfo=0,
                    ),
                )
            )


def plan_typing(text, unicode_fallback=True):
    """Turn ``text`` into the key events needed to type it.

    Yields ``("shift", True/False)``, ``("key", name)`` and
    ``("unicode", character)`` steps. Shift is raised once for a whole run of
    characters that need it and lowered once afterwards, the way a person
    types, and it is always lowered at the end.

    Split out from :func:`type_text` purely so the sequencing can be tested
    without a keyboard — the shift bug this fixes was invisible in code
    review and only showed up as "HUR_L%" on screen.
    """
    shift = False
    for character in str(text):
        entry = _TYPE_MAP.get(character)

        if entry is None:
            if shift:
                shift = False
                yield ("shift", False)
            if not unicode_fallback:
                raise ValueError(f"Cannot type character: {character!r}")
            yield ("unicode", character)
            continue

        key_name, needs_shift = entry
        if needs_shift != shift:
            shift = needs_shift
            yield ("shift", shift)
        yield ("key", key_name)

    if shift:
        yield ("shift", False)


def type_text(text, interval=0.03, press_seconds=0.03, unicode_fallback=True,
              shift_settle=0.02):
    """Type ``text`` one character at a time.

    ``interval`` is the pause between characters. Typing faster than about
    0.02s per character tends to drop characters in game text fields.

    Shift is **held across a run** of characters that all need it, and every
    transition gets ``shift_settle`` on both sides. Typing "HUR-L5" into Star
    Citizen used to produce "HUR_L%": each character toggled shift on its own,
    and with only 12ms between shift down and shift up, two characters could
    land inside one game frame and both get the same sampled shift state. The
    unshifted "-" and "5" inherited the shift belonging to "R" and "L".

    Holding shift the way a human does means far fewer transitions, and the
    settle time keeps each one clear of its neighbours' key events.
    """
    shift_down = False

    def set_shift(wanted):
        nonlocal shift_down
        if wanted == shift_down:
            return
        _key_event("left shift", key_up=not wanted)
        shift_down = wanted
        time.sleep(max(0.0, float(shift_settle)))

    try:
        for kind, value in plan_typing(text, unicode_fallback=unicode_fallback):
            if kind == "shift":
                set_shift(value)
            elif kind == "unicode":
                type_unicode(value)
                time.sleep(max(0.0, float(interval)))
            else:
                _key_event(value)
                time.sleep(max(0.0, float(press_seconds)))
                _key_event(value, key_up=True)
                time.sleep(max(0.0, float(interval)))
    finally:
        set_shift(False)


def clear_text_field():
    """Select-all then delete, for reusing a field that already has text."""
    tap_keybind("ctrl+a")
    time.sleep(0.05)
    tap_keybind("delete")
