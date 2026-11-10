"""Where the beats of a music bed fall, so accents can land on them.

A spectral-flux onset detector: short-time energy changes across frequency
bands, peaks above the track's own local level, at least a quarter second
apart. Good enough to put a cut or a punch-in on the beat a viewer feels, and
it needs nothing beyond numpy and the ffmpeg already required.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from social_video.errors import FFmpegError
from social_video.ffmpeg.run import run_ffmpeg_bytes

RATE = 11025
HOP = 256
WINDOW = 1024
MIN_GAP = 0.25


def detect_beats(
    audio: Path, *, start_at: float = 0.0, duration: float | None = None
) -> list[float]:
    """Beat times in seconds from ``start_at`` into the file."""
    argv = ["-v", "error", "-ss", f"{max(0.0, start_at):.6f}"]
    if duration is not None:
        argv += ["-t", f"{max(0.1, duration):.6f}"]
    argv += ["-i", str(audio), "-map", "0:a:0", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"]
    try:
        raw = run_ffmpeg_bytes(argv, desc=f"decode {audio.name} for beats", timeout=600)
    except FFmpegError:
        return []
    return onsets(np.frombuffer(raw, dtype=np.float32), RATE) if raw else []


def onsets(signal: np.ndarray, rate: int = RATE) -> list[float]:
    if signal.size < WINDOW * 2:
        return []
    frames = np.lib.stride_tricks.sliding_window_view(signal, WINDOW)[::HOP]
    spectrum = np.abs(np.fft.rfft(frames * np.hanning(WINDOW), axis=1))
    flux = np.maximum(np.diff(np.log1p(spectrum), axis=0), 0.0).sum(axis=1)
    if flux.max() <= 0:
        return []
    # Compare each frame with its own neighbourhood, so a quiet intro and a
    # loud chorus both yield their beats.
    # Average over the frames that exist: near either end of the window the
    # neighbourhood is cut short, and counting the missing frames as silence
    # let the noise floor of the first and last quarter second read as beats.
    width = max(3, int(0.5 * rate / HOP))
    kernel = np.ones(width)
    local = np.convolve(flux, kernel, mode="same") / np.convolve(
        np.ones_like(flux), kernel, mode="same"
    )
    spread = flux.std()
    gap = int(MIN_GAP * rate / HOP)
    beats: list[float] = []
    last = -gap
    for index in range(1, flux.size - 1):
        peak = flux[index] >= flux[index - 1] and flux[index] >= flux[index + 1]
        if peak and flux[index] > local[index] + 0.5 * spread and index - last >= gap:
            # A window reports a change when the onset reaches its middle.
            beats.append(round(((index + 1) * HOP + WINDOW / 2) / rate, 3))
            last = index
    return beats


def snap(time: float, beats: list[float], *, tolerance: float = 0.12) -> float:
    """The nearest beat within ``tolerance``, else the time unchanged."""
    if not beats:
        return time
    nearest = min(beats, key=lambda beat: abs(beat - time))
    return nearest if abs(nearest - time) <= tolerance else time
