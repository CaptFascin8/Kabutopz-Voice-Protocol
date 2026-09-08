"""Create a cloned voice from a raw recording, end to end.

Prepares the reference clip, registers the voice, and optionally renders
lines — the same three steps the VOICE CLONES page performs, available
from the command line so a voice can be made, tested and re-made without
the UI.

    python make_voice.py --name "Ship Computer" --source take.wav
    python make_voice.py --name "Ship Computer" --source take.wav --proof
    python make_voice.py --name "Ship Computer" --source take.wav --full

``--proof`` renders a handful of lines so you can hear whether the clone
is any good before committing to the whole catalogue. That ordering
matters: the full render is minutes of work, and there is no sense
spending them on a reference clip that turned out to be too echoey.
"""

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))          # voice_clones lives beside us

import voice_clones as vc                      # noqa: E402
import prepare_reference                       # noqa: E402


# Enough to judge a clone by: a greeting, the line said most often, a long
# sentence to expose wobble, and one with a proper noun in it.
PROOF_LINES = (
    "Voice calibrated.",
    "Command confirmed.",
    "Standing by.",
    "Course set to Grim Hex.",
    "Grim Hex is in the Pyro system. Travel to the Pyro Gateway first.",
)


def default_app_dir():
    return Path.home() / ".star_citizen_voice_keybinds"


def known_destinations():
    """Every place the star map knows how to route to.

    Read from the alias table rather than duplicated here, so a
    destination added for the star map is automatically a destination the
    cloned voice can pronounce.
    """
    try:
        import starmap
    except ImportError:
        return []
    return sorted(set(starmap.DESTINATION_ALIASES.values()))


def render(voice, lines, python=None, dry_run=False, device="auto"):
    """Run the renderer as a subprocess, echoing its progress."""
    # A temporary *directory*, not mkstemp: mkstemp hands back an open file
    # descriptor, and Windows refuses to delete a file that is still open.
    # On Linux the same code cleans up silently, which is exactly how this
    # got written in the first place.
    scratch = tempfile.TemporaryDirectory(prefix="kvp-render-")
    lines_file = Path(scratch.name) / "lines.json"
    lines_file.write_text(json.dumps(lines), encoding="utf-8")

    command = [
        python or sys.executable,
        str(HERE / "render_voice.py"),
        "--voice", str(voice.path),
        "--lines", str(lines_file),
        "--device", device,
    ]
    if dry_run:
        command.append("--dry-run")

    started = time.time()
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )

    failures = []
    for raw in process.stdout:
        raw = raw.strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except ValueError:
            print(f"   {raw}")
            continue

        kind = event.get("event")
        if kind == "loading":
            print(f"   loading the model on {event['device']}...")
        elif kind == "start":
            print(f"   rendering {event['total']} lines on {event['device']}")
        elif kind == "line":
            print(f"   [{event['index']}/{event['total']}] {event['text']}")
        elif kind == "line_failed":
            failures.append(event["text"])
            print(f"   FAILED: {event['text']} — {event.get('message')}")
        elif kind == "error":
            print(f"   ERROR: {event.get('message')}")
        elif kind == "done":
            print(f"   done: {event['rendered']} rendered, "
                  f"{event['failed']} failed, {event['seconds']}s")

    process.wait()
    scratch.cleanup()
    print(f"   elapsed {time.time() - started:.1f}s")
    return process.returncode, failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--source", required=True,
                        help="the raw recording to clone from")
    parser.add_argument("--app-dir", default=None)
    parser.add_argument("--seconds", type=float,
                        default=prepare_reference.DEFAULT_SECONDS)
    parser.add_argument("--replace", action="store_true",
                        help="replace a voice of the same name")
    parser.add_argument("--proof", action="store_true",
                        help="render a few lines so you can judge the clone")
    parser.add_argument("--full", action="store_true",
                        help="render the whole catalogue")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--device", default="auto",
                        choices=["auto", "cuda", "cpu"])
    parser.add_argument("--python", default=None,
                        help="interpreter with chatterbox installed "
                             "(defaults to .venv in this folder)")
    args = parser.parse_args()

    app_dir = Path(args.app_dir) if args.app_dir else default_app_dir()

    python = args.python
    if python is None:
        candidate = HERE / ".venv" / "Scripts" / "python.exe"
        python = str(candidate) if candidate.is_file() else sys.executable

    if args.replace:
        vc.delete_voice(app_dir, vc.slugify(args.name))

    # 1. Trim and clean the reference. Same reason as above: a directory,
    # so nothing is left holding an open handle when it is removed.
    scratch = tempfile.TemporaryDirectory(prefix="kvp-reference-")
    prepared = Path(scratch.name) / "reference.wav"
    try:
        report = prepare_reference.prepare(args.source, prepared, args.seconds)
    except Exception as exc:
        scratch.cleanup()
        print(f"Could not prepare the reference: {exc}")
        return 1

    print(f"reference   {report['clip_seconds']}s from {report['start_seconds']}s "
          f"in, {report['speech_ratio'] * 100:.0f}% speech, "
          f"{report['rate']}Hz mono")
    if report["speech_ratio"] < 0.6:
        print("            NOTE: more than a third silence — a denser read "
              "would clone better")

    # 2. Register it.
    try:
        voice = vc.create_voice(app_dir, args.name, prepared)
    except ValueError as exc:
        print(f"Could not create the voice: {exc}")
        return 1
    finally:
        scratch.cleanup()

    print(f"created     {voice.name}  ->  {voice.path}")

    # 3. Render, if asked.
    lines = []
    if args.full:
        lines = vc.line_catalog(
            destinations=known_destinations(),
            systems=("Stanton", "Pyro", "Nyx", "Terra"),
        )
    elif args.proof:
        lines = list(PROOF_LINES)

    if not lines:
        print("\nNo lines rendered. Pass --proof or --full to render some.")
        return 0

    print()
    code, failures = render(voice, lines, python, args.dry_run, args.device)
    if failures:
        print(f"\n{len(failures)} line(s) failed.")
    print(f"\nclips in    {voice.clips_dir}")
    return code


if __name__ == "__main__":
    sys.exit(main())
