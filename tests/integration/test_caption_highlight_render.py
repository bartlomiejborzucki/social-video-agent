"""The burned-in active-word highlight lights the spoken word, and only it.

The unit tests check the ASS text. This renders it with the real libass and
looks at the pixels, because the failure it guards against -- karaoke timing
that lights every word *not yet* spoken -- produced perfectly valid ASS.
"""

from __future__ import annotations

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
