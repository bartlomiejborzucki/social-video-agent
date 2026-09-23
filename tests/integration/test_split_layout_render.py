"""A stacked layout renders each region into its own band, at the right size."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from social_video.edl.render import PREVIEW, render_edl
from social_video.schemas.edl import EDL, EDLRange, Pane, PaneFit, ReframeMode, ReframePlan
from social_video.sources import build_manifest
from tests.conftest import ffmpeg, requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


def _halves(path: Path) -> Path:
    """Red on the left, blue on the right, 640x360."""
    ffmpeg(
        "-f", "lavfi", "-i", "color=c=red:s=320x360:r=30:d=1",
        "-f", "lavfi", "-i", "color=c=blue:s=320x360:r=30:d=1",
        "-f", "lavfi", "-i", "sine=d=1",
        "-filter_complex", "[0:v][1:v]hstack=inputs=2[v]",
        "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(path),
    )  # fmt: skip
    return path


def _frame(video: Path, tmp_path: Path) -> np.ndarray:
    png = tmp_path / "frame.png"
    ffmpeg("-ss", "0.5", "-i", str(video), "-frames:v", "1", str(png))
    with Image.open(png) as image:
        return np.asarray(image.convert("RGB")).astype(int)


def test_two_regions_stack_top_and_bottom(tmp_path: Path) -> None:
    source = _halves(tmp_path / "rozmowa.mp4")
    edl = EDL(
        output_width=180,
        output_height=320,
        normalize_audio=False,
        ranges=[
            EDLRange(
                source="rozmowa",
                start=0,
                end=0.9,
                reframe=ReframePlan(
                    mode=ReframeMode.SPLIT_STACK,
                    panes=[
                        Pane(x=0, y=0, width=300, height=360, share=0.6, label="left"),
                        Pane(x=340, y=0, width=300, height=360, share=0.4, label="right"),
                    ],
                ),
            )
        ],
    )
    output = tmp_path / "stack.mp4"

    render_edl(edl, build_manifest([source]), output, quality=PREVIEW)

    pixels = _frame(output, tmp_path)
    assert pixels.shape[:2] == (320, 180)
    red = (pixels[..., 0] > 150) & (pixels[..., 2] < 100)
    blue = (pixels[..., 2] > 150) & (pixels[..., 0] < 100)
    boundary = round(320 * 0.6 / 2) * 2
    assert red[: boundary - 4].mean() > 0.95
    assert blue[boundary + 4 :].mean() > 0.95


def test_a_contained_screen_pane_is_padded_not_cropped(tmp_path: Path) -> None:
    source = _halves(tmp_path / "ekran.mp4")
    edl = EDL(
        output_width=180,
        output_height=320,
        normalize_audio=False,
        ranges=[
            EDLRange(
                source="ekran",
                start=0,
                end=0.9,
                reframe=ReframePlan(
                    mode=ReframeMode.SPLIT_STACK,
                    panes=[
                        # The whole 16:9 frame, shown in full above the face.
                        Pane(x=0, y=0, width=640, height=360, share=0.5, fit=PaneFit.CONTAIN),
                        Pane(x=0, y=0, width=320, height=360, share=0.5),
                    ],
                ),
            )
        ],
    )
    output = tmp_path / "screen.mp4"

    render_edl(edl, build_manifest([source]), output, quality=PREVIEW)

    top = _frame(output, tmp_path)[:160]
    # Both halves of the screen survive, with black bars above and below.
    assert ((top[..., 0] > 150) & (top[..., 2] < 100)).any()
    assert ((top[..., 2] > 150) & (top[..., 0] < 100)).any()
    assert (top[:10].max(axis=-1) < 40).all()
