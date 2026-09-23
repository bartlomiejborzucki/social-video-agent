"""The 1.0 graphics vocabulary: each type says what it needs, and gets it."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from social_video.schemas.motion import MotionElement


def _element(kind: str, **fields) -> MotionElement:
    return MotionElement(type=kind, start=0, end=2, reason="it earns its place", **fields)


@pytest.mark.parametrize("kind", ["quote", "stat", "chapter", "cta"])
def test_worded_graphics_need_their_words(kind: str) -> None:
    with pytest.raises(PydanticValidationError, match=f"a {kind} needs text"):
        _element(kind)


@pytest.mark.parametrize("kind", ["progress", "logo_reveal"])
def test_textless_graphics_refuse_words(kind: str) -> None:
    _element(kind)
    with pytest.raises(PydanticValidationError, match="carries no text"):
        _element(kind, text="Subscribe")


def test_a_list_has_two_to_five_short_points() -> None:
    _element("list", items=["Nagraj", "Wytnij", "Opublikuj"])
    for items in (["Tylko jeden"], ["x" * 61, "ok"]):
        with pytest.raises(PydanticValidationError, match="two to five items"):
            _element("list", items=items)
    with pytest.raises(PydanticValidationError, match="only used by a list"):
        _element("quote", text="Cytat", items=["a", "b"])


def test_a_stat_is_one_short_figure() -> None:
    _element("stat", text="73,5%", secondary_text="widzów ogląda bez dźwięku")
    with pytest.raises(PydanticValidationError, match="one figure"):
        _element("stat", text="siedemdziesiąt trzy procent")
