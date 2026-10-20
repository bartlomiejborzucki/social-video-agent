"""Stickers and shakes: anchored to a word, inside the brand's rules."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from social_video.edl.render import ShakeWindow, shake_graph
from social_video.motion.stickers import anchor_to_words, sticker_problems
from social_video.qa.motion import check_motion
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import MotionElement, MotionElementType, MotionPlan, Shake

SHOCK = "\U0001f633"


def _sticker(**fields) -> MotionElement:
    values = {"start": 7.0, "end": 8.0, "emoji": SHOCK, "reason": "Shock at the promise."}
    values.update(fields)
    return MotionElement(type=MotionElementType.STICKER, **values)


def _track() -> CaptionTrack:
    words = [("Przecież", 6.2, 6.6), ("się", 6.6, 6.75), ("dogadaliśmy,", 6.75, 7.4),
             ("Zgodziłeś!", 7.52, 8.3), ("Zgodziłeś", 9.0, 9.5)]  # fmt: skip
    cue = CaptionCue(
        index=1, start=6.2, end=9.5, text=" ".join(w for w, _s, _e in words),
        words=[CaptionWord(text=w, start=s, end=e) for w, s, e in words],
    )  # fmt: skip
    return CaptionTrack(cues=[cue])


def test_a_sticker_is_one_emoji_or_one_image_for_a_moment_after_the_opening() -> None:
    _sticker()
    with pytest.raises(ValidationError, match="one emoji or one image_asset"):
        _sticker(emoji=None)
    with pytest.raises(ValidationError, match=r"0\.6-1\.5 s"):
        _sticker(end=9.0)
    with pytest.raises(ValidationError, match="opening frame"):
        _sticker(start=0.0, end=1.0)
    with pytest.raises(ValidationError, match="wholly inside the frame"):
        _sticker(x_pct=0.99)
    with pytest.raises(ValidationError, match="only used by a sticker"):
        MotionElement(type="cta", start=1, end=3, text="Zapisz", emoji=SHOCK, reason="r")


def test_stickers_and_shakes_land_on_their_word_and_occurrence() -> None:
    plan = MotionPlan(
        rationale="r",
        elements=[_sticker(start=1.0, end=1.8, at_word="zgodziłeś")],
        shakes=[Shake(start=0.0, end=0.4, at_word="Zgodziłeś!", occurrence=2, reason="r")],
    )
    anchored, notes = anchor_to_words(plan, _track())
    sticker = anchored.elements[0]
    assert (sticker.start, sticker.end) == pytest.approx((7.52, 8.32))
    assert (anchored.shakes[0].start, anchored.shakes[0].end) == pytest.approx((9.0, 9.4))
    assert len(notes) == 2
    with pytest.raises(ValueError, match="occurrence 3 does not exist"):
        anchor_to_words(
            MotionPlan(rationale="r", elements=[_sticker(at_word="Zgodziłeś", occurrence=3)]),
            _track(),
        )


def test_the_brand_limits_stickers_by_energy_allowlist_and_cards() -> None:
    card = MotionElement(type="end_card", start=7.5, end=9.5, text="Książka", reason="r")
    plan = MotionPlan(rationale="r", elements=[_sticker(), _sticker(start=10, end=11), card])
    assert sticker_problems(plan, energy="bold", allowlist=[SHOCK]) == [
        "sticker at 7.00s overlaps a full-frame card"
    ]
    calm = sticker_problems(plan, energy="calm", allowlist=[])
    assert any("calm allows 0" in p for p in calm)
    assert any("not in sticker_allowlist" in p for p in calm)
    three = MotionPlan(rationale="r", elements=[_sticker(start=t, end=t + 1) for t in (2, 4, 6)])
    assert any("bold allows 2" in p for p in sticker_problems(three, energy="bold",
                                                              allowlist=[SHOCK]))  # fmt: skip


def test_shake_is_drawn_only_inside_its_window() -> None:
    graph, label = shake_graph("[cvm]", [ShakeWindow(7.5, 7.9, 1.2, 9.0)], (1080, 1920))
    assert label == "[shk0]"
    assert "between(t,7.5000,7.9000)" in graph
    assert "crop=1080:1920" in graph and "setsar=1" in graph


def test_motion_qa_names_a_sticker_on_a_face_or_the_captions() -> None:
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=20)])
    on_face = MotionPlan(rationale="r", elements=[_sticker(x_pct=0.5, y_pct=0.35)])
    face = [(0.35, 0.25, 0.65, 0.5)]
    report = check_motion(edl, on_face, None, faces=lambda _t: face)
    names = {c.name: c for c in report.checks}
    assert not names["sticker at 7.00s clear of faces"].passed
    clear = MotionPlan(rationale="r", elements=[_sticker(x_pct=0.85, y_pct=0.2)])
    names = {c.name: c for c in check_motion(edl, clear, None, faces=lambda _t: face).checks}
    assert names["sticker at 7.00s clear of faces"].passed
