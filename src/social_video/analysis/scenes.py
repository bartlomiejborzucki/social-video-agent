"""Scene detection.

Scene cuts are information, not instructions. They tell us where the source
already changes, which is where our own crop may move without looking like a
mistake, and where a cut will feel natural. They do not decide what to keep.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def detect_scenes(
    video: Path, *, threshold: float = 27.0, min_scene_len: float = 0.6
) -> list[tuple[float, float]]:
    """Detect scene boundaries. Returns (start, end) pairs in seconds.

    Uses PySceneDetect's content detector, which compares frame content rather
    than raw luma and so is not fooled by a lighting change.
    """
    try:
        from scenedetect import ContentDetector, detect
    except ImportError:
        log.warning("scenedetect is not installed; treating the source as one scene")
        return []

    try:
        scenes = detect(
            str(video),
            ContentDetector(threshold=threshold, min_scene_len=1),
            show_progress=False,
        )
    except Exception as exc:
        # A source we cannot analyse is not a reason to fail an edit.
        log.warning("scene detection failed for %s: %s", video.name, exc)
        return []

    out: list[tuple[float, float]] = []
    for start, end in scenes:
        a, b = start.get_seconds(), end.get_seconds()
        if b - a >= min_scene_len:
            out.append((a, b))
    return out


def scene_cut_times(scenes: list[tuple[float, float]]) -> list[float]:
    """Just the cut instants, excluding the very start of the source."""
    return [start for start, _ in scenes[1:]]
