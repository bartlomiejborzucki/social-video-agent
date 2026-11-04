"""The hook title and the end teaser: overlays over the speaker, never cards."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from social_video.motion.anchors import anchor_to_words
from social_video.motion.layout import element_band
from social_video.qa.hook import announced_list, check_title
from social_video.qa.opening import OPENING_CARDS, opening_warnings, refuse_card_openings
from social_video.remotion import title_payload
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord
from social_video.schemas.config import OpeningPolicy
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import MotionElement, MotionElementType, MotionPlan


def _title(**fields) -> MotionElement:
    values = {
        "type": "hook_title",
        "start": 0.4,
        "end": 3.4,
        "text": "Czy to już za późno?",
        "reason": "The question the reel answers.",
    }
    return MotionElement(**{**values, **fields})


def _teaser(**fields) -> MotionElement:
    values = {"type": "end_teaser", "text": "Jutro: co zrobić zamiast", "reason": "Next part."}
    return MotionElement(**{**values, **fields})


def test_a_hook_title_is_short_and_early() -> None:
    title = _title(secondary_text="część 1.", emphasis_words=["późno"])
    assert title.placement is not None and title.placement.value == "top"
    with pytest.raises(PydanticValidationError, match="8 words"):
        _title(text="To jest zdecydowanie za długi tytuł na jedną krótką rolkę")
    with pytest.raises(PydanticValidationError, match="frame 0 stays the scene"):
        _title(start=0.0, end=3.0)
    with pytest.raises(PydanticValidationError, match="frame 0 stays the scene"):
        _title(start=2.5, end=5.0)
    with pytest.raises(PydanticValidationError, match="2-4 s"):
        _title(end=1.4)
    with pytest.raises(PydanticValidationError, match="not in the hook_title"):
        _title(emphasis_words=["jutro"])


def test_title_fields_belong_to_titles() -> None:
    with pytest.raises(PydanticValidationError, match="only used by a hook_title"):
        MotionElement(type="callout", start=1, end=3, text="Uwaga", title_style="pill", reason="x")
    with pytest.raises(PydanticValidationError, match="from_end"):
        _title(from_end=3.0)


def test_one_title_and_one_teaser_per_reel() -> None:
    with pytest.raises(PydanticValidationError, match="one hook_title"):
        MotionPlan(elements=[_title(), _title()], rationale="x")
    MotionPlan(elements=[_title(), _teaser()], rationale="x")


def test_a_hook_title_is_not_a_card_at_the_opening() -> None:
    assert MotionElementType.HOOK_TITLE not in OPENING_CARDS
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=10)])
    plan = MotionPlan(elements=[_title()], rationale="x")
    refuse_card_openings(edl, plan, OpeningPolicy())


def test_a_late_title_and_late_speech_are_worth_a_look() -> None:
    cue = CaptionCue(
        index=1, start=0.0, end=1.5, text="Mleko się skończyło",
        words=[CaptionWord(text="Mleko", start=0.7, end=1.0)],
    )  # fmt: skip
    late = MotionPlan(elements=[_title(start=1.4, end=4.4)], rationale="x")
    found = opening_warnings(late, [cue])
    assert any("first word is at 0.70s" in item for item in found)
    assert any("hook_title enters at 1.40s" in item for item in found)
    on_time = MotionPlan(elements=[_title()], rationale="x")
    early = cue.model_copy(update={"words": [CaptionWord(text="Mleko", start=0.1, end=0.4)]})
    assert opening_warnings(on_time, [early]) == []


def test_the_end_teaser_covers_the_last_seconds_before_held_cards() -> None:
    card = MotionElement(
        type="end_card", start=20, end=22, text="Koniec", hold=True, reason="Card."
    )
    plan = MotionPlan(elements=[_teaser(from_end=3.0), card], rationale="x")
    placed, notes = anchor_to_words(plan, None, duration=22.0)
    teaser = next(e for e in placed.elements if e.type is MotionElementType.END_TEASER)
    assert (teaser.start, teaser.end) == (17.0, 20.0)
    assert notes and "end_teaser" in notes[0]
    again, more = anchor_to_words(placed, None, duration=22.0)
    assert more == [] and again == placed


def test_the_title_is_fitted_in_capitals_on_two_lines_at_most() -> None:
    payload = title_payload(
        _title(secondary_text="część", series={"part": 2, "total": 4}),
        width=1080, height=1920, font=None,
    )  # fmt: skip
    lines = payload["fitted"]["title"]["lines"]
    assert 1 <= len(lines) <= 2
    assert " ".join(lines) == "CZY TO JUŻ ZA PÓŹNO?"
    assert payload["subtitle"] == "część 2/4"
    assert payload["entry"] == "typewriter" and payload["title_style"] == "highlight"
    assert title_payload(_teaser(), width=1080, height=1920, font=None)["entry"] == "pop"


def test_the_title_band_sits_above_the_captions() -> None:
    top, bottom = element_band(_title(), height=1920, margins={"top": 6})
    assert 0.06 < top < bottom < 0.4
    teaser_top, teaser_bottom = element_band(_teaser(), height=1920, margins={})
    assert 0.45 < teaser_top < teaser_bottom < 0.66


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("Nie odkładaj tego na jutro!", True),
        ("Kto pierwszy ustąpi?", True),
        ("3 rzeczy przed snem", True),
        ("Kawa albo herbata", True),
        ("Mój zwykły poranek", False),
    ],
)
def test_hook_check_reads_the_title(text: str, ok: bool) -> None:
    findings = check_title(text)
    assert findings[0].ok
    assert findings[1].ok is ok


def test_a_list_announced_early_is_suggested_as_a_list() -> None:
    track = CaptionTrack(
        cues=[CaptionCue(index=1, start=0.0, end=2.0, text="Zapamiętaj trzy kroki")]
    )
    found = announced_list(track)
    assert found is not None and "item_at_words" in found.fix
    late = CaptionTrack(
        cues=[CaptionCue(index=1, start=6.0, end=8.0, text="Zapamiętaj trzy kroki")]
    )
    assert announced_list(late) is None
