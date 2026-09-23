"""Punch-ins are timed, non-overlapping, and held to the brand's movement limit."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from social_video.errors import ValidationError
from social_video.pipeline import _check_movement
from social_video.schemas.brand import BrandProfile
from social_video.schemas.config import BrandContract
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import MotionPlan, PunchIn


def _punch(start: float, end: float, scale: float = 1.1) -> PunchIn:
    return PunchIn(start=start, end=end, scale=scale, reason="the point lands here")


def _contract(*, limit: float = 1.12, intensity: float = 0.25) -> BrandContract:
    return BrandContract(
        project_config_path="c.yaml",
        project_config_sha256="0" * 64,
        project_root=".",
        brand=BrandProfile(punch_in_max=limit, motion_intensity=intensity),
        output_width=1080,
        output_height=1920,
        output_fps="30/1",
    )


def test_a_punch_in_needs_time_to_ease_in_and_out() -> None:
    with pytest.raises(PydanticValidationError, match=r"at least 0\.4 s"):
        _punch(1.0, 1.2)


def test_a_punch_in_never_zooms_out_or_past_one_and_a_half() -> None:
    for scale in (1.0, 1.6):
        with pytest.raises(PydanticValidationError):
            _punch(0, 1, scale=scale)


def test_punch_ins_may_not_overlap() -> None:
    with pytest.raises(PydanticValidationError, match="overlap"):
        MotionPlan(rationale="r", punch_ins=[_punch(0, 2), _punch(1.5, 3)])


def test_the_brand_limit_and_a_still_brand_are_both_enforced() -> None:
    plan = MotionPlan(rationale="r", punch_ins=[_punch(0, 1, scale=1.2)])
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=2, zoom=1.3)])

    with pytest.raises(ValidationError) as limited:
        _check_movement(edl, plan, _contract(limit=1.12))
    message = str(limited.value)
    assert "range 0 zooms to 1.3" in message
    assert "punch-in at 0.00s scales to 1.2" in message

    with pytest.raises(ValidationError, match="punch_in_intensity: 0"):
        _check_movement(
            EDL(ranges=[EDLRange(source="a", start=0, end=2)]),
            plan,
            _contract(limit=1.5, intensity=0.0),
        )


def test_movement_within_the_contract_passes() -> None:
    plan = MotionPlan(rationale="r", punch_ins=[_punch(0, 1, scale=1.12)])
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=2, zoom=1.1)])

    _check_movement(edl, plan, _contract())
