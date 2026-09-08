"""Cloned voice storage and playback.

This module deliberately has **no heavy dependencies**. The model that
creates a voice lives in a separate sidecar (see ``voice_forge/``); nothing
here ever imports torch, and nothing here ever runs a model. All this side
does is read what the sidecar produced and play it.

That split is the whole design. Voice cloning needs PyTorch — a couple of
gigabytes — and bundling it would turn a 40 MB app into a 2 GB one and make
the feature unmergeable upstream. So the sidecar is an optional folder with
its own environment, and the app degrades to the Windows voice without it.

The second half of the design is that **nothing is generated while you
fly**. Every line the ship computer can say is rendered to a WAV once, when
the voice is created. Speaking is then a file read, which costs nothing,
takes no VRAM away from the game, and cannot stutter.

Layout on disk::

    ~/.star_citizen_voice_keybinds/voices/
        athena/
            voice.json          name, engine, settings, line index
            reference.wav       the audio the voice was cloned from
            clips/
                3f2a....wav     one rendered line
        ship-computer/
            ...

Plain folders and plain JSON, so a voice can be backed up, copied to
another machine, or deleted in Explorer without the app's help.
"""

import hashlib
import json
import re
import shutil
import time
import wave
from pathlib import Path

# Windows-only, and part of the standard library — which is exactly why it
# is used here rather than a playback package. Imported defensively so the
# module can still be tested off Windows.
try:
    import winsound
except ImportError:  # pragma: no cover - non-Windows test environments
    winsound = None


VOICE_DIR_NAME = "voices"
META_NAME = "voice.json"
CLIPS_DIR_NAME = "clips"
REFERENCE_NAME = "reference.wav"

# What the sidecar records about itself, so a voice made by an older build
# can be recognised and re-rendered rather than silently misbehaving.
CURRENT_FORMAT = 1
DEFAULT_ENGINE = "chatterbox"

# Recording defaults. 24 kHz mono matches what the model wants and keeps the
# reference clip small; the app records through sounddevice, which is
# already a dependency.
RECORD_SAMPLE_RATE = 24000
RECORD_CHANNELS = 1
RECORD_SECONDS = 12.0
MIN_REFERENCE_SECONDS = 4.0

# Chatterbox clones from roughly seven seconds. The script exists because a
# clean, varied ten seconds beats a noisy thirty: background music, room
# echo or a second voice all get encoded into the embedding alongside the
# voice you actually wanted.
RECORDING_SCRIPT = (
    "Navigation systems online. Plotting a course to the Stanton system.\n"
    "Quantum drive spooling. Estimated travel time, two minutes.\n"
    "Warning: hull integrity at sixty percent. Shields holding."
)


def slugify(name):
    """Folder-safe name. Two voices cannot collide by accident."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).strip().lower()).strip("-")
    return slug or "voice"


def line_key(text):
    """Stable filename for a line of speech.

    Hashed rather than derived from the words so that punctuation, length
    and non-ASCII characters cannot produce an illegal filename, and so the
    same sentence always lands on the same file.
    """
    normalized = " ".join(str(text).split()).lower()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


class Voice:
    """One cloned voice on disk."""

    def __init__(self, path):
        self.path = Path(path)
        self.meta = self._read_meta()

    # ---- metadata -------------------------------------------------------
    def _read_meta(self):
        try:
            return json.loads((self.path / META_NAME).read_text("utf-8"))
        except Exception:
            return {}

    def save_meta(self):
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / META_NAME).write_text(
            json.dumps(self.meta, indent=2), encoding="utf-8"
        )

    @property
    def slug(self):
        return self.path.name

    @property
    def name(self):
        return self.meta.get("name") or self.slug

    @property
    def engine(self):
        return self.meta.get("engine", DEFAULT_ENGINE)

    @property
    def reference(self):
        return self.path / self.meta.get("reference", REFERENCE_NAME)

    @property
    def clips_dir(self):
        return self.path / CLIPS_DIR_NAME

    @property
    def is_stale(self):
        """True when this voice predates the current on-disk format."""
        return int(self.meta.get("format", 0)) != CURRENT_FORMAT

    # ---- rendered lines -------------------------------------------------
    def clip_for(self, text):
        """Path to the rendered clip for ``text``, or None if not rendered.

        Checks the file actually exists rather than trusting the index — a
        voice folder can be edited or partly copied, and a missing file
        should degrade to the Windows voice, not raise mid-sentence.
        """
        path = self.clips_dir / f"{line_key(text)}.wav"
        return path if path.is_file() else None

    def has(self, text):
        return self.clip_for(text) is not None

    def rendered_count(self):
        try:
            return len(list(self.clips_dir.glob("*.wav")))
        except Exception:
            return 0

    def missing(self, lines):
        """Which of ``lines`` have no clip yet, in order, without repeats."""
        seen = set()
        out = []
        for text in lines:
            key = line_key(text)
            if key in seen or self.has(text):
                continue
            seen.add(key)
            out.append(text)
        return out

    def as_row(self):
        """One line for the voices list in the UI."""
        return (
            f"{self.name}  —  {self.rendered_count()} lines"
            + ("  (needs re-render)" if self.is_stale else "")
        )


# ---- the library ------------------------------------------------------
def voices_root(app_dir):
    return Path(app_dir) / VOICE_DIR_NAME


def list_voices(app_dir):
    """Every voice on disk, newest first."""
    root = voices_root(app_dir)
    if not root.is_dir():
        return []

    found = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and (entry / META_NAME).is_file():
            found.append(Voice(entry))

    found.sort(key=lambda v: v.meta.get("created", ""), reverse=True)
    return found


def find_voice(app_dir, name_or_slug):
    """Look a voice up the way a person would say it.

    Matches the slug, then the name, then a forgiving comparison — the
    speech recogniser will not reliably reproduce capitalisation or
    punctuation in "switch to ship computer voice".
    """
    target = slugify(name_or_slug)
    if not target:
        return None

    voices = list_voices(app_dir)
    for voice in voices:
        if voice.slug == target:
            return voice
    for voice in voices:
        if slugify(voice.name) == target:
            return voice
    # Last resort: ignore separators entirely, so "shipcomputer" finds
    # "Ship Computer".
    flat = target.replace("-", "")
    for voice in voices:
        if slugify(voice.name).replace("-", "") == flat:
            return voice
    return None


def create_voice(app_dir, name, reference_wav, engine=DEFAULT_ENGINE,
                 settings=None):
    """Create a voice folder from a reference recording.

    Returns the new :class:`Voice`. Raises ValueError with a sentence fit
    to show the user if the name collides or the reference is unusable.
    """
    label = str(name).strip()
    if not label:
        raise ValueError("Give the voice a name first.")

    slug = slugify(label)
    root = voices_root(app_dir)
    path = root / slug
    if path.exists():
        raise ValueError(f"A voice called {label} already exists.")

    source = Path(reference_wav)
    if not source.is_file():
        raise ValueError("That reference recording could not be found.")

    seconds = wav_duration(source)
    if seconds is None:
        raise ValueError(
            "That file is not a readable WAV. Export it as WAV and try again."
        )
    if seconds < MIN_REFERENCE_SECONDS:
        raise ValueError(
            f"The reference is only {seconds:.1f}s. "
            f"Use at least {MIN_REFERENCE_SECONDS:.0f}s of clean speech."
        )

    (path / CLIPS_DIR_NAME).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, path / REFERENCE_NAME)

    voice = Voice(path)
    voice.meta = {
        "format": CURRENT_FORMAT,
        "name": label,
        "engine": engine,
        "reference": REFERENCE_NAME,
        "reference_seconds": round(seconds, 2),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "settings": dict(settings or {}),
    }
    voice.save_meta()
    return voice


def delete_voice(app_dir, slug):
    """Remove a voice folder. Returns True when something was removed."""
    path = voices_root(app_dir) / slugify(slug)
    if not path.is_dir():
        return False
    shutil.rmtree(path, ignore_errors=True)
    return not path.exists()


# ---- what needs rendering ---------------------------------------------
#
# Every fixed thing the ship computer says. Kept here rather than scraped
# out of the app so that adding a line is a deliberate act with a visible
# diff, and so this list can be tested.
FIXED_LINES = (
    "Command confirmed.",
    "Voice calibrated.",
    "Standing by.",
    "Entering wake word mode.",
    "Welcome back.",
    "Ready to plot course.",
    "Course set.",
    "Thank you for flying with me.",
    "You're welcome.",
    "You're welcome, pilot.",
    "Any time. Happy to help.",
    "My pleasure. Safe flying.",
    "Always happy to fly with you.",
    "Of course. I'm here when you need me.",
    "I could not open the star map.",
    "I could not reach the search bar.",
    "The star map is already busy.",
    "I could not confirm the route.",
)


def line_catalog(destinations=(), systems=(), extra=()):
    """Every line to render for a new voice.

    Destination-shaped lines are expanded here rather than left to fall
    back at runtime: "Course set to Grim Hex" is the sentence this app
    exists to say, and hearing it in the Windows voice would undo the
    whole feature.

    The cross-system warning is expanded over destination and system
    together, which is the one combinatorial set worth paying for — it is
    the reply that saves a wasted quantum jump.
    """
    lines = list(FIXED_LINES)

    for destination in destinations:
        lines.append(f"Course set to {destination}.")
        lines.append(f"Course plotted to {destination}.")
        lines.append(f"No results for {destination}.")
        lines.append(f"I could not find {destination} in the results.")
        for system in systems:
            lines.append(
                f"{destination} is in the {system} system. "
                f"Travel to the {system} Gateway first."
            )

    lines.extend(str(item) for item in extra if str(item).strip())

    # Preserve order, drop duplicates — the same sentence can arrive from
    # two places and rendering it twice is wasted minutes.
    seen = set()
    unique = []
    for text in lines:
        key = line_key(text)
        if key in seen:
            continue
        seen.add(key)
        unique.append(text)
    return unique


# ---- audio ------------------------------------------------------------
def wav_duration(path):
    """Length of a WAV in seconds, or None if it is not a readable WAV."""
    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
            return frames / float(rate) if rate else None
    except Exception:
        return None


def write_wav(path, frames, sample_rate=RECORD_SAMPLE_RATE,
              channels=RECORD_CHANNELS, sample_width=2):
    """Write 16-bit PCM frames to a WAV file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(sample_width)
        handle.setframerate(sample_rate)
        handle.writeframes(frames)
    return path


def play(path):
    """Play a WAV without blocking. Returns False if it could not start.

    Never raises: a voice line failing to play must not take down the
    listen loop, and the caller falls back to the Windows voice.
    """
    if winsound is None:
        return False
    try:
        winsound.PlaySound(
            str(path), winsound.SND_FILENAME | winsound.SND_ASYNC
        )
        return True
    except Exception:
        return False


def stop():
    """Stop whatever is playing. Safe to call when nothing is."""
    if winsound is None:
        return
    try:
        winsound.PlaySound(None, winsound.SND_PURGE)
    except Exception:
        pass
