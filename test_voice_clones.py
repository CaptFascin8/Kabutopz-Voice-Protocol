"""Offline tests for the cloned-voice file system.

No model, no Windows, no audio hardware — every function under test is
either pure or touches a temporary folder:

    python test_voice_clones.py
"""

import shutil
import struct
import sys
import tempfile
import wave
from pathlib import Path

import voice_clones as vc


FAILURES = []


def check(label, got, want):
    ok = got == want
    print(f"   [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"          got  {got!r}")
        print(f"          want {want!r}")
        FAILURES.append(label)
    return ok


def make_wav(path, seconds=8.0, rate=vc.RECORD_SAMPLE_RATE):
    """A silent but structurally valid WAV of a given length."""
    frames = b"".join(
        struct.pack("<h", 0) for _ in range(int(seconds * rate))
    )
    return vc.write_wav(path, frames, sample_rate=rate)


def test_slug_and_key():
    print("\n1. Names and line keys")
    check("'Ship Computer' slug", vc.slugify("Ship Computer"), "ship-computer")
    check("punctuation stripped", vc.slugify("A.T.H.E.N.A!"), "a-t-h-e-n-a")
    check("empty name still usable", vc.slugify("   "), "voice")

    # The key must survive the differences a speech engine introduces.
    same = vc.line_key("Course set to Grim Hex.")
    check("case-insensitive", vc.line_key("COURSE SET TO GRIM HEX."), same)
    check("whitespace-insensitive",
          vc.line_key("Course  set   to Grim Hex."), same)
    check("different text differs",
          vc.line_key("Course set to Daymar.") == same, False)
    check("key is a legal filename",
          all(c in "0123456789abcdef" for c in same), True)


def test_catalog():
    print("\n2. What gets rendered")
    lines = vc.line_catalog(
        destinations=["Grim Hex", "Lorville"],
        systems=["Stanton", "Pyro"],
    )

    check("includes the fixed lines", "Voice calibrated." in lines, True)
    check("includes 'Course set to Grim Hex.'",
          "Course set to Grim Hex." in lines, True)
    check("includes the cross-system warning",
          "Grim Hex is in the Pyro system. Travel to the Pyro Gateway first."
          in lines, True)

    check("no duplicates",
          len({vc.line_key(t) for t in lines}), len(lines))

    # 2 destinations x (4 per-destination lines + 2 systems) = 12, + fixed.
    check("count is destinations x systems, plus fixed",
          len(lines), len(vc.FIXED_LINES) + 12)

    check("extra lines are appended",
          "Shields up." in vc.line_catalog(extra=["Shields up."]), True)
    check("blank extras are ignored",
          vc.line_catalog(extra=["  ", ""]), list(vc.FIXED_LINES))

    empty = vc.line_catalog()
    check("no destinations means fixed lines only",
          empty, list(vc.FIXED_LINES))


def test_create_and_find(app_dir):
    print("\n3. Creating, listing and finding voices")
    reference = make_wav(app_dir / "ref.wav", seconds=8.0)

    voice = vc.create_voice(app_dir, "Ship Computer", reference)
    check("folder is the slug", voice.slug, "ship-computer")
    check("display name is kept", voice.name, "Ship Computer")
    check("reference copied in", voice.reference.is_file(), True)
    check("clips folder made", voice.clips_dir.is_dir(), True)
    check("engine recorded", voice.engine, "chatterbox")
    check("format stamped, so not stale", voice.is_stale, False)

    vc.create_voice(app_dir, "Athena", reference)
    names = sorted(v.name for v in vc.list_voices(app_dir))
    check("both voices listed", names, ["Athena", "Ship Computer"])

    # Spoken lookups: the recogniser will not give us punctuation or case.
    for spoken in ["Ship Computer", "ship computer", "SHIP COMPUTER",
                   "ship-computer", "shipcomputer"]:
        found = vc.find_voice(app_dir, spoken)
        check(f"'{spoken}' finds the voice",
              found.slug if found else None, "ship-computer")

    check("an unknown name finds nothing",
          vc.find_voice(app_dir, "hal nine thousand"), None)
    check("an empty name finds nothing", vc.find_voice(app_dir, "  "), None)


def test_create_rejects_bad_input(app_dir):
    print("\n4. Creation refuses what it cannot use")
    reference = make_wav(app_dir / "ref.wav", seconds=8.0)

    for label, args in [
            ("a blank name", ("   ", reference)),
            ("a duplicate name", ("Ship Computer", reference)),
            ("a missing file", ("Nova", app_dir / "nope.wav")),
    ]:
        try:
            vc.create_voice(app_dir, *args)
            print(f"   [FAIL] {label} was accepted")
            FAILURES.append(f"accepted {label}")
        except ValueError as exc:
            print(f"   [PASS] {label} refused: {exc}")

    # A clip too short to clone from is the interesting one: it fails at
    # render time otherwise, minutes later, with a worse message.
    short = make_wav(app_dir / "short.wav", seconds=1.5)
    try:
        vc.create_voice(app_dir, "Too Short", short)
        print("   [FAIL] a 1.5s reference was accepted")
        FAILURES.append("short reference accepted")
    except ValueError as exc:
        good = "1.5" in str(exc)
        print(f"   [{'PASS' if good else 'FAIL'}] short reference refused: {exc}")
        if not good:
            FAILURES.append("short reference message unhelpful")

    # And a file that is not audio at all.
    junk = app_dir / "notaudio.wav"
    junk.write_text("this is not a wav")
    try:
        vc.create_voice(app_dir, "Junk", junk)
        print("   [FAIL] a text file was accepted as audio")
        FAILURES.append("text file accepted")
    except ValueError as exc:
        print(f"   [PASS] non-audio refused: {exc}")


def test_clips(app_dir):
    print("\n5. Finding rendered clips")
    voice = vc.find_voice(app_dir, "Ship Computer")

    check("nothing rendered yet", voice.has("Voice calibrated."), False)
    check("count is zero", voice.rendered_count(), 0)

    make_wav(voice.clips_dir / f"{vc.line_key('Voice calibrated.')}.wav", 1.0)
    check("finds the clip", voice.has("Voice calibrated."), True)
    check("finds it despite case and spacing",
          voice.has("voice   CALIBRATED."), True)
    check("count is one", voice.rendered_count(), 1)

    lines = ["Voice calibrated.", "Standing by.", "Standing by."]
    check("missing() skips rendered and de-duplicates",
          voice.missing(lines), ["Standing by."])

    # A folder can be copied or edited by hand; an index entry whose file
    # has gone must degrade to the Windows voice, not raise mid-sentence.
    (voice.clips_dir / f"{vc.line_key('Voice calibrated.')}.wav").unlink()
    check("a deleted clip reports as missing",
          voice.has("Voice calibrated."), False)


def test_stale_format(app_dir):
    print("\n6. A voice from an older build is flagged, not trusted")
    voice = vc.find_voice(app_dir, "Athena")
    voice.meta["format"] = 0
    voice.save_meta()
    check("stale voice flagged", vc.Voice(voice.path).is_stale, True)
    check("row says so", "needs re-render" in vc.Voice(voice.path).as_row(), True)


def test_delete(app_dir):
    print("\n7. Deleting")
    check("deletes a real voice", vc.delete_voice(app_dir, "Athena"), True)
    check("gone from the list",
          [v.slug for v in vc.list_voices(app_dir)], ["ship-computer"])
    check("deleting nothing is not an error",
          vc.delete_voice(app_dir, "athena"), False)


def test_audio_helpers(app_dir):
    print("\n8. WAV helpers")
    path = make_wav(app_dir / "len.wav", seconds=3.0)
    duration = vc.wav_duration(path)
    check("duration read back", round(duration, 1), 3.0)
    check("a non-WAV reads as None",
          vc.wav_duration(app_dir / "notaudio.wav"), None)
    check("a missing file reads as None",
          vc.wav_duration(app_dir / "absent.wav"), None)

    # Playback is a no-op off Windows and must never raise either way.
    vc.play(path)
    vc.stop()
    print("   [PASS] play/stop are safe with no audio device")


def test_custom_replies_and_misses(app_dir):
    print("\n9. Custom replies and lines the app actually needed")

    settings = {
        "custom_actions": [
            {"repeat_cancel_response": "Welcome back, pilot.",
             "repeat_start_response": "Going idle."},
            {"repeat_cancel_response": "", "repeat_start_response": None},
            {"repeat_cancel_response": "Welcome back, pilot."},
        ],
        "wake_word": {"enter_response": "Going quiet.",
                      "wake_response": "At your service."},
    }
    replies = vc.custom_replies(settings)
    check("picks up every typed reply, de-duplicated",
          replies,
          ["Welcome back, pilot.", "Going idle.",
           "Going quiet.", "At your service."])
    check("blank and None replies are dropped",
          any(not r for r in replies), False)
    check("junk settings do not raise", vc.custom_replies("nonsense"), [])
    check("missing keys do not raise", vc.custom_replies({}), [])

    # Those replies belong in the catalogue.
    catalog = vc.line_catalog(extra=replies)
    check("custom replies reach the catalogue",
          "Welcome back, pilot." in catalog, True)

    voice = vc.find_voice(app_dir, "Ship Computer")
    voice.clear_misses()

    # The app speaks something nobody anticipated.
    voice.note_miss("Course set to Checkmate.")
    voice.note_miss("Course set to Checkmate.")
    voice.note_miss("  Course  set to   Checkmate.  ")
    check("a miss is logged once, whitespace-insensitive",
          voice.logged_misses(), ["Course set to Checkmate."])

    check("blank misses are ignored",
          (voice.note_miss("   "), voice.logged_misses())[1],
          ["Course set to Checkmate."])

    # Render it, and it stops being outstanding.
    make_wav(voice.clips_dir / f"{vc.line_key('Course set to Checkmate.')}.wav", 1.0)
    check("a rendered miss drops off the list", voice.logged_misses(), [])

    # A line already rendered is never logged in the first place.
    voice.note_miss("Course set to Checkmate.")
    check("rendered lines are not re-logged", voice.logged_misses(), [])

    # pending() is what the render button acts on.
    pending = voice.pending(["Standing by.", "Course set to Checkmate."])
    check("pending is catalogue gaps plus real misses",
          pending, ["Standing by."])

    voice.note_miss("Docking clamps released.")
    check("pending includes logged misses",
          voice.pending(["Standing by."]),
          ["Standing by.", "Docking clamps released."])

    check("misses survive a reload",
          vc.Voice(voice.path).logged_misses(), ["Docking clamps released."])


def main():
    print("Kabutopz Voice Protocol — cloned voice storage tests")
    app_dir = Path(tempfile.mkdtemp(prefix="kvp-voices-"))
    try:
        test_slug_and_key()
        test_catalog()
        test_create_and_find(app_dir)
        test_create_rejects_bad_input(app_dir)
        test_clips(app_dir)
        test_stale_format(app_dir)
        test_delete(app_dir)
        test_audio_helpers(app_dir)
        test_custom_replies_and_misses(app_dir)
    finally:
        shutil.rmtree(app_dir, ignore_errors=True)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed:")
        for label in FAILURES:
            print(f"   - {label}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
