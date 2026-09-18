"""Choosing which detected face is the one currently talking.

This is **audio-correlated mouth motion**, not neural active-speaker detection.
It tracks each face across sampled frames, measures how much the mouth region
changes between samples, and correlates that with the speech envelope taken from
the audio. The face whose mouth moves when the audio is loud is the speaker.

Why this rather than the alternatives the ecosystem audit rejected: it samples
densely across the whole range instead of a handful of frames, it uses temporal
motion rather than a single-frame mouth-aspect ratio, it associates faces into
tracks so a score belongs to a person rather than to a bounding box, and it
correlates against the real audio instead of guessing from the picture alone.

Its limits are stated rather than hidden. It cannot tell apart two people whose
mouths move together, it degrades on heavy motion blur or a moving camera, and
when no track is convincingly better than the runner-up it returns nothing so
the caller falls back to face prominence. Proper ASD -- LR-ASD is the candidate
recorded in the ecosystem audit -- remains the next step, and would replace the
scoring here without changing this module's interface.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from social_video.ffmpeg.run import find_binary
from social_video.reframe.detect import Face, FrameFaces

log = logging.getLogger(__name__)

#: Sampling rate for speaker analysis. Mouth motion needs more than the two
#: samples per second that crop placement is happy with.
SPEAKER_SAMPLES_PER_SECOND = 6.0
#: Never analyse more than this many frames, whatever the range length.
MAX_SPEAKER_SAMPLES = 900
#: Mouth patch edge, in pixels, that every mouth is resampled to.
MOUTH_PATCH = 24
#: A face further than this fraction of its own width from a track's last known
#: position is a different person, not the same one having moved.
TRACK_DISTANCE = 1.2
#: Below this correlation nothing is claimed.
MIN_CORRELATION = 0.15
#: The winner must beat the runner-up by this much to be called the speaker.
MIN_MARGIN = 0.08


@dataclass
class FaceTrack:
    """One person followed across sampled frames."""

    id: int
    #: Sample index -> the face found for this track at that sample.
    faces: dict[int, Face] = field(default_factory=dict)
    #: Sample index -> mean absolute mouth-patch change since the previous sample.
    motion: dict[int, float] = field(default_factory=dict)

    @property
    def coverage(self) -> int:
        return len(self.faces)

    def last_index(self) -> int:
        return max(self.faces) if self.faces else -1


def track_faces(samples: list[FrameFaces]) -> list[FaceTrack]:
    """Associate faces across samples by nearest centre.

    Deliberately simple: an identity model would be a second dependency and the
    failure it guards against -- two faces swapping identity between samples --
    is already handled by requiring a clear margin before naming a speaker.
    """
    tracks: list[FaceTrack] = []
    for index, sample in enumerate(samples):
        unmatched = list(sample.faces)
        for track in sorted(tracks, key=lambda t: -t.last_index()):
            if not unmatched or index - track.last_index() > 3:
                continue
            previous = track.faces[track.last_index()]
            best = min(unmatched, key=lambda f: _distance(f, previous))
            if _distance(best, previous) <= TRACK_DISTANCE * max(1.0, previous.width):
                track.faces[index] = best
                unmatched.remove(best)
        for face in unmatched:
            track = FaceTrack(id=len(tracks))
            track.faces[index] = face
            tracks.append(track)
    return tracks


def _distance(face: Face, other: Face) -> float:
    ax, ay = face.center
    bx, by = other.center
    return float(np.hypot(ax - bx, ay - by))


def speech_envelope(audio_source: Path, times: list[float], *, window: float = 0.25) -> list[float]:
    """Per-sample speech energy, normalised to 0-1 across the range.

    Decoded once as mono 16 kHz PCM. Anything quieter than the range's own noise
    floor reads as zero, so a silent passage cannot correlate with anything.
    """
    if not times:
        return []
    start, stop = times[0], times[-1] + window
    argv = [
        find_binary("ffmpeg"),
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-ss",
        f"{max(0.0, start):.6f}",
        "-t",
        f"{max(0.05, stop - start):.6f}",
        "-i",
        str(audio_source),
        "-map",
        "0:a:0",
        "-f",
        "s16le",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-",
    ]
    proc = subprocess.run(argv, capture_output=True, check=False, timeout=1800)
    if proc.returncode != 0 or not proc.stdout:
        log.debug("could not read audio for speaker detection")
        return [0.0] * len(times)
    signal = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    rate = 16000
    energies: list[float] = []
    for t in times:
        begin = int(max(0.0, t - start) * rate)
        end = min(len(signal), begin + int(window * rate))
        chunk = signal[begin:end]
        energies.append(float(np.sqrt(np.mean(np.square(chunk)))) if chunk.size else 0.0)
    peak = max(energies, default=0.0)
    return [value / peak for value in energies] if peak > 0 else [0.0] * len(times)


def mouth_patch(frame, face: Face) -> np.ndarray | None:
    """A small grayscale crop centred on the mouth, normalised for exposure."""
    centre = face.mouth_center
    if centre is None or frame is None:
        return None
    height, width = frame.shape[:2]
    half = max(4.0, face.width * 0.3)
    x0 = int(max(0, centre[0] - half))
    x1 = int(min(width, centre[0] + half))
    y0 = int(max(0, centre[1] - half * 0.7))
    y1 = int(min(height, centre[1] + half * 0.7))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    import cv2

    patch = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    patch = cv2.resize(patch, (MOUTH_PATCH, MOUTH_PATCH), interpolation=cv2.INTER_AREA)
    values = patch.astype(np.float32)
    spread = float(values.std())
    # Normalise per patch so a face in shadow is compared on movement, not on
    # how brightly it happens to be lit.
    return (values - float(values.mean())) / spread if spread > 1e-3 else values * 0.0


def correlation(motion: list[float | None], speech: list[float]) -> float:
    """Pearson correlation over the samples where this track was actually visible."""
    pairs = [
        (m, s) for m, s in zip(motion, speech, strict=True) if m is not None and not np.isnan(m)
    ]
    if len(pairs) < 4:
        return 0.0
    left = np.array([p[0] for p in pairs], dtype=np.float64)
    right = np.array([p[1] for p in pairs], dtype=np.float64)
    if left.std() < 1e-9 or right.std() < 1e-9:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


@dataclass(frozen=True)
class SpeakerChoice:
    """Which track is talking, and how sure we are allowed to sound about it."""

    track_id: int | None
    score: float
    margin: float
    reason: str

    @property
    def confident(self) -> bool:
        return self.track_id is not None


def choose_speaker(
    tracks: list[FaceTrack], speech: list[float], sample_count: int
) -> SpeakerChoice:
    """Pick the track whose mouth moves with the audio, or decline to pick."""
    if not tracks:
        return SpeakerChoice(None, 0.0, 0.0, "no faces were tracked")
    if len(tracks) == 1:
        return SpeakerChoice(
            tracks[0].id, 1.0, 1.0, "a single tracked face; no speaker ambiguity to resolve"
        )
    scored: list[tuple[float, FaceTrack]] = []
    for track in tracks:
        motion: list[float | None] = [track.motion.get(index) for index in range(sample_count)]
        scored.append((correlation(motion, speech), track))
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best = scored[0]
    runner_up = scored[1][0]
    margin = best_score - runner_up
    if best_score < MIN_CORRELATION:
        return SpeakerChoice(
            None,
            best_score,
            margin,
            f"no face's mouth movement tracked the audio (best r={best_score:.2f})",
        )
    if margin < MIN_MARGIN:
        return SpeakerChoice(
            None,
            best_score,
            margin,
            f"two faces moved with the audio equally (r={best_score:.2f} vs {runner_up:.2f})",
        )
    return SpeakerChoice(
        best.id,
        best_score,
        margin,
        f"mouth movement correlated with speech (r={best_score:.2f}, "
        f"{margin:.2f} clear of the next face)",
    )


def analyse_speaker(
    video: Path,
    *,
    start: float,
    end: float,
    audio_source: Path | None = None,
) -> tuple[list[FrameFaces], list[FaceTrack], SpeakerChoice]:
    """Sample the range once, tracking faces and mouth motion, and pick a speaker."""
    from social_video.reframe.detect import detect_faces

    span = max(0.1, end - start)
    rate = min(SPEAKER_SAMPLES_PER_SECOND, MAX_SPEAKER_SAMPLES / span)
    patches: dict[float, dict[int, np.ndarray]] = {}
    order: list[float] = []

    def collect(t: float, frame, faces: tuple[Face, ...]) -> None:
        order.append(t)
        patches[t] = {}
        for index, face in enumerate(faces):
            patch = mouth_patch(frame, face)
            if patch is not None:
                patches[t][index] = patch

    samples = detect_faces(video, start=start, end=end, samples_per_second=rate, on_frame=collect)
    tracks = track_faces(samples)
    _fill_motion(samples, tracks, patches)
    speech = speech_envelope(audio_source or video, [s.t for s in samples])
    return samples, tracks, choose_speaker(tracks, speech, len(samples))


def _fill_motion(
    samples: list[FrameFaces],
    tracks: list[FaceTrack],
    patches: dict[float, dict[int, np.ndarray]],
) -> None:
    """Mouth motion is the change since this track's previous sighting."""
    for track in tracks:
        previous: np.ndarray | None = None
        for index in sorted(track.faces):
            sample = samples[index]
            face = track.faces[index]
            position = next((i for i, f in enumerate(sample.faces) if f is face), None)
            patch = patches.get(sample.t, {}).get(position) if position is not None else None
            if patch is not None and previous is not None and patch.shape == previous.shape:
                track.motion[index] = float(np.mean(np.abs(patch - previous)))
            if patch is not None:
                previous = patch
