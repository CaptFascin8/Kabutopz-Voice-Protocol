"""Headless startup smoke test: build the real UI under a virtual display.

Catches the class of bug that only appears at launch — a page registered in
one place but not another, a missing widget attribute, a bad theme key.
Stubs only the Windows-specific edges (audio, SendInput, OCR).
"""
import sys, types, traceback
import os, tempfile

# --- isolate settings.json --------------------------------------------
# APP_DIR is Path.home()/".star_citizen_voice_keybinds", so without this the
# test writes into the real profile and every run appends another custom
# command — which made "custom command created" fail on the second run for
# reasons that had nothing to do with the code under test.
_HOME = tempfile.mkdtemp(prefix="kvp-smoke-home-")
os.environ["HOME"] = _HOME
os.environ["USERPROFILE"] = _HOME

# --- stub the Windows-only edges -------------------------------------
sd = types.ModuleType("sounddevice")
sd.query_devices = lambda *a, **k: []
sd.RawInputStream = object
sys.modules["sounddevice"] = sd

sr = types.ModuleType("speech_recognition")
class _R:
    def recognize_google(self, *a, **k): return ""
sr.Recognizer = _R
sr.AudioData = object
sr.UnknownValueError = type("UnknownValueError", (Exception,), {})
sr.RequestError = type("RequestError", (Exception,), {})
sys.modules["speech_recognition"] = sr

wi = types.ModuleType("win_input")
class _HK:
    def __init__(self,*a,**k): pass
    def start(self): pass
    def stop(self): pass
wi.GlobalHotkey = _HK
for fn in ("click_at","clear_text_field","hold_keybind","move_mouse_to","scroll_wheel",
           "tap_keybind","tap_mouse_combo","type_text"):
    setattr(wi, fn, lambda *a, **k: None)
wi.dpi_scale = lambda: (1.0, 1.0)
wi.get_cursor_pos = lambda physical=False: (0, 0)
wi.screen_metrics = lambda physical=False: (0, 0, 1920, 1080)
wi.parse_global_hotkey = lambda kb: (0, 0)
sys.modules["win_input"] = wi

oc = types.ModuleType("win_ocr")
oc.ocr_region = lambda *a, **k: {"ok": True, "lines": []}
oc.line_center = lambda l: (0, 0)
oc.ocr_status = lambda: (True, "Windows OCR available (en-US)")
sys.modules["win_ocr"] = oc

# Import from this script's own folder, wherever it has been copied to.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import importlib.util
spec = importlib.util.spec_from_file_location(
    "kvpapp", os.path.join(_HERE, "starcitizen_voice_keybinds.py"))
mod = importlib.util.module_from_spec(spec)

failures = []
try:
    spec.loader.exec_module(mod)
    print("PASS  module imports")
except Exception:
    traceback.print_exc(); sys.exit(1)

try:
    app = mod.VoiceKeybindApp()
    print("PASS  VoiceKeybindApp() constructed — every page built")
except Exception:
    print("FAIL  constructor raised:")
    traceback.print_exc(); sys.exit(1)

# Every page in PAGE_ORDER must actually show without raising.
for page in mod.PAGE_ORDER:
    try:
        app.show_page(page)
        app.update_idletasks()
        print(f"PASS  show_page({page!r})")
    except Exception as exc:
        failures.append(f"show_page({page!r}): {exc}")
        print(f"FAIL  show_page({page!r}): {exc}")

# The new widgets must exist and respond.
for name in ("starmap_page","starmap_x_var","starmap_system_var","starmap_test_var",
             "starmap_status_label","repeat_list","repeat_default_var",
             "custom_repeat_var","custom_repeat_interval_var","custom_repeat_cancel_var",
             "custom_repeat_reply_var"):
    ok = hasattr(app, name)
    print(f"{'PASS' if ok else 'FAIL'}  widget {name}")
    if not ok: failures.append(f"missing widget {name}")

try:
    app._refresh_repeat_list(); app._refresh_starmap_page(); app._starmap_apply_toggles()
    app._clear_custom_word_form(); app.apply_theme(); app._save_settings()
    print("PASS  refresh/apply/save round-trip")
except Exception as exc:
    failures.append(f"round-trip: {exc}"); print(f"FAIL  round-trip: {exc}"); traceback.print_exc()

# ---- layout: is every control actually reachable? --------------------
def _find(widget, text):
    """Depth-first search for a button/label carrying this text."""
    try:
        if str(widget.cget("text")).strip().upper() == text.upper():
            return widget
    except Exception:
        pass
    for child in widget.winfo_children():
        hit = _find(child, text)
        if hit is not None:
            return hit
    return None

try:
    # Force the window to the app's minimum size — the worst realistic case.
    app.geometry("1020x700")
    app.update_idletasks(); app.update()

    for page, button in (("CUSTOM WORDS", "CREATE CUSTOM COMMAND"),
                         ("CUSTOM WORDS", "CLEAR FORM"),
                         ("CUSTOM WORDS", "DELETE CUSTOM COMMAND"),
                         ("STAR MAP", "TEST ROUTE"),
                         ("STAR MAP", "CAPTURE POSITION (5S)")):
        app.show_page(page); app.update_idletasks(); app.update()
        w = _find(app, button)
        if w is None:
            print(f"FAIL  {page}: button {button!r} not found at all")
            failures.append(f"{button} missing"); continue
        # A widget inside a scroll canvas has a real height once mapped;
        # reachability means the scrollregion covers it.
        h = w.winfo_height(); y = w.winfo_rooty() - app.winfo_rooty()
        ok = h > 1
        print(f"{'PASS' if ok else 'FAIL'}  {page}: {button!r} laid out "
              f"(h={h}, y={y})")
        if not ok: failures.append(f"{button} not laid out")

    # The scroll container must report a scrollregion taller than the viewport,
    # otherwise there is nothing to scroll to and the button stays hidden.
    def _canvases(w, out):
        if isinstance(w, mod.tk.Canvas): out.append(w)
        for c in w.winfo_children(): _canvases(c, out)
        return out
    app.show_page("CUSTOM WORDS"); app.update_idletasks(); app.update()
    found = [c for c in _canvases(app.custom_words_page, [])
             if c.cget("scrollregion")]
    ok = bool(found)
    print(f"{'PASS' if ok else 'FAIL'}  CUSTOM WORDS has a live scrollregion "
          f"({[c.cget('scrollregion') for c in found]})")
    if not ok: failures.append("no scrollregion")
except Exception as exc:
    failures.append(f"layout: {exc}"); print(f"FAIL  layout: {exc}"); traceback.print_exc()

# ---- the decisive check: does scrolling REVEAL the hidden button? -----
try:
    app.show_page("CUSTOM WORDS"); app.update_idletasks(); app.update()
    btn = _find(app, "CREATE CUSTOM COMMAND")
    canvas = [c for c in _canvases(app.custom_words_page, []) if c.cget("scrollregion")][0]

    win_h = app.winfo_height()
    before = btn.winfo_rooty() - app.winfo_rooty()
    canvas.yview_moveto(1.0)
    app.update_idletasks(); app.update()
    after = btn.winfo_rooty() - app.winfo_rooty()

    moved = after < before
    visible = 0 <= after <= win_h
    print(f"      window height {win_h}px")
    print(f"      button y before scroll: {before}  (visible: {0 <= before <= win_h})")
    print(f"      button y after  scroll: {after}  (visible: {visible})")
    print(f"{'PASS' if moved else 'FAIL'}  scrolling moves the button up")
    if not moved: failures.append("scroll does not move content")
    print(f"{'PASS' if visible else 'FAIL'}  CREATE CUSTOM COMMAND reachable after scrolling")
    if not visible: failures.append("button still unreachable")

    canvas.yview_moveto(0.0); app.update_idletasks()
except Exception as exc:
    failures.append(f"scroll reveal: {exc}"); print(f"FAIL  scroll reveal: {exc}"); traceback.print_exc()

# ---- functional: create the AFK command the way the UI does ----------
import time as _t
try:
    mod.messagebox.showinfo = lambda *a, **k: None
    mod.messagebox.showerror = lambda *a, **k: failures.append(f"showerror: {a}")
    mod.messagebox.askyesno = lambda *a, **k: True

    app.custom_name_var.set("AFK")
    app.custom_category_var.set("Special")
    app.custom_key_var.set("f1")
    app.custom_type_var.set("tap")
    app.custom_repeat_var.set(True)
    app.custom_repeat_interval_var.set("0.15")
    app.custom_repeat_cancel_var.set("i'm back, im back")
    app.custom_repeat_reply_var.set("Welcome back.")
    app.custom_phrase_var.set("away from keyboard"); app._add_custom_phrase_row()
    app.custom_phrase_var.set("afk"); app._add_custom_phrase_row()
    app._create_custom_command()

    ids = [a["id"] for a in app.custom_actions]
    ok = len(ids) == 1
    print(f"{'PASS' if ok else 'FAIL'}  custom command created ({ids})")
    if not ok: failures.append("custom command not created")
    else:
        aid = ids[0]
        rec = app.custom_actions[0]
        for key, want in (("repeat", True), ("repeat_interval", 0.15),
                          ("repeat_cancel_response", "Welcome back.")):
            good = rec.get(key) == want
            print(f"{'PASS' if good else 'FAIL'}  record {key} = {rec.get(key)!r}")
            if not good: failures.append(f"record {key}")
        good = rec.get("repeat_cancel_phrases") == ["i'm back", "im back"]
        print(f"{'PASS' if good else 'FAIL'}  stop phrases parsed {rec.get('repeat_cancel_phrases')}")
        if not good: failures.append("stop phrases")

        # the phrase must reach the matcher
        pairs = dict((p, a) for p, a in app._build_phrase_matcher())
        good = pairs.get("away from keyboard") == aid and pairs.get("afk") == aid
        print(f"{'PASS' if good else 'FAIL'}  phrases registered in the matcher")
        if not good: failures.append("phrases not in matcher")

        # start it, then cancel by its own stop phrase
        app._begin_repeat(aid); _t.sleep(0.4)
        running = app.repeats.is_active(aid)
        print(f"{'PASS' if running else 'FAIL'}  repeat running")
        if not running: failures.append("repeat did not start")
        hit = app._repeat_cancel_match("i'm back")
        good = hit == aid
        print(f"{'PASS' if good else 'FAIL'}  \"i'm back\" matches the running repeat")
        if not good: failures.append("stop phrase did not match")
        app.repeats.stop(aid, announce=False); _t.sleep(0.2)
        stopped = not app.repeats.is_active(aid)
        print(f"{'PASS' if stopped else 'FAIL'}  repeat stopped")
        if not stopped: failures.append("repeat did not stop")
        # inert when nothing is running
        good = app._repeat_cancel_match("i'm back") is None
        print(f"{'PASS' if good else 'FAIL'}  stop phrase inert when nothing repeats")
        if not good: failures.append("stop phrase not inert")
except Exception as exc:
    failures.append(f"custom command flow: {exc}")
    print(f"FAIL  custom command flow: {exc}"); traceback.print_exc()

# ---- functional: star map voice grammar ------------------------------
try:
    calls = []
    app._run_starmap = lambda fn, *a: calls.append((getattr(fn, "__name__", str(fn)), a)) or True
    for heard, expect in [("open star map", "open_map"),
                          ("plot a course to grim hex", "_starmap_route"),
                          ("take me to daymar", "_starmap_route"),
                          ("close star map", "close_map")]:
        calls.clear()
        handled = app._handle_starmap_speech(heard)
        got = calls[0][0] if calls else None
        good = handled and got == expect
        print(f"{'PASS' if good else 'FAIL'}  \"{heard}\" -> {got}")
        if not good: failures.append(f"grammar {heard}")
    good = not app._handle_starmap_speech("shields front")
    print(f"{'PASS' if good else 'FAIL'}  a plain keybind phrase falls through")
    if not good: failures.append("keybind phrase intercepted")
    app._handle_starmap_speech("set system to pyro")
    good = app.starmap.current_system == "Pyro"
    print(f"{'PASS' if good else 'FAIL'}  \"set system to pyro\" -> {app.starmap.current_system}")
    if not good: failures.append("set system")
except Exception as exc:
    failures.append(f"grammar: {exc}"); print(f"FAIL  grammar: {exc}"); traceback.print_exc()

# ---- functional: phrases resolve to the action they name -------------
try:
    matcher = app._build_phrase_matcher()

    def _resolve(heard):
        for phrase, action_id in matcher:
            if phrase in heard:
                return action_id
        return None

    for heard, expect in [("toggle quantum", "quantum_toggle"),
                          ("quantum mode", "quantum_toggle"),
                          ("nav mode", "quantum_toggle"),
                          ("engage quantum", "quantum_engage"),
                          ("quantum jump", "quantum_engage")]:
        got = _resolve(heard)
        good = got == expect
        print(f"{'PASS' if good else 'FAIL'}  \"{heard}\" -> {got}")
        if not good: failures.append(f"phrase {heard} -> {got}")
        # the star map grammar must not swallow it first
        good = not app._handle_starmap_speech(heard)
        print(f"{'PASS' if good else 'FAIL'}  \"{heard}\" reaches the keybind matcher")
        if not good: failures.append(f"{heard} intercepted by star map")

    # A tap under one frame of game time gets dropped by Star Citizen's
    # input poll; this is why "toggle quantum" did nothing while
    # "engage quantum" (the same key, held) always worked.
    # win_input is stubbed above, so read the real default out of the source.
    import ast as _ast, pathlib as _pl
    _tree = _ast.parse((_pl.Path(__file__).parent / "win_input.py").read_text())
    def _defaults(name):
        fn = next(f for f in _ast.walk(_tree)
                  if isinstance(f, _ast.FunctionDef) and f.name == name)
        args = fn.args.args[-len(fn.args.defaults):] if fn.args.defaults else []
        return {a.arg: _ast.literal_eval(d)
                for a, d in zip(args, fn.args.defaults)}

    tap_default = _defaults("tap_keybind")["tap_seconds"]
    good = tap_default >= 0.08
    print(f"{'PASS' if good else 'FAIL'}  tap press is {tap_default*1000:.0f}ms (>=80ms)")
    if not good: failures.append(f"tap too short: {tap_default}")

    # "HUR-L5" typed as "HUR_L%": shift toggled per character with no margin,
    # so two characters could share one sampled shift state inside a frame.
    typing = _defaults("type_text")
    for field, floor in [("press_seconds", 0.025), ("shift_settle", 0.015)]:
        value = typing.get(field)
        good = value is not None and value >= floor
        print(f"{'PASS' if good else 'FAIL'}  type_text {field} = {value} "
              f"(>={floor})")
        if not good: failures.append(f"type_text {field}: {value}")
except Exception as exc:
    failures.append(f"phrase resolution: {exc}")
    print(f"FAIL  phrase resolution: {exc}"); traceback.print_exc()

try:
    try:
        app.repeats.start("quit_star_citizen","Turn Off SC","tap","alt+f4",None,1.0)
        print("FAIL  alt+F4 repeat was allowed"); failures.append("NEVER_REPEAT")
    except ValueError:
        print("PASS  alt+F4 still refuses to repeat")
    app.repeats.stop_all(announce=False); app.destroy()
    print("PASS  clean shutdown")
except Exception as exc:
    failures.append(f"shutdown: {exc}"); print(f"FAIL  shutdown: {exc}")

print("\n" + ("SMOKE TEST PASSED" if not failures else f"{len(failures)} FAILURES: {failures}"))
sys.exit(1 if failures else 0)
