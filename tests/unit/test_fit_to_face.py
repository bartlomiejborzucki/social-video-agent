"""A card over the head ends above it: fitted from the measured face."""

from __future__ import annotations

import pytest

from social_video.motion.layout import (
    MIN_FIT_SCALE,
    element_band,
    face_clear_line,
    fit_to_face,
)
from social_video.remotion import _element_payload
from social_video.schemas.edl import EDL, EDLRange, ReframeMode, ReframePlan
from social_video.schemas.motion import MotionElement, MotionPlan

MARGINS = {"top": 6.0, "right": 6.0, "bottom": 12.0, "left": 6.0}
H = 1920


def _edl(focus_y: float | None, face: float = 0.22, zoom: float = 1.0) -> EDL:
    plan = (
        ReframePlan(mode=ReframeMode.FIT, focus_x=0.5, focus_y=focus_y, face_height=face)
        if focus_y is not None
        else None
    )
    return EDL(ranges=[EDLRange(source="kamera", start=0, end=20, zoom=zoom, reframe=plan)])


def _process() -> MotionElement:
    return MotionElement(
        type="process", start=4.0, end=8.0, text="Plan dnia:",
        items=["rano", "południe", "wieczór"], reason="Trzy etapy.",
    )  # fmt: skip


def test_the_forehead_ends_above_the_eyes_by_the_measured_face() -> None:
    assert face_clear_line(_edl(0.30), 4, 8, H) == pytest.approx((0.30 - 0.45 * 0.22) * H)
    # A zoom enlarges the face and leaves the eyes where they were.
    zoomed = face_clear_line(_edl(0.30, zoom=1.25), 4, 8, H)
    assert zoomed == pytest.approx((0.30 - 0.45 * 0.22 * 1.25) * H)
    assert face_clear_line(_edl(None), 4, 8, H) is None
    assert face_clear_line(_edl(0.30), 30, 34, H) is None, "no range is shown then"


def test_a_card_that_would_reach_the_face_is_drawn_smaller_toward_its_top() -> None:
    card = _process()
    top, bottom = (edge * H for edge in element_band(card, height=H, margins=MARGINS))
    clear = face_clear_line(_edl(0.30), 4, 8, H)
    assert top < clear < bottom, "the fixture is a card that overlaps the head"

    scale, origin = fit_to_face(card, _edl(0.30), height=H, margins=MARGINS)

    assert origin == pytest.approx(top, abs=0.1)
    assert MIN_FIT_SCALE <= scale < 1.0
    assert top + (bottom - top) * scale == pytest.approx(clear, abs=1.0)


def test_a_card_that_already_clears_the_head_is_left_alone() -> None:
    assert fit_to_face(_process(), _edl(0.45), height=H, margins=MARGINS) is None
    assert fit_to_face(_process(), _edl(None), height=H, margins=MARGINS) is None
    assert fit_to_face(_process(), None, height=H, margins=MARGINS) is None
    centred = MotionElement(type="strike", start=4, end=8, text="Stare", replacement="Nowe",
                            reason="Zamiana.", position="center")  # fmt: skip
    assert fit_to_face(centred, _edl(0.30), height=H, margins=MARGINS) is None
    label = MotionElement(type="label", start=4, end=8, text="Scena", reason="Scena.")
    assert fit_to_face(label, _edl(0.30), height=H, margins=MARGINS) is None


def test_a_card_is_never_shrunk_past_what_stays_readable() -> None:
    scale, _origin = fit_to_face(_process(), _edl(0.24, face=0.3), height=H, margins=MARGINS)

    assert scale == MIN_FIT_SCALE
    # A face so high that the card starts inside it is not helped by shrinking.
    assert fit_to_face(_process(), _edl(0.16, face=0.3), height=H, margins=MARGINS) is None


def test_the_compositor_is_told_the_fit_and_qa_measures_the_card_as_drawn() -> None:
    from social_video.qa.motion import _Placement

    card = _process()
    plan = MotionPlan(rationale="Karta nad głową.", elements=[card])
    edl = _edl(0.30)

    fitted = _element_payload(card, plan, {}, height=H, margins=MARGINS, edl=edl)
    plain = _element_payload(card, plan, {}, height=H, margins=MARGINS)

    assert fitted["fit"]["scale"] < 1.0 and fitted["fit"]["origin_y"] > 0
    assert plain["fit"] is None
    drawn = _Placement(margins=MARGINS, height=H, edl=edl).band(card)
    whole = _Placement(margins=MARGINS, height=H).band(card)
    assert drawn[0] == whole[0] and drawn[1] < whole[1]
    assert drawn[1] * H == pytest.approx(face_clear_line(edl, 4, 8, H), abs=1.0)
