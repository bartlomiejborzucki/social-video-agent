"""The burned-in active-word highlight lights the spoken word, and only it.

The unit tests check the ASS text. This renders it with the real libass and
looks at the pixels, because the failure it guards against -- karaoke timing
that lights every word *not yet* spoken -- produced perfectly valid ASS.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from social_video.captions.ass import write_ass
from social_video.ffmpeg.filters import escape_filter_path
from social_video.ffmpeg.run import has_libass
from social_video.schemas.brand import CaptionStyle
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord
from tests.conftest import requires_ffmpeg

pytestmark = [
    pytest.mark.integration,
    requires_ffmpeg,
    pytest.mark.skipif(not has_libass(), reason="ffmpeg built without libass"),
]

WIDTH, HEIGHT = 540, 960


def _frame(tmp_path: Path, subtitles: Path, at: float) -> np.ndarray:
    png = tmp_path / f"frame-{at:.2f}.png"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={WIDTH}x{HEIGHT}:r=30:d=2",
            "-vf",
            f"subtitles={escape_filter_path(subtitles)}",
            "-ss",
            f"{at:.3f}",
            "-frames:v",
            "1",
            str(png),
        ],
        check=True,
    )
    with Image.open(png) as image:
        return np.asarray(image.convert("RGB")).astype(int)


def _yellow_share_left(pixels: np.ndarray) -> float:
    """Fraction of highlight-coloured pixels that sit left of the centre line."""
    red, green, blue = pixels[..., 0], pixels[..., 1], pixels[..., 2]
    yellow = (red > 180) & (green > 150) & (blue < 90)
    columns = np.nonzero(yellow)[1]
    assert columns.size, "no highlighted pixels were drawn"
    return float((columns < WIDTH / 2).mean())


def test_the_highlight_follows_the_spoken_word(tmp_path: Path) -> None:
    track = CaptionTrack(
        cues=[
            CaptionCue(
                index=1,
                start=0.0,
                end=1.6,
                text="MMMM WWWW",
                words=[
                    CaptionWord(text="MMMM", start=0.0, end=0.8),
                    CaptionWord(text="WWWW", start=0.8, end=1.6),
                ],
            )
        ]
    )
    style = CaptionStyle(
        highlight_active_word=True,
        highlight_colour="#FFD400",
        primary_colour="#FFFFFF",
        font_size_pct=6.0,
        max_lines=1,
    )
    subtitles = write_ass(track, style, tmp_path / "captions.ass", width=WIDTH, height=HEIGHT)

    first = _yellow_share_left(_frame(tmp_path, subtitles, 0.4))
    second = _yellow_share_left(_frame(tmp_path, subtitles, 1.2))

    assert first > 0.9, "while the first word is spoken, the highlight is on the left"
    assert second < 0.1, "while the second word is spoken, the highlight is on the right"


def _two_words() -> CaptionTrack:
    return CaptionTrack(
        cues=[
            CaptionCue(
                index=1,
                start=0.0,
                end=1.6,
                text="MMMM WWWW",
                words=[
                    CaptionWord(text="MMMM", start=0.0, end=0.8),
                    CaptionWord(text="WWWW", start=0.8, end=1.6),
                ],
            )
        ]
    )


def test_a_brand_keyword_is_drawn_in_its_colour(tmp_path: Path) -> None:
    style = CaptionStyle(
        emphasis_words=["mmmm"],
        emphasis_colour="#FFD400",
        primary_colour="#FFFFFF",
        font_size_pct=6.0,
        max_lines=1,
    )
    subtitles = write_ass(
        _two_words(), style, tmp_path / "captions.ass", width=WIDTH, height=HEIGHT
    )

    for at in (0.4, 1.2):
        assert _yellow_share_left(_frame(tmp_path, subtitles, at)) > 0.9


ROOT = Path(__file__).resolve().parents[2]
HAS_REMOTION = (
    shutil.which("node") is not None
    and (ROOT / "node_modules/remotion").is_dir()
    and (ROOT / "node_modules/.remotion").is_dir()
)


@pytest.mark.skipif(not HAS_REMOTION, reason="Remotion dependencies/browser not installed")
def test_remotion_draws_the_keyword_and_the_highlight(tmp_path: Path) -> None:
    from social_video.remotion import render_motion_design
    from social_video.schemas.motion import MotionPlan

    base = tmp_path / "base.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={WIDTH}x{HEIGHT}:r=30:d=2",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-t",
            "2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(base),
        ],
        check=True,
    )
    style = CaptionStyle(
        emphasis_words=["mmmm"],
        emphasis_colour="#FFD400",
        highlight_active_word=True,
        highlight_colour="#FFD400",
        primary_colour="#FFFFFF",
        font_size_pct=6.0,
        max_lines=1,
        outline_width=0,
    )
    output, features, _ = render_motion_design(
        base,
        tmp_path / "out.mp4",
        MotionPlan(rationale="Caption colour check."),
        duration_in_frames=60,
        fps=30,
        width=WIDTH,
        height=HEIGHT,
        staging_root=tmp_path / "stage",
        captions=_two_words(),
        caption_style=style,
    )

    def frame(at: float) -> np.ndarray:
        png = tmp_path / f"remotion-{at:.2f}.png"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                f"{at:.3f}",
                "-i",
                str(output),
                "-frames:v",
                "1",
                str(png),
            ],
            check=True,
        )
        with Image.open(png) as image:
            return np.asarray(image.convert("RGB")).astype(int)

    assert "keyword_emphasis" in features
    # While the keyword is spoken only it is yellow; while the second word is
    # spoken both are, because the keyword rests in its emphasis colour.
    assert _yellow_share_left(frame(0.4)) > 0.9
    share = _yellow_share_left(frame(1.2))
    assert 0.2 < share < 0.8


@pytest.mark.skipif(not HAS_REMOTION, reason="Remotion dependencies/browser not installed")
def test_a_punch_in_scales_the_picture_and_only_while_it_runs(tmp_path: Path) -> None:
    from social_video.remotion import render_motion_design
    from social_video.schemas.motion import MotionPlan, PunchIn

    base = tmp_path / "disc.mp4"
    # A white disc on black, centred on the punch-in's fixed point, so its area
    # measures the scale directly.
    subprocess.run(
        [
            "ffmpeg", "-v", "error",
            "-f", "lavfi", "-i", f"color=c=black:s={WIDTH}x{HEIGHT}:r=30:d=2",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-vf", "geq=lum='if(lt(hypot(X-W/2,Y-H/2),60),255,0)':cb=128:cr=128",
            "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(base),
        ],
        check=True,
    )  # fmt: skip
    plan = MotionPlan(
        rationale="Punch-in check.",
        punch_ins=[
            PunchIn(start=0.6, end=1.8, scale=1.3, focus_x=0.5, focus_y=0.5, reason="the point")
        ],
    )
    output, features, _ = render_motion_design(
        base,
        tmp_path / "out.mp4",
        plan,
        duration_in_frames=60,
        fps=30,
        width=WIDTH,
        height=HEIGHT,
        staging_root=tmp_path / "stage",
    )

    def white_area(at: float) -> int:
        png = tmp_path / f"punch-{at:.2f}.png"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.3f}", "-i", str(output),
             "-frames:v", "1", str(png)],
            check=True,
        )  # fmt: skip
        with Image.open(png) as image:
            return int((np.asarray(image.convert("L")) > 128).sum())

    before, held = white_area(0.3), white_area(1.2)
    assert "punch_in" in features
    assert held / before == pytest.approx(1.3**2, rel=0.08)
