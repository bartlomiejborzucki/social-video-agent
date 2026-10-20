"""Audio/video sync of a composited render against the base it was drawn over.

A compositor that carries the sound itself can shift it: Remotion's audio path
once delayed every render by ~45 ms, a lag nobody notices on a single viewing
and everybody notices as lips that move before the voice. The base render is
checked against the sources already, so the delivered file is held to it:

* sound: the RMS envelopes of the two files are correlated in 10 s windows on
  a 5 ms grid, and the median lag is the offset;
* picture: downscaled frames are compared at small frame offsets, away from
  punch-ins and transitions, which redraw the whole frame on purpose.

The A/V error is the sound offset minus the picture offset: a render whose
picture and sound moved together is still in sync with itself.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np

from social_video.ffmpeg.run import find_binary
from social_video.schemas.qa import QACheck, QASeverity

RATE = 48000
#: 5 ms envelope grid.
HOP = 240
WINDOW_SECONDS = 10.0
MAX_LAG_SECONDS = 0.25
#: Larger than this between sound and picture is visible on a face.
AV_TOLERANCE = 0.020
MAX_FRAME_OFFSET = 3
_THUMB = (36, 64)


#: Windows whose best alignment correlates less than this are not evidence:
#: a steady tone or room noise matches itself at every lag.
MIN_CORRELATION = 0.6
#: Log-RMS spread below this (about 2 dB) has nothing to align on.
MIN_SPREAD = 0.25


@dataclass(frozen=True)
class SyncMeasurement:
    #: None when the sound has no variation to align on.
    audio_offset: float | None
    video_offset_frames: int | None
    frame_duration: float

    @property
    def video_offset(self) -> float:
        return (self.video_offset_frames or 0) * self.frame_duration

    @property
    def av_error(self) -> float | None:
        """How much later the sound plays than the picture, versus the base."""
        if self.audio_offset is None:
            return None
        return self.audio_offset - self.video_offset


def envelope(path: Path) -> np.ndarray:
    """Log RMS of the first audio track on a 5 ms grid."""
    proc = subprocess.run(
        [
            find_binary("ffmpeg"),
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            str(RATE),
            "-f",
            "f32le",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    return envelope_of(np.frombuffer(proc.stdout, dtype=np.float32))


def envelope_of(signal: np.ndarray) -> np.ndarray:
    frames = len(signal) // HOP
    if frames == 0:
        return np.zeros(0)
    blocks = signal[: frames * HOP].reshape(frames, HOP).astype(np.float64)
    return np.log(np.sqrt(np.mean(np.square(blocks), axis=1)) + 1e-6)


def envelope_lag(reference: np.ndarray, candidate: np.ndarray) -> float | None:
    """Seconds by which ``candidate`` plays later than ``reference``.

    The median over 10 s windows, so one window of room tone or music cannot
    decide the answer. None when no window has enough variation, or matches
    clearly enough, to be evidence.
    """
    per_second = RATE / HOP
    window = int(WINDOW_SECONDS * per_second)
    max_lag = int(MAX_LAG_SECONDS * per_second)
    length = min(len(reference), len(candidate))
    lags: list[int] = []
    start = max_lag
    while start + window + max_lag <= length or not lags:
        end = min(start + window, length - max_lag)
        if end - start < per_second:
            break
        ref = reference[start:end] - reference[start:end].mean()
        if float(np.std(ref)) < MIN_SPREAD:
            start += window
            continue
        best_score, best_lag = -np.inf, 0
        for lag in range(-max_lag, max_lag + 1):
            seg = candidate[start + lag : end + lag]
            seg = seg - seg.mean()
            norm = float(np.linalg.norm(ref) * np.linalg.norm(seg))
            score = float(np.dot(ref, seg)) / norm if norm > 0 else 0.0
            if score > best_score:
                best_score, best_lag = score, lag
        if best_score >= MIN_CORRELATION:
            lags.append(best_lag)
        start += window
    if not lags:
        return None
    return float(np.median(lags)) / per_second


def _thumbnails(path: Path) -> np.ndarray:
    width, height = _THUMB
    proc = subprocess.run(
        [
            find_binary("ffmpeg"),
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-vf",
            f"scale={width}:{height}:flags=area,format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    data = np.frombuffer(proc.stdout, dtype=np.uint8)
    return data[: len(data) // (width * height) * width * height].reshape(-1, height, width)


def frame_offset(
    reference: np.ndarray,
    candidate: np.ndarray,
    *,
    usable: list[int],
) -> int | None:
    """The frame shift that best maps ``reference`` onto ``candidate``."""
    if not usable:
        return None
    ref = reference.astype(np.float32)
    cand = candidate.astype(np.float32)
    scores: dict[int, float] = {}
    for shift in range(-MAX_FRAME_OFFSET, MAX_FRAME_OFFSET + 1):
        pairs = [i for i in usable if 0 <= i + shift < len(cand) and i < len(ref)]
        if not pairs:
            continue
        scores[shift] = float(np.mean([np.abs(ref[i] - cand[i + shift]).mean() for i in pairs]))
    if not scores:
        return None
    return min(scores, key=lambda k: (scores[k], abs(k)))


def usable_frames(
    total: int, fps: float, busy: list[tuple[float, float]], *, step: int = 5
) -> list[int]:
    """Frames away from spans that redraw the whole picture, with motion around them."""
    margin = MAX_FRAME_OFFSET + 2
    out: list[int] = []
    for index in range(margin, total - margin, step):
        t = index / fps
        if any(start - 0.2 <= t <= end + 0.2 for start, end in busy):
            continue
        out.append(index)
    return out


def measure_sync(
    base: Path,
    output: Path,
    *,
    fps: str,
    busy: list[tuple[float, float]] | None = None,
) -> SyncMeasurement:
    rate = float(Fraction(fps))
    audio = envelope_lag(envelope(base), envelope(output))
    ref, cand = _thumbnails(base), _thumbnails(output)
    usable = usable_frames(min(len(ref), len(cand)), rate, busy or [])
    video = frame_offset(ref, cand, usable=usable)
    return SyncMeasurement(audio_offset=audio, video_offset_frames=video, frame_duration=1 / rate)


def sync_check(measurement: SyncMeasurement) -> QACheck:
    error = measurement.av_error
    frames = measurement.video_offset_frames
    if error is None:
        return QACheck(
            name="audio/video sync against base",
            severity=QASeverity.INFO,
            passed=True,
            message="not measured: the sound has too little variation to align on",
        )
    picture = "picture not compared" if frames is None else f"picture {frames:+d} frame(s)"
    ok = abs(error) <= AV_TOLERANCE
    return QACheck(
        name="audio/video sync against base",
        severity=QASeverity.ERROR,
        passed=ok,
        message=(
            f"sound {(measurement.audio_offset or 0.0) * 1000:+.0f} ms, {picture} against the base "
            f"render; A/V error {error * 1000:+.0f} ms"
            + ("" if ok else f" exceeds {AV_TOLERANCE * 1000:.0f} ms (positive: sound is late)")
        ),
        measured=round(error, 4),
        expected=0.0,
    )
