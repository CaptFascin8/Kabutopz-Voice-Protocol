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

# Every page in PAGE_ORDER must show — and must show the RIGHT frame.
#
# Checking only that show_page() does not raise is what let a missing
# entry through: show_page fell back to the voice page, so selecting
# VOICE CLONES silently displayed VOICE PROTOCOL. No error, no clue.
for page in mod.PAGE_ORDER:
    try:
        app.show_page(page)
        app.update_idletasks()

        expected = app.page_frames[page]
        showing = [
            name for name, frame in app.page_frames.items()
            if frame.winfo_ismapped()
        ]
        good = showing == [page] and expected.winfo_ismapped()
        print(f"{'PASS' if good else 'FAIL'}  show_page({page!r}) "
              f"-> {showing}")
        if not good:
            failures.append(f"show_page({page!r}) showed {showing}")
    except Exception as exc:
        failures.append(f"show_page({page!r}): {exc}")
        print(f"FAIL  show_page({page!r}): {exc}")

# Every tab must be able to reach a frame, and vice versa. _register_pages
# raises at startup if not, so getting here at all is most of the proof.
try:
    good = set(app.page_frames) == set(mod.PAGE_ORDER)
    print(f"{'PASS' if good else 'FAIL'}  every page in PAGE_ORDER has a frame")
    if not good:
        failures.append("page frames and PAGE_ORDER disagree")
except Exception as exc:
    failures.append(f"page registry: {exc}")

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
                         ("CUSTOMIZE", "ENABLE WAKE WORD MODE"),
                         ("CUSTOMIZE", "RESET TO INDUSTRIAL ORANGE"),
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
for _page, _attr, _button in (("CUSTOM WORDS", "custom_words_page", "CREATE CUSTOM COMMAND"),
                              ("CUSTOMIZE", "customize_page", "RESET TO INDUSTRIAL ORANGE")):
    try:
        app.show_page(_page); app.update_idletasks(); app.update()
        btn = _find(app, _button)
        canvas = [c for c in _canvases(getattr(app, _attr), []) if c.cget("scrollregion")][0]

        win_h = app.winfo_height()
        before = btn.winfo_rooty() - app.winfo_rooty()
        canvas.yview_moveto(1.0)
        app.update_idletasks(); app.update()
        after = btn.winfo_rooty() - app.winfo_rooty()

        moved = after < before
        visible = 0 <= after <= win_h
        print(f"      {_page}: window {win_h}px, {_button} y {before} -> {after}"
              f" (visible: {0 <= before <= win_h} -> {visible})")
        print(f"{'PASS' if moved else 'FAIL'}  {_page}: scrolling moves content up")
        if not moved: failures.append(f"{_page} scroll does not move content")
        print(f"{'PASS' if visible else 'FAIL'}  {_page}: {_button} reachable after scrolling")
        if not visible: failures.append(f"{_page}: {_button} still unreachable")

        canvas.yview_moveto(0.0); app.update_idletasks()
    except Exception as exc:
        failures.append(f"{_page} scroll reveal: {exc}")
        print(f"FAIL  {_page} scroll reveal: {exc}"); traceback.print_exc()

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

# ---- functional: wake word mode --------------------------------------
try:
    for name in ("wake_enabled_var", "wake_phrases_var", "wake_sleep_var",
                 "wake_enter_var", "wake_reply_var"):
        ok = hasattr(app, name)
        print(f"{'PASS' if ok else 'FAIL'}  widget {name}")
        if not ok: failures.append(f"missing widget {name}")

    cfg = app._wake_settings()
    good = ("computer turn voice on" in cfg["phrases"]
            and "computer start listening" in cfg["phrases"])
    print(f"{'PASS' if good else 'FAIL'}  default wake phrases {cfg['phrases']}")
    if not good: failures.append("wake phrase defaults")

    good = "voice off" in cfg["sleep_phrases"]
    print(f"{'PASS' if good else 'FAIL'}  default sleep phrases {cfg['sleep_phrases']}")
    if not good: failures.append("sleep phrase defaults")

    good = cfg["enter_response"] == "Entering wake word mode." and cfg["wake_response"] == "Standing by."
    print(f"{'PASS' if good else 'FAIL'}  default replies "
          f"{cfg['enter_response']!r} / {cfg['wake_response']!r}")
    if not good: failures.append("wake reply defaults")

    # Matching, including the politeness the recogniser adds.
    for heard, phrases, expect in [
            ("voice off", cfg["sleep_phrases"], True),
            ("computer voice off", cfg["sleep_phrases"], True),
            ("shields front", cfg["sleep_phrases"], False),
            ("computer start listening", cfg["phrases"], True),
            ("okay computer turn voice on please", cfg["phrases"], True),
            ("plot a course to lorville", cfg["phrases"], False)]:
        got = app._phrase_in(heard, phrases)
        good = got == expect
        print(f"{'PASS' if good else 'FAIL'}  match {heard!r} -> {got}")
        if not good: failures.append(f"wake match {heard}")

    # The state machine, driven the way the listen loop drives it.
    spoken = []
    app._speak = lambda text="", force=False: spoken.append(text)
    app.running = True

    app.wake_mode = False
    app._enter_wake_mode()
    good = app.wake_mode and spoken[-1] == "Entering wake word mode."
    print(f"{'PASS' if good else 'FAIL'}  sleep -> wake_mode={app.wake_mode}, said {spoken[-1]!r}")
    if not good: failures.append("enter wake mode")

    app._set_status()
    label = app.status_label.cget("text")
    good = label == "WAKE WORD MODE"
    print(f"{'PASS' if good else 'FAIL'}  status reads {label!r} while asleep")
    if not good: failures.append(f"status while asleep: {label}")

    app._leave_wake_mode()
    app._set_status()
    good = (not app.wake_mode) and spoken[-1] == "Standing by." and app.status_label.cget("text") == "LISTENING"
    print(f"{'PASS' if good else 'FAIL'}  wake -> awake, said {spoken[-1]!r}, status {app.status_label.cget('text')!r}")
    if not good: failures.append("leave wake mode")

    # start_listening must never come up asleep.
    app.wake_mode = True
    app.running = False
    app.selected_device = "__default__"
    try:
        app.start_listening()
    except Exception:
        pass
    good = not app.wake_mode
    print(f"{'PASS' if good else 'FAIL'}  start_listening comes up awake")
    if not good: failures.append("start_listening left wake mode on")
    app.running = False

    # Round-trip through settings.json.
    app.wake_sleep_var.set("sleep now, quiet mode")
    app.wake_reply_var.set("Ready when you are.")
    app._save_settings()
    cfg = app._wake_settings()
    good = cfg["sleep_phrases"] == ["sleep now", "quiet mode"] and cfg["wake_response"] == "Ready when you are."
    print(f"{'PASS' if good else 'FAIL'}  edits round-trip: {cfg['sleep_phrases']} / {cfg['wake_response']!r}")
    if not good: failures.append("wake settings round-trip")

    # An empty phrase list would be a mode you cannot wake from.
    app.wake_phrases_var.set("   ")
    app._save_settings()
    cfg = app._wake_settings()
    good = cfg["phrases"] == list(mod.WAKE_PHRASES)
    print(f"{'PASS' if good else 'FAIL'}  blank wake phrases fall back to defaults")
    if not good: failures.append("blank wake phrases not defaulted")
except Exception as exc:
    failures.append(f"wake word: {exc}")
    print(f"FAIL  wake word: {exc}"); traceback.print_exc()

# ---- functional: cloned voices ---------------------------------------
try:
    import voice_clones as _vc, struct as _struct

    ok = hasattr(app, "voice_clone_list") and hasattr(app, "voice_name_var")
    print(f"{'PASS' if ok else 'FAIL'}  VOICE CLONES page built")
    if not ok: failures.append("voice clones page missing")

    # Make a voice on disk the way the sidecar would leave it.
    app_dir = mod.APP_DIR
    ref = app_dir / "t.wav"
    _vc.write_wav(ref, b"".join(_struct.pack("<h", 0) for _ in range(8 * 24000)))
    made = _vc.create_voice(app_dir, "Ship Computer", ref)
    for line in ["Voice calibrated.", "Command confirmed."]:
        _vc.write_wav(made.clips_dir / f"{_vc.line_key(line)}.wav",
                      b"".join(_struct.pack("<h", 0) for _ in range(24000)))

    app._refresh_voice_clones()
    rows = app.voice_clone_list.get(0, "end")
    good = len(rows) == 2 and "Windows voice" in rows[0] and "Ship Computer" in rows[1]
    print(f"{'PASS' if good else 'FAIL'}  list shows the Windows voice and the clone")
    if not good: failures.append(f"voice list: {rows}")

    # The spoken switch. Every phrasing a pilot might actually use.
    spoken = []
    app._speak = lambda text="", force=False: spoken.append(text)

    for heard, expect in [("switch to ship computer voice", "ship-computer"),
                          ("computer ship computer voice", "ship-computer"),
                          ("use the ship computer voice", "ship-computer"),
                          ("change to shipcomputer voice", "ship-computer")]:
        app.active_voice = None
        handled = app._handle_voice_switch(heard)
        got = app.active_voice.slug if app.active_voice else None
        good = handled and got == expect
        print(f"{'PASS' if good else 'FAIL'}  \"{heard}\" -> {got}")
        if not good: failures.append(f"switch {heard}")

    good = spoken and spoken[-1] == "Voice calibrated."
    print(f"{'PASS' if good else 'FAIL'}  switching says {spoken[-1]!r}")
    if not good: failures.append("switch reply")

    app._handle_voice_switch("switch to windows voice")
    # A name is not a dictionary word: the recogniser gave back "captain
    # fascinate" for "Captain FasciN8", which matches nothing exactly.
    _vc.create_voice(app_dir, "Captain FasciN8", ref)
    for heard, expect in [("switch to captain fascinate voice", "captain-fascin8"),
                          ("switch to captain fascin8 voice", "captain-fascin8"),
                          ("switch to captain fassinate voice", "captain-fascin8")]:
        app.active_voice = None
        app._handle_voice_switch(heard)
        got = app.active_voice.slug if app.active_voice else None
        good = got == expect
        print(f"{'PASS' if good else 'FAIL'}  mis-heard name: \"{heard}\" -> {got}")
        if not good: failures.append(f"fuzzy name {heard}")

    # But a genuinely different name must still be refused.
    app.active_voice = None
    app._handle_voice_switch("switch to margaret thatcher voice")
    good = app.active_voice is None
    print(f"{'PASS' if good else 'FAIL'}  an unrelated name is still refused")
    if not good: failures.append("fuzzy matched an unrelated name")

    app._handle_voice_switch("switch to windows voice")
    good = app.active_voice is None
    print(f"{'PASS' if good else 'FAIL'}  \"switch to windows voice\" returns to the Windows voice")
    if not good: failures.append("switch back to windows")

    spoken.clear()
    app._handle_voice_switch("switch to hal nine thousand voice")
    good = spoken and "no voice called" in spoken[-1]
    print(f"{'PASS' if good else 'FAIL'}  an unknown voice says so: {spoken[-1] if spoken else None!r}")
    if not good: failures.append("unknown voice not reported")

    # It must not eat ordinary commands.
    for heard in ["plot a course to lorville", "shields front",
                  "toggle quantum", "voice off"]:
        good = not app._handle_voice_switch(heard)
        print(f"{'PASS' if good else 'FAIL'}  \"{heard}\" is not a voice switch")
        if not good: failures.append(f"switch swallowed {heard}")

    # The active clone must be preferred over the Windows voice, and a
    # line it does not have must be written down rather than lost.
    played = []
    real_play = _vc.play
    _vc.play = lambda path: played.append(str(path)) or True
    try:
        app._speak = mod.VoiceKeybindApp._speak.__get__(app)
        app.active_voice = _vc.find_voice(app_dir, "ship-computer")
        app.active_voice.clear_misses()
        # Speech is sequenced on a worker thread now, so give it a moment.
        app._speak("Voice calibrated.", force=True)
        _t.sleep(0.4)
        good = len(played) == 1
        print(f"{'PASS' if good else 'FAIL'}  a rendered line plays from the clone")
        if not good: failures.append("clone clip not played")

        # A variable part must go to Windows and never be logged, while the
        # sentence beside it still comes from the clone.
        played.clear()
        app._speak("Voice calibrated. 1 minute, 23 seconds.", force=True)
        _t.sleep(0.6)
        good = len(played) == 1
        print(f"{'PASS' if good else 'FAIL'}  mixed line: clone speaks 1 part, Windows the time")
        if not good: failures.append(f"segmented speech played {len(played)}")

        good = not any("minute" in m for m in app.active_voice.logged_misses())
        print(f"{'PASS' if good else 'FAIL'}  a travel time is never logged for rendering")
        if not good: failures.append("variable line logged")

        app._speak("Docking clamps released.", force=True)
        _t.sleep(0.4)
        misses = app.active_voice.logged_misses()
        good = misses == ["Docking clamps released."]
        print(f"{'PASS' if good else 'FAIL'}  an unrendered line is logged: {misses}")
        if not good: failures.append(f"miss not logged: {misses}")
    finally:
        _vc.play = real_play
        app._speak = lambda text="", force=False: None

    # Deleting one bad clip must put exactly that line back on the pending
    # list — the alternative is re-rendering 154 lines to fix one.
    v = app.active_voice
    before = len(v.pending(app._voice_catalog()))
    v.clip_for("Voice calibrated.").unlink()
    after = len(v.pending(app._voice_catalog()))
    good = after == before + 1 and not v.has("Voice calibrated.")
    print(f"{'PASS' if good else 'FAIL'}  removing one clip queues exactly that line ({before} -> {after})")
    if not good: failures.append("re-render queue")

    good = app._pending_line_count() == after
    print(f"{'PASS' if good else 'FAIL'}  the close prompt would offer {after} line(s)")
    if not good: failures.append("pending count")

    app.active_voice = None
    good = app._pending_line_count() == 0
    print(f"{'PASS' if good else 'FAIL'}  no cloned voice means no close prompt")
    if not good: failures.append("pending count with no voice")

    # The catalogue must include the pilot's own replies.
    cat = app._voice_catalog()
    good = "Course set to Grim Hex." in cat and len(cat) > 100
    print(f"{'PASS' if good else 'FAIL'}  catalogue has {len(cat)} lines incl. destinations")
    if not good: failures.append("catalogue wrong")

    good = app._voice_forge_dir().name == "voice_forge"
    print(f"{'PASS' if good else 'FAIL'}  sidecar located at {app._voice_forge_dir().name}/")
    if not good: failures.append("sidecar path")
except Exception as exc:
    failures.append(f"voice clones: {exc}")
    print(f"FAIL  voice clones: {exc}"); traceback.print_exc()

# ---- the listen loop must check things in the right order ------------
try:
    import inspect as _inspect
    src = _inspect.getsource(mod.VoiceKeybindApp._listen_loop)
    markers = [
        ("wake gate",        "if self.wake_mode:"),
        ("sleep phrase",     'self._enter_wake_mode(wake)'),
        ("hard voice-off",   "VOICE_OFF_PHRASES"),
        ("repeat cancel",    "_repeat_cancel_match"),
        ("stop repeating",   "REPEAT_STOP_ALL_PHRASES"),
        ("star map",         "_handle_starmap_speech"),
        ("voice switch",     "_handle_voice_switch"),
        ("keybind matcher",  "_build_phrase_matcher()"),
    ]
    positions = [(name, src.find(needle)) for name, needle in markers]
    missing = [name for name, pos in positions if pos < 0]
    if missing:
        failures.append(f"listen loop missing: {missing}")
        print(f"FAIL  listen loop is missing {missing}")
    else:
        ordered = all(a[1] < b[1] for a, b in zip(positions, positions[1:]))
        print(f"{'PASS' if ordered else 'FAIL'}  listen loop order: "
              + " -> ".join(name for name, _ in positions))
        if not ordered:
            failures.append("listen loop order wrong")
except Exception as exc:
    failures.append(f"listen order: {exc}"); print(f"FAIL  listen order: {exc}")

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
