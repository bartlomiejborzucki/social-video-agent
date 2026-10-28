"""Graphics synced to the spoken word, drawn by Remotion over a black frame."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from social_video.schemas.motion import MotionElement, MotionPlan
from tests.conftest import requires_ffmpeg

ROOT = Path(__file__).resolve().parents[2]
HAS_REMOTION = shutil.which("node") is not None and (ROOT / "node_modules/.remotion").is_dir()
WIDTH, HEIGHT = 360, 640

pytestmark = [
    pytest.mark.integration,
    requires_ffmpeg,
    pytest.mark.skipif(not HAS_REMOTION, reason="Remotion dependencies/browser not installed"),
]


def _black(tmp_path: Path, seconds: float) -> Path:
    base = tmp_path / "black.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", f"color=c=black:s={WIDTH}x{HEIGHT}:r=30:d={seconds}",
         "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
         "-t", f"{seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(base)],
        check=True,
    )  # fmt: skip
    return base


def _render(tmp_path: Path, plan: MotionPlan, seconds: float = 4.0, **options):
    from social_video.remotion import render_motion_design

    output, features, _layout = render_motion_design(
        _black(tmp_path, seconds),
        tmp_path / "out.mp4",
        plan,
        duration_in_frames=round(seconds * 30),
        fps=30,
        width=WIDTH,
        height=HEIGHT,
        staging_root=tmp_path / "stage",
        **options,
    )

    def frame(at: float) -> np.ndarray:
        png = tmp_path / f"f-{at:.2f}.png"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.3f}", "-i", str(output),
             "-frames:v", "1", str(png)],
            check=True,
        )  # fmt: skip
        with Image.open(png) as image:
            return np.asarray(image.convert("RGB")).astype(int)

    return frame, features


def test_list_points_enter_on_their_word_times(tmp_path: Path) -> None:
    listed = MotionElement(
        type="list", start=0.3, end=3.8, text="Spróbuj tak", items=["Kąpiel", "Bajka"],
        position="top", item_times=[1.0, 2.5], reason="Each point as it is said.",
    )  # fmt: skip
    frame, _ = _render(tmp_path, MotionPlan(rationale="Anchored list.", elements=[listed]))

    def change(a: float, b: float) -> float:
        return float(np.abs(frame(a) - frame(b)).mean())

    # Each point waits for its word (an even reveal would show the first at
    # 0.3 s and the second at 1.5 s), and nothing moves between the words.
    assert change(0.8, 1.9) > 0.2
    assert change(1.9, 2.4) < 0.05
    assert change(2.4, 3.0) > 0.2
    assert change(3.3, 3.5) < 0.05
