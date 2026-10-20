"""Named grades: drawn when known, refused when not."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from social_video.grades import grade_filter, grade_names
from social_video.schemas.edl import EDL, EDLRange


def test_names_combine_in_order_and_unknown_ones_are_refused() -> None:
    assert grade_names("") == []
    assert grade_names("mono_contrast+shake") == ["mono_contrast", "shake"]
    with pytest.raises(ValueError, match=r"unknown grade 'sepia'.*mono, mono_contrast, shake"):
        grade_names("mono+sepia")


def test_the_edl_refuses_a_grade_no_renderer_draws() -> None:
    with pytest.raises(ValidationError, match="unknown grade 'teal_orange'"):
        EDLRange(source="a", start=0, end=1, grade="teal_orange")
    with pytest.raises(ValidationError, match="unknown grade"):
        EDL(ranges=[EDLRange(source="a", start=0, end=1)], grade="film")


def test_shake_stays_inside_an_enlarged_frame_of_the_canvas() -> None:
    chain = grade_filter("shake", (1080, 1920))
    assert chain is not None
    assert chain.startswith("scale=1166:2074")
    assert "crop=1080:1920" in chain
    assert grade_filter("mono", (1080, 1920)) == "hue=s=0"
    assert grade_filter("", (1080, 1920)) is None
