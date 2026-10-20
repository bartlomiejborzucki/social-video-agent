"""Open on the moment the picture moves, not on a still frame before it.

The first second decides whether a viewer stays, and a clip often starts a
beat before anything happens in it. This measures how much the picture of the
first range changes, frame to frame, over its first two seconds, and proposes
starting it where the movement starts -- only where that cuts no words: under
a separate voice the picture is free to move, and over its own sound only
when nothing is said before the new in-point.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from social_video.ffmpeg.run import find_binary
from social_video.schemas.edl import EDL
from social_video.schemas.motion import RangeStart
from social_video.schemas.source import SourceManifest
from social_video.schemas.transcript import Transcript

WINDOW = 2.0
RATE = 10
#: Mean change per sampled frame, out of 255, below which the picture is still.
STILL = 3.0


def picture_change(video: Path, start: float, window: float = WINDOW) -> list[tuple[float, float]]:
    """(source time, change to the next sample) across ``window`` seconds."""
    width, height = 48, 84
    proc = subprocess.run(
        [find_binary("ffmpeg"), "-v", "error", "-nostdin", "-ss", f"{start:.3f}", "-t",
         f"{window:.3f}", "-i", str(video), "-vf",
         f"fps={RATE},scale={width}:{height}:flags=area,format=gray", "-f", "rawvideo", "-"],
        capture_output=True, check=False,
    )  # fmt: skip
    data = np.frombuffer(proc.stdout, dtype=np.uint8)
    frames = data[: len(data) // (width * height) * width * height].reshape(-1, height, width)
    frames = frames.astype(np.float32)
    return [
        (round(start + index / RATE, 3), float(np.abs(frames[index + 1] - frames[index]).mean()))
        for index in range(len(frames) - 1)
    ]


def opening_in_point(
    edl: EDL, sources: SourceManifest, transcripts: dict[str, Transcript]
) -> RangeStart | None:
    """A later in-point for the first range where its picture starts moving, or None."""
    first = edl.ranges[0]
    entry = sources.by_id(first.effective_video_source)
    changes = picture_change(entry.resolved_path(), first.effective_video_start)
    if len(changes) < 3:
        return None
    opening = changes[0][1]
    moment, peak = max(changes, key=lambda item: item[1])
    if peak < STILL or opening >= 0.6 * peak or moment <= first.effective_video_start + 0.05:
        return None
    start = round(max(first.effective_video_start, moment - 0.05), 3)
    separate = first.audio_source is not None and first.audio_source != first.source
    if separate:
        needed = first.output_duration * first.speed
        if start + needed > entry.duration + 1e-3:
            return None
    else:
        transcript = transcripts.get(first.effective_audio_source)
        if transcript is None:
            return None
        if any(first.start - 1e-3 <= w.start < start + 0.1 for w in transcript.words):
            return None
    return RangeStart(
        range_index=0,
        video_start=start,
        reason=(
            f"the picture is still at {first.effective_video_start:.2f}s (change {opening:.1f}) "
            f"and moves from {moment:.2f}s (change {peak:.1f})"
        ),
    )
