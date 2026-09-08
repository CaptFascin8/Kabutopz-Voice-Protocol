"""Turn a raw recording into a clean reference clip for cloning.

Chatterbox clones from roughly seven to ten seconds, and a tight clean clip
beats a long loose one: background noise, room echo, long silences and a
second voice all get encoded into the speaker embedding alongside the voice
you actually wanted. Handing it a raw 32-second take is how you get a clone
that sounds vaguely like you and also vaguely like your room.

So this picks the best window automatically rather than making anyone open
an audio editor:

  1. measure loudness across the recording in short frames
  2. work out where speech is, from the recording's own noise floor
  3. slide a window and score it on how much speech it contains, keeping
     the window that starts on a real word rather than mid-syllable
  4. convert to mono at the model's rate and normalise the level

Standard library only — ``wave`` and ``audioop`` — so it runs in the app's
own Python with nothing installed. ``audioop`` is deprecated in 3.13, so
the few operations used here have small local fallbacks.
"""

import argparse
import math
import struct
import sys
import wave
from pathlib import Path

try:
    import audioop
except ImportError:  # pragma: no cover - Python 3.13+
    audioop = None


TARGET_RATE = 24000
FRAME_MS = 20
DEFAULT_SECONDS = 11.0
# Speech is taken to be anything meaningfully above the recording's own
# quiet floor. Measured relative to the clip rather than fixed, because one
# person's quiet room is another's noisy one.
SPEECH_MARGIN = 3.5


def _rms(fragment, width):
    if audioop is not None:
        return audioop.rms(fragment, width)
    count = len(fragment) // width
    if not count:
        return 0
    values = struct.unpack(f"<{count}h", fragment[: count * width])
    return int(math.sqrt(sum(v * v for v in values) / count))


def _to_mono(fragment, width, channels):
    if channels == 1:
        return fragment
    if audioop is not None:
        return audioop.tomono(fragment, width, 0.5, 0.5)
    count = len(fragment) // (width * channels)
    values = struct.unpack(f"<{count * channels}h", fragment)
    mixed = [
        sum(values[i * channels:(i + 1) * channels]) // channels
        for i in range(count)
    ]
    return struct.pack(f"<{count}h", *mixed)


def _resample(fragment, width, rate, target):
    if rate == target:
        return fragment
    if audioop is not None:
        converted, _ = audioop.ratecv(fragment, width, 1, rate, target, None)
        return converted
    # Nearest-neighbour fallback. Only reached on Python 3.13+ without
    # audioop; adequate for a speech reference clip.
    count = len(fragment) // width
    values = struct.unpack(f"<{count}h", fragment)
    step = rate / float(target)
    out = [values[min(count - 1, int(i * step))]
           for i in range(int(count / step))]
    return struct.pack(f"<{len(out)}h", *out)


def _normalise(fragment, width, peak_target=0.89):
    """Bring the peak up without clipping. Quiet references clone poorly."""
    if audioop is not None:
        peak = audioop.max(fragment, width)
    else:
        count = len(fragment) // width
        peak = max(abs(v) for v in struct.unpack(f"<{count}h", fragment)) or 0

    ceiling = 2 ** (width * 8 - 1) - 1
    if peak <= 0:
        return fragment
    factor = (peak_target * ceiling) / peak
    # Only ever quieten a hot clip a little; mostly this lifts a quiet one.
    factor = max(0.5, min(factor, 8.0))
    if audioop is not None:
        return audioop.mul(fragment, width, factor)

    count = len(fragment) // width
    values = struct.unpack(f"<{count}h", fragment)
    scaled = [max(-ceiling, min(ceiling, int(v * factor))) for v in values]
    return struct.pack(f"<{count}h", *scaled)


def analyse(path):
    """Read a WAV and return (mono frames, rate, per-frame loudness)."""
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())

    if width != 2:
        raise ValueError(
            f"Expected 16-bit audio, found {width * 8}-bit. "
            "Export as 16-bit PCM WAV."
        )

    mono = _to_mono(raw, width, channels)
    frame_bytes = int(rate * FRAME_MS / 1000) * width
    levels = [
        _rms(mono[i:i + frame_bytes], width)
        for i in range(0, len(mono) - frame_bytes, frame_bytes)
    ]
    return mono, rate, levels, width


def speech_mask(levels):
    """Which frames are speech, judged against this clip's own quiet floor."""
    if not levels:
        return []
    quiet = sorted(levels)
    floor = quiet[len(quiet) // 5] or 1        # 20th percentile
    threshold = max(floor * SPEECH_MARGIN, 40)
    return [level >= threshold for level in levels]


def best_window(mask, frames_needed):
    """Start frame of the speech-densest window that begins on a word.

    Starting mid-syllable gives the model a clipped consonant to learn
    from, so among near-equal windows the one starting at a speech onset
    wins.
    """
    if frames_needed >= len(mask):
        return 0

    best_start, best_score = 0, -1.0
    running = sum(mask[:frames_needed])

    for start in range(len(mask) - frames_needed + 1):
        if start:
            running += mask[start + frames_needed - 1] - mask[start - 1]
        score = float(running)
        # Prefer a window whose first frame is speech and whose previous
        # frame is not — that is the start of a word.
        if mask[start] and (start == 0 or not mask[start - 1]):
            score += frames_needed * 0.05
        if score > best_score:
            best_start, best_score = start, score

    return best_start


def prepare(source, destination, seconds=DEFAULT_SECONDS,
            target_rate=TARGET_RATE):
    mono, rate, levels, width = analyse(source)
    mask = speech_mask(levels)

    speech_frames = sum(mask)
    total_seconds = len(levels) * FRAME_MS / 1000.0
    speech_seconds = speech_frames * FRAME_MS / 1000.0

    frames_needed = int(seconds * 1000 / FRAME_MS)
    start_frame = best_window(mask, frames_needed)

    frame_bytes = int(rate * FRAME_MS / 1000) * width
    begin = start_frame * frame_bytes
    end = min(len(mono), begin + frames_needed * frame_bytes)
    clip = mono[begin:end]

    kept = mask[start_frame:start_frame + frames_needed]
    kept_speech = sum(kept) * FRAME_MS / 1000.0

    clip = _resample(clip, width, rate, target_rate)
    clip = _normalise(clip, width)

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(width)
        handle.setframerate(target_rate)
        handle.writeframes(clip)

    return {
        "source_seconds": round(total_seconds, 1),
        "source_speech_seconds": round(speech_seconds, 1),
        "start_seconds": round(start_frame * FRAME_MS / 1000.0, 1),
        "clip_seconds": round(len(kept) * FRAME_MS / 1000.0, 1),
        "clip_speech_seconds": round(kept_speech, 1),
        "speech_ratio": round(kept_speech / max(0.1, seconds), 2),
        "rate": target_rate,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument("--seconds", type=float, default=DEFAULT_SECONDS)
    args = parser.parse_args()

    try:
        report = prepare(args.source, args.destination, args.seconds)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"source            {report['source_seconds']}s "
          f"({report['source_speech_seconds']}s of speech)")
    print(f"picked            {report['start_seconds']}s "
          f"-> +{report['clip_seconds']}s")
    print(f"speech in clip    {report['clip_speech_seconds']}s "
          f"({report['speech_ratio'] * 100:.0f}% of the window)")
    print(f"written           {args.destination} at {report['rate']}Hz mono")

    if report["speech_ratio"] < 0.6:
        print()
        print("NOTE: that window is more than a third silence. A denser "
              "read will clone better.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
