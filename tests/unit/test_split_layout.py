"""Split layouts: two people stacked, or a screen above the presenter."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from social_video.reframe.detect import Face, FrameFaces
from social_video.reframe.plan import split_panes
from social_video.schemas.edl import Pane, PaneFit, ReframeMode, ReframePlan


def _pane(share: float, **extra) -> Pane:
    return Pane(x=0, y=0, width=100, height=100, share=share, **extra)


def test_a_stack_needs_two_or_three_panes_that_fill_the_frame() -> None:
    ReframePlan(mode=ReframeMode.SPLIT_STACK, panes=[_pane(0.6), _pane(0.4)])
    with pytest.raises(PydanticValidationError, match="two or three panes"):
        ReframePlan(mode=ReframeMode.SPLIT_STACK, panes=[_pane(1.0)])
    with pytest.raises(PydanticValidationError, match="add up to 1"):
        ReframePlan(mode=ReframeMode.SPLIT_STACK, panes=[_pane(0.5), _pane(0.3)])


def test_panes_belong_to_split_stack_only() -> None:
    with pytest.raises(PydanticValidationError, match="only used by split_stack"):
        ReframePlan(mode=ReframeMode.FIT, panes=[_pane(0.5), _pane(0.5)])


def _two_people(samples: int = 10, *, both: bool = True) -> list[FrameFaces]:
    left = Face(x=380, y=300, width=160, height=200, confidence=0.9)
    right = Face(x=1380, y=320, width=150, height=190, confidence=0.9)
    return [FrameFaces(t=i * 0.5, faces=(right, left) if both else (left,)) for i in range(samples)]


def test_two_people_get_one_pane_each_left_person_on_top() -> None:
    panes = split_panes(_two_people(), (1920, 1080), (1080, 1920))

    assert isinstance(panes, list) and len(panes) == 2
    top, bottom = panes
    assert top.x < bottom.x
    for pane in panes:
        assert pane.fit is PaneFit.COVER and pane.share == 0.5
        assert pane.x + pane.width <= 1920 and pane.y + pane.height <= 1080
        # Each crop has the band's shape, so covering it costs almost nothing.
        assert pane.width / pane.height == pytest.approx(1080 / 960, rel=0.02)
    assert top.x < 460 < top.x + top.width
    assert bottom.x < 1455 < bottom.x + bottom.width


def test_one_person_is_a_reason_not_a_stack() -> None:
    reason = split_panes(_two_people(both=False), (1920, 1080), (1080, 1920))

    assert isinstance(reason, str)
    assert "needs two people" in reason
