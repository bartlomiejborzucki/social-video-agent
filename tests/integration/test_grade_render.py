"""Grades are drawn by the render, not just accepted by the schema."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from social_video.edl.render import DRAFT, render_edl
from social_video.schemas.edl import EDL, EDLRange
from social_video.sources import build_manifest
from tests.conftest import make_video, requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


def _frames(path: Path, size: tuple[int, int]) -> np.ndarray:
    width, height = size
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True,
        capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(-1, height, width, 3).astype(float)


def test_mono_contrast_and_shake_are_rendered(tmp_path: Path) -> None:
    source = make_video(tmp_path / "plac.mp4", width=320, height=568, duration=1.0)
    manifest = build_manifest([source])

    def render(grade: str) -> np.ndarray:
        edl = EDL(
            output_width=320,
            output_height=568,
            output_fps="30/1",
            normalize_audio=False,
            ranges=[EDLRange(source="plac", start=0, end=1, grade=grade)],
        )
        out = tmp_path / f"{grade or 'plain'}.mp4"
        render_edl(edl, manifest, out, quality=DRAFT)
        return _frames(out, (320, 568))

    plain = render("")
    mono = render("mono_contrast")
    shaken = render("shake")
    # Mono: the channels agree to within the encoder's chroma noise.
    assert np.abs(mono[..., 0] - mono[..., 2]).mean() < 4
    assert np.abs(plain[..., 0] - plain[..., 2]).mean() > 20
    # Shake: the picture moves against the ungraded one, frame to frame.
    drift = [np.abs(shaken[i] - plain[i]).mean() for i in range(0, len(plain), 5)]
    assert max(drift) > 5
