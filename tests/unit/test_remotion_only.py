from __future__ import annotations

import pytest

from social_video.errors import ValidationError
from social_video.pipeline import _check_remotion_only
from social_video.schemas.brand import BrandProfile, CaptionBackgroundStyle, CaptionStyle
from social_video.schemas.config import BrandContract
from social_video.schemas.workflow import Renderer


def _contract(
    background: CaptionBackgroundStyle = CaptionBackgroundStyle.NONE, **captions: object
) -> BrandContract:
    return BrandContract(
        project_config_path="c.yaml",
        project_config_sha256="c" * 64,
        project_root="/p",
        brand=BrandProfile(captions=CaptionStyle(background_style=background, **captions)),
        output_width=1080,
        output_height=1920,
        output_fps="30/1",
    )


def test_the_ffmpeg_route_refuses_rounded_lines_captions() -> None:
    contract = _contract(CaptionBackgroundStyle.ROUNDED_LINES)
    with pytest.raises(ValidationError, match="rounded_lines"):
        _check_remotion_only(contract, Renderer.FFMPEG, captions=True)


def test_rounded_lines_pass_on_remotion_or_without_captions() -> None:
    contract = _contract(CaptionBackgroundStyle.ROUNDED_LINES)
    _check_remotion_only(contract, Renderer.REMOTION, captions=True)
    _check_remotion_only(contract, Renderer.FFMPEG, captions=False)


def test_the_ffmpeg_route_still_draws_a_rounded_box() -> None:
    _check_remotion_only(
        _contract(CaptionBackgroundStyle.ROUNDED_BOX), Renderer.FFMPEG, captions=True
    )


def test_the_ffmpeg_route_refuses_an_emphasis_mark() -> None:
    marked = _contract(emphasis_words=["studio"], emphasis_mark="highlight")
    with pytest.raises(ValidationError, match="emphasis_mark: highlight"):
        _check_remotion_only(marked, Renderer.FFMPEG, captions=True)
    _check_remotion_only(marked, Renderer.REMOTION, captions=True)
    # A mark with no words to put it on asks for nothing.
    _check_remotion_only(_contract(emphasis_mark="circle"), Renderer.FFMPEG, captions=True)
