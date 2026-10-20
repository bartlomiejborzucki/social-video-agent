"""Where a recording has voice, measured from its sound rather than its words.

An RMS envelope on a 10 ms grid against the local noise floor. Used to put
cut edges where speech is heard and to catch words a transcript stretched
over a pause.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from social_video.ffmpeg.run import find_binary

RATE = 16000
FRAME = 0.01
#: Frames in a row that count as speech, so a click is not a syllable.
MIN_RUN = 3


def decode_mono(path: Path, *, track: int = 0, start: float = 0.0, end: float | None = None):
    """Mono float samples at ``RATE`` of one audio track, optionally a span of it."""
    argv = [find_binary("ffmpeg"), "-v", "error", "-nostdin"]
    if start > 0:
        argv += ["-ss", f"{start:.3f}"]
    if end is not None:
        argv += ["-t", f"{max(FRAME, end - start):.3f}"]
    argv += ["-i", str(path), "-map", f"0:a:{track}", "-ac", "1", "-ar", str(RATE)]
    argv += ["-f", "f32le", "-"]
    proc = subprocess.run(argv, capture_output=True, check=True)
    return np.frombuffer(proc.stdout, dtype=np.float32)


def envelope_db(signal: np.ndarray, rate: int = RATE) -> np.ndarray:
    """RMS level in dBFS on a 10 ms grid."""
    hop = int(rate * FRAME)
    frames = len(signal) // hop
    if frames == 0:
        return np.zeros(0)
    blocks = signal[: frames * hop].reshape(frames, hop).astype(np.float64)
    rms = np.sqrt(np.mean(np.square(blocks), axis=1))
    return 20.0 * np.log10(rms + 1e-9)


def speech_mask(db: np.ndarray) -> np.ndarray:
    """Frames loud enough above the floor to be voice, in runs of MIN_RUN or more.

    The threshold sits a fifth of the way from the noise floor to the speech
    peaks, and at least 8 dB above the floor: low enough to keep a decaying
    final syllable, high enough to ignore room tone.
    """
    if db.size == 0:
        return np.zeros(0, dtype=bool)
    floor = float(np.percentile(db, 10))
    peak = float(np.percentile(db, 95))
    loud = db > floor + max(8.0, 0.2 * (peak - floor))
    if peak - floor < 10.0:
        # Nothing stands out from the floor: no speech can be located here.
        return np.zeros_like(loud)
    mask = np.zeros_like(loud)
    run_start = None
    for index, value in enumerate([*loud.tolist(), False]):
        if value and run_start is None:
            run_start = index
        elif not value and run_start is not None:
            if index - run_start >= MIN_RUN:
                mask[run_start:index] = True
            run_start = None
    return mask


def quiet_spans(signal: np.ndarray, *, minimum: float = 0.3) -> list[tuple[float, float]]:
    """Stretches without voice at least ``minimum`` long, in seconds.

    A recording with no dynamics -- a steady tone, constant noise -- has no
    measurable voice at all, so nothing in it is reported as quiet.
    """
    db = envelope_db(signal)
    if db.size == 0 or np.percentile(db, 95) - np.percentile(db, 10) < 10.0:
        return []
    mask = speech_mask(db)
    spans: list[tuple[float, float]] = []
    start = None
    for index, voiced in enumerate([*mask.tolist(), True]):
        if not voiced and start is None:
            start = index
        elif voiced and start is not None:
            if (index - start) * FRAME >= minimum:
                spans.append((round(start * FRAME, 3), round(index * FRAME, 3)))
            start = None
    return spans


def recording_quiet_spans(path: Path, *, track: int = 0) -> list[tuple[float, float]] | None:
    """Quiet stretches of a whole recording, or None when it cannot be decoded."""
    try:
        return quiet_spans(decode_mono(path, track=track))
    except (subprocess.CalledProcessError, OSError):
        return None
