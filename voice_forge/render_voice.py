"""Render every line of a cloned voice to WAV. Runs in the sidecar.

This is the ONLY file in the project that touches a model, and it never
runs inside the app. The app spawns it as a subprocess when you create a
voice, reads its progress, and it exits when the last line is written.
After that the model is not running at all — which is the point. Star
Citizen at 4K wants every megabyte of VRAM, and a ship computer that
stutters because a neural net is warming up is worse than one with a
plain Windows voice.

Usage (the app does this for you)::

    python render_voice.py --voice <voice folder> --lines lines.json
    python render_voice.py --voice <voice folder> --lines lines.json --dry-run

Progress is written to stdout as one JSON object per line, so the caller
can drive a progress bar without parsing prose::

    {"event": "start", "total": 214, "device": "cuda"}
    {"event": "line", "index": 1, "total": 214, "text": "Command confirmed."}
    {"event": "done", "rendered": 214, "failed": 0, "seconds": 186.4}

``--dry-run`` writes correctly-formatted silence instead of loading the
model, so the whole app flow — create, render, switch, speak — can be
tested end to end before anyone installs two gigabytes of PyTorch.
"""

import argparse
import json
import os
import struct
import sys
import time
import wave
from pathlib import Path

# Chatterbox draws a tqdm bar per sampling step — a thousand lines of
# "Sampling: 3%|..." per rendered clip, which drowns our own JSON progress
# and makes a log file useless. Set before torch or chatterbox is imported.
os.environ.setdefault("TQDM_DISABLE", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


# 16-bit PCM, always. Chatterbox hands back float32 audio, and a float WAV
# is legal but winsound will not play it — the clip would land on disk
# looking perfect and be silent in the app. Converting here, once, is the
# difference between a feature that works and one that fails silently.
SAMPLE_WIDTH = 2
FALLBACK_RATE = 24000


def emit(**payload):
    """One JSON object per line, flushed, so the caller sees it live."""
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def line_key(text):
    """Must match voice_clones.line_key exactly — same file, both sides."""
    import hashlib
    normalized = " ".join(str(text).split()).lower()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def write_pcm16(path, samples, sample_rate):
    """Write float samples in -1..1 as a 16-bit PCM WAV."""
    frames = bytearray()
    for value in samples:
        clipped = max(-1.0, min(1.0, float(value)))
        frames += struct.pack("<h", int(clipped * 32767))

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(SAMPLE_WIDTH)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(frames))


def silent_clip(path, text, sample_rate=FALLBACK_RATE):
    """A dry-run stand-in: silence roughly as long as the line would be.

    Length is proportional to the text so a progress bar and a playback
    path can both be exercised realistically without a model.
    """
    seconds = max(0.4, min(6.0, len(text) / 14.0))
    write_pcm16(path, [0.0] * int(seconds * sample_rate), sample_rate)


class Renderer:
    """Loads Chatterbox once and renders lines against a reference clip."""

    def __init__(self, reference, device="auto", settings=None):
        self.reference = str(reference)
        self.settings = dict(settings or {})
        self.device = self._pick_device(device)
        self.model = None
        self.sample_rate = FALLBACK_RATE

    @staticmethod
    def _pick_device(requested):
        """CUDA when it is really usable, CPU otherwise.

        ``torch.cuda.is_available()`` can be True on a machine whose driver
        and wheel disagree, and the failure then arrives deep inside the
        first generate() call. Asking for the device name up front turns
        that into a clean fall back to CPU.
        """
        if requested and requested != "auto":
            return requested
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.get_device_name(0)
                return "cuda"
        except Exception:
            pass
        return "cpu"

    def gpu_pressure(self):
        """Free VRAM in GB, or None when not on a GPU.

        Rendering while a game has the card is dramatically slower — a
        measured 254s versus 102s for the same five lines, with Star
        Citizen holding 8.5 of 12 GB. Without this the pilot just sees a
        mysteriously slow render and reasonably blames the tool.
        """
        if self.device != "cuda":
            return None
        try:
            import torch
            free, total = torch.cuda.mem_get_info()
            return free / 1024 ** 3, total / 1024 ** 3
        except Exception:
            return None

    def load(self):
        from chatterbox.tts import ChatterboxTTS
        self.model = ChatterboxTTS.from_pretrained(device=self.device)
        self.sample_rate = int(getattr(self.model, "sr", FALLBACK_RATE))

    def render(self, text, path):
        kwargs = {"audio_prompt_path": self.reference}
        for name in ("exaggeration", "cfg_weight", "temperature"):
            if name in self.settings:
                kwargs[name] = self.settings[name]

        wav = self.model.generate(text, **kwargs)

        # Flatten whatever shape the model returned into a list of floats,
        # then write PCM16 ourselves rather than trusting torchaudio's
        # default encoding.
        try:
            samples = wav.detach().cpu().flatten().tolist()
        except AttributeError:
            samples = list(wav)

        write_pcm16(path, samples, self.sample_rate)


def load_lines(source):
    """Lines to render: a JSON list from a file, or from stdin with '-'."""
    raw = sys.stdin.read() if source == "-" else Path(source).read_text("utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("The lines file must contain a JSON list of strings.")
    return [str(item) for item in data if str(item).strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice", required=True,
                        help="the voice folder, containing reference.wav")
    parser.add_argument("--lines", required=True,
                        help="JSON list of lines to render, or - for stdin")
    parser.add_argument("--device", default="auto",
                        choices=["auto", "cuda", "cpu"])
    parser.add_argument("--dry-run", action="store_true",
                        help="write silence instead of loading the model")
    parser.add_argument("--overwrite", action="store_true",
                        help="re-render lines that already have a clip")
    args = parser.parse_args()

    voice_dir = Path(args.voice)
    clips_dir = voice_dir / "clips"
    reference = voice_dir / "reference.wav"

    if not args.dry_run and not reference.is_file():
        emit(event="error",
             message=f"No reference recording at {reference}.")
        return 2

    try:
        lines = load_lines(args.lines)
    except Exception as exc:
        emit(event="error", message=f"Could not read the lines list: {exc}")
        return 2

    settings = {}
    meta_path = voice_dir / "voice.json"
    if meta_path.is_file():
        try:
            settings = json.loads(meta_path.read_text("utf-8")).get(
                "settings", {}
            ) or {}
        except Exception:
            settings = {}

    pending = []
    for text in lines:
        path = clips_dir / f"{line_key(text)}.wav"
        if path.is_file() and not args.overwrite:
            continue
        pending.append((text, path))

    if not pending:
        emit(event="done", rendered=0, failed=0, seconds=0.0,
             message="Every line was already rendered.")
        return 0

    renderer = None
    if not args.dry_run:
        renderer = Renderer(reference, args.device, settings)
        try:
            emit(event="loading", device=renderer.device)
            renderer.load()
        except ImportError:
            emit(event="error",
                 message="Chatterbox is not installed in this environment. "
                         "Run setup_voice_forge.bat first.")
            return 3
        except Exception as exc:
            emit(event="error", message=f"Could not load the model: {exc}")
            return 3

    device = renderer.device if renderer else "dry-run"

    # Say it before the long part starts, not after.
    if renderer is not None:
        pressure = renderer.gpu_pressure()
        if pressure and pressure[0] < 3.0:
            emit(event="warning",
                 message=f"Only {pressure[0]:.1f} GB of {pressure[1]:.0f} GB "
                         f"of video memory is free — something else is using "
                         f"the GPU. Close it and rendering will be several "
                         f"times faster, or re-run with --device cpu.")

    emit(event="start", total=len(pending), device=device)

    started = time.time()
    rendered = 0
    failed = 0

    for index, (text, path) in enumerate(pending, start=1):
        emit(event="line", index=index, total=len(pending), text=text)
        try:
            if renderer is None:
                silent_clip(path, text)
            else:
                renderer.render(text, path)
            rendered += 1
        except Exception as exc:
            failed += 1
            # One bad line must not lose the other two hundred.
            emit(event="line_failed", text=text, message=str(exc))

    emit(event="done", rendered=rendered, failed=failed,
         seconds=round(time.time() - started, 1))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
