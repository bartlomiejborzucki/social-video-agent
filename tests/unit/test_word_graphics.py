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


def _bubble(**fields) -> MotionElement:
    values = {"start": 1.0, "end": 3.0, "text": "Jeszcze jedna bajka!",
              "reason": "The child's line, as a bubble."}  # fmt: skip
    values.update(fields)
    return MotionElement(type=MotionElementType.BUBBLE, **values)


def test_a_bubble_is_something_said_or_written_over_the_head() -> None:
    speech = _bubble(tail="left")
    assert speech.bubble_variant.value == "speech"
    assert speech.placement is not None and speech.placement.value == "top"
    message = _bubble(variant="message", secondary_text="pytanie od obserwatorki")
    payload = _element_payload(message, MotionPlan(rationale="r"), {})
    assert (payload["variant"], payload["tail"], payload["position"]) == ("message", None, "top")
    assert _element_payload(_bubble(), MotionPlan(rationale="r"), {})["tail"] == "speaker"
    with pytest.raises(ValidationError, match="at most 60 characters"):
        _bubble(text="x" * 61)
    with pytest.raises(ValidationError, match="note of at most 40"):
        _bubble(secondary_text="x" * 41)
    with pytest.raises(ValidationError, match="no tail"):
        _bubble(variant="message", tail="left")
    with pytest.raises(ValidationError, match=r"1\.2-6 s"):
        _bubble(end=9.0)
    # Never in the opening frame: the first caption carries the situation there.
    with pytest.raises(ValidationError, match="opening frame"):
        _bubble(start=0.1, end=2.0)
    with pytest.raises(ValidationError, match="accepts position: top"):
        _bubble(position="center")
    with pytest.raises(ValidationError, match="only used by a bubble"):
        _strike(variant="speech")
    with pytest.raises(ValidationError, match="remove bubble"):
        MotionPlan(rationale="r", sensitive_topic=True, elements=[_bubble()])


def test_a_bubble_pops_in_on_its_word_in_the_top_zone() -> None:
    plan = MotionPlan(rationale="r", elements=[_bubble(at_word="płacz!")])
    anchored, notes = anchor_to_words(plan, _track())
    bubble = anchored.elements[0]
    assert (bubble.start, bubble.end) == pytest.approx((1.2, 3.2))
    assert notes == ["bubble on 'płacz!' placed at 1.20s"]
    top, bottom = element_band(bubble, height=1920, margins={"top": 10})
    assert top == pytest.approx(0.1 + 10 / 1920) and bottom < 0.35


def _process(**fields) -> MotionElement:
    values = {"start": 1.0, "end": 6.0, "text": "Wieczorem",
              "items": ["kolacja", "kąpiel", "bajka", "sen"], "done_text": "gotowe do snu",
              "reason": "The evening routine, stage by stage."}  # fmt: skip
    values.update(fields)
    return MotionElement(type=MotionElementType.PROCESS, **values)


def test_a_process_is_two_to_five_short_stages_at_the_top() -> None:
    process = _process()
    assert process.placement is not None and process.placement.value == "top"
    with pytest.raises(ValidationError, match="at most 12 characters"):
        _process(items=["kolacja", "bardzo długa kąpiel"])
    with pytest.raises(ValidationError, match="2 to 5 items"):
        _process(items=["sen"])
    with pytest.raises(ValidationError, match=r"at least 2\.5 s"):
        _process(end=2.0)
    with pytest.raises(ValidationError, match="only used by a process"):
        MotionElement(type="list", start=1, end=4, items=["a", "b"], done_text="ok", reason="r")
    with pytest.raises(ValidationError, match="accepts position: top"):
        _process(position="center")
    with pytest.raises(ValidationError, match="remove process"):
        MotionPlan(rationale="r", sensitive_topic=True, elements=[_process()])
    top, bottom = element_band(process, height=1920, margins={"top": 10})
    assert 0.1 < top < bottom < 0.3


def test_each_stage_enters_on_its_word() -> None:
    plan = MotionPlan(
        rationale="r",
        elements=[_process(items=["płacz", "powiedz"], item_at_words=["płacz!", "powiedz:"])],
    )
    anchored, _notes = anchor_to_words(plan, _track())
    assert anchored.elements[0].item_times == pytest.approx([1.2, 3.6])


def test_a_kinetic_word_is_one_short_word_once_a_reel_and_never_calm() -> None:
    from social_video.motion.energy import word_graphic_problems

    word = MotionElement(type="kinetic_word", start=2.0, end=3.5, text="SPOKÓJ",
                         at_word="smutno.", reason="The key word, built.")  # fmt: skip
    with pytest.raises(ValidationError, match="one word of at most 12"):
        MotionElement(type="kinetic_word", start=2, end=3, text="dwa słowa", reason="r")
    with pytest.raises(ValidationError, match="one word of at most 12"):
        MotionElement(type="kinetic_word", start=2, end=3, text="niesamowicieee", reason="r")
    with pytest.raises(ValidationError, match=r"0\.8-2\.5 s"):
        MotionElement(type="kinetic_word", start=2, end=6, text="SPOKÓJ", reason="r")
    with pytest.raises(ValidationError, match="remove kinetic_word"):
        MotionPlan(rationale="r", sensitive_topic=True, elements=[word])
    once = MotionPlan(rationale="r", elements=[word])
    later = word.model_copy(update={"start": 4.0, "end": 5.0})
    twice = MotionPlan(rationale="r", elements=[word, later])
    assert word_graphic_problems(once, energy="bold") == []
    assert word_graphic_problems(twice, energy="bold") == [
        "2 kinetic_word(s); motion_energy bold allows 1 per reel"
    ]
    assert word_graphic_problems(once, energy="calm") == [
        "1 kinetic_word(s); motion_energy calm allows 0 per reel"
    ]
    anchored, _ = anchor_to_words(once, _track())
    assert anchored.elements[0].start == pytest.approx(5.0)
    top, bottom = element_band(word, height=1920, margins={"top": 10})
    assert 0.1 < top < bottom < 0.22
