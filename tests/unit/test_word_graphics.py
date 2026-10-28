"""Word graphics: their schemas and limits, their words, their place on the frame."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from social_video.motion.anchors import anchor_to_words
from social_video.motion.layout import element_band
from social_video.motion.sfx import sync_sfx
from social_video.qa.motion import check_motion
from social_video.remotion import _element_payload
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import MotionElement, MotionElementType, MotionPlan

#: Invented lines: a habit, then what to say instead.
SPOKEN = [("Nie", 1.0, 1.2), ("płacz!", 1.2, 1.7), ("Zamiast", 3.0, 3.4), ("tego", 3.4, 3.6),
          ("powiedz:", 3.6, 4.1), ("widzę,", 4.4, 4.8), ("że", 4.8, 4.9), ("ci", 4.9, 5.0),
          ("smutno.", 5.0, 5.6)]  # fmt: skip


def _track(shift: float = 0.0) -> CaptionTrack:
    words = [CaptionWord(text=w, start=s + shift, end=e + shift) for w, s, e in SPOKEN]
    return CaptionTrack(
        cues=[
            CaptionCue(index=1, start=words[0].start, end=words[-1].end,
                       text=" ".join(w.text for w in words), words=words)
        ]
    )  # fmt: skip


def _strike(**fields) -> MotionElement:
    values = {"start": 1.0, "end": 6.5, "text": "Nie płacz!", "replacement": "Widzę, że ci smutno.",
              "reason": "The habit, crossed out."}  # fmt: skip
    values.update(fields)
    return MotionElement(type=MotionElementType.STRIKE, **values)


def test_a_strike_crosses_out_a_short_line_and_replaces_it() -> None:
    strike = _strike()
    assert strike.placement is not None and strike.placement.value == "top"
    assert strike.strike_moments == (pytest.approx(2.2), pytest.approx(2.9))
    with pytest.raises(ValidationError, match="replacement of at most 40"):
        _strike(replacement=None)
    with pytest.raises(ValidationError, match="at most 40"):
        _strike(text="To zdanie jest zdecydowanie za długie na przekreślenie")
    with pytest.raises(ValidationError, match=r"1\.5-10 s"):
        _strike(end=2.0)
    with pytest.raises(ValidationError, match="opening frame"):
        _strike(start=0.0)
    with pytest.raises(ValidationError, match="while it is on screen"):
        _strike(strike_at=5.0, replace_at=4.0)
    with pytest.raises(ValidationError, match="only used by a strike"):
        MotionElement(type="callout", start=1, end=3, text="Pytanie?", replacement="x",
                      reason="r")  # fmt: skip
    with pytest.raises(ValidationError, match="not a callout"):
        MotionElement(type="callout", start=1, end=3, text="Pytanie?", at_word="Nie",
                      reason="r")  # fmt: skip
    _strike(position="center", strike_mark="scissors")
    with pytest.raises(ValidationError, match="accepts position: top, center"):
        _strike(position="above_captions")


def test_the_stroke_and_the_replacement_land_on_their_words() -> None:
    plan = MotionPlan(
        rationale="r",
        elements=[_strike(start=5.0, end=9.0, at_word="zamiast", replace_at_word="widzę,")],
    )
    anchored, notes = anchor_to_words(plan, _track())

    strike = anchored.elements[0]
    # The word fell outside the strike: it opens STRIKE_LEAD_S before it.
    assert (strike.start, strike.strike_at, strike.replace_at) == pytest.approx((1.8, 3.0, 4.4))
    assert strike.end == pytest.approx(1.8 + 4.0)
    assert notes[:2] == [
        "strike on 'zamiast' crosses out at 3.00s",
        "strike replaced on 'widzę,' at 4.40s",
    ]
    # A word inside the strike keeps its start.
    inside = MotionPlan(rationale="r", elements=[_strike(start=0.5, end=6.0, at_word="zamiast")])
    assert anchor_to_words(inside, _track())[0].elements[0].start == pytest.approx(0.5)
    # A later recompile carries the whole strike with its words.
    moved, _ = anchor_to_words(anchored, _track(shift=0.5))
    again = moved.elements[0]
    assert (again.start, again.strike_at, again.replace_at) == pytest.approx((2.3, 3.5, 4.9))


def test_a_sensitive_reel_takes_no_playful_graphics() -> None:
    with pytest.raises(ValidationError, match="no playful graphics; remove strike"):
        MotionPlan(rationale="r", sensitive_topic=True, elements=[_strike()])
    calm = MotionElement(type="list", start=1, end=4, items=["Oddech", "Cisza"],
                         item_times=[1.5, 2.5], reason="r")  # fmt: skip
    MotionPlan(rationale="r", sensitive_topic=True, elements=[calm])


def test_a_strike_sits_at_the_top_by_default_and_is_measured_there() -> None:
    top, bottom = element_band(_strike(), height=1920, margins={"top": 10})
    assert 0.1 < top < bottom < 0.25
    middle = element_band(_strike(position="center"), height=1920, margins={})
    assert middle[0] < 0.5 < middle[1]
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=8)])
    report = check_motion(edl, MotionPlan(rationale="r", elements=[_strike()]), None)
    readable = next(c for c in report.checks if c.name == "strike at 1.00s readable")
    # Both lines count: 10 + 20 characters at 15 per second, plus a glance.
    assert readable.expected == pytest.approx(0.6 + 30 / 15)


def test_the_compositor_and_the_sound_get_the_stroke_moment(tmp_path) -> None:
    strike = _strike(strike_at=2.0)
    payload = _element_payload(strike, MotionPlan(rationale="r"), {})
    assert (payload["strike_at"], payload["replace_at"]) == pytest.approx((2.0, 2.7))
    (tmp_path / "pop.wav").write_bytes(b"RIFF")
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=8)])
    _updated, added = sync_sfx(edl, MotionPlan(rationale="r", elements=[strike]), tmp_path)
    assert [effect.at for effect in added] == [1.0, 2.0]
