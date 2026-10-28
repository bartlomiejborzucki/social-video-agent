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


def test_words_not_spoken_yet_are_dimmed_mid_caption(tmp_path: Path) -> None:
    from social_video.schemas.brand import CaptionStyle
    from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord

    spoken = [("mama", 0.0, 1.0), ("tata", 1.0, 2.0), ("baba", 2.0, 3.0)]
    track = CaptionTrack(
        cues=[
            CaptionCue(index=1, start=0.0, end=3.0, text="mama tata baba",
                       words=[CaptionWord(text=w, start=s, end=e) for w, s, e in spoken])
        ]
    )  # fmt: skip
    style = CaptionStyle(
        primary_colour="#FFFFFF", highlight_active_word=True, highlight_colour="#FFD400",
        upcoming_word_opacity=0.4, font_size_pct=6.0, max_lines=1, outline_width=0,
    )  # fmt: skip
    frame, features = _render(
        tmp_path, MotionPlan(rationale="Caption check."), seconds=3.0,
        captions=track, caption_style=style,
    )  # fmt: skip
    assert "upcoming_words_dimmed" in features

    pixels = frame(1.5)
    drawn = pixels.max(axis=-1) > 60
    columns = np.flatnonzero(drawn.any(axis=0))
    # The words are the runs of drawn columns between the two widest gaps.
    gaps = np.argsort(np.diff(columns))[-2:]
    words = np.split(columns, sorted(gaps + 1))
    said, current, coming = (pixels[:, part][drawn[:, part]] for part in words)
    # Before the current word: full white. The current word: the highlight.
    # After it: the caption colour at 40 %, so no pixel reaches full white.
    assert np.percentile(said.min(axis=-1), 90) > 200
    core = current[current.max(axis=-1) > 180]
    assert (core[:, 2] < core[:, 0] - 80).mean() > 0.9  # yellow: blue far under red
    assert (current.min(axis=-1) > 200).mean() < 0.02  # and nothing white
    assert coming.max() < 140
    # Once it is said, the last word is drawn at full strength.
    assert np.percentile(frame(2.95)[:, words[2]].max(axis=-1), 99.5) > 200
