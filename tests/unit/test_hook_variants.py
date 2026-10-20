"""Three opening lines from the brief, and a short head of the edit to test them."""

from __future__ import annotations

import pytest

from social_video.editorial.brief import parse_brief_text
from social_video.motion.hook_variants import head_of, variants_from_brief, with_first_caption
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import MotionElement, MotionPlan, PunchIn

BRIEF = (
    "Scenariusz:\n- 0-4 s | Pokój | Dziecko miało posprzątać pokój, np. przed "
    "kolacją. A teraz… słychać: „Nie chcę!” | Zgodziło się. A teraz nie chce.\n"
)


def test_the_brief_gives_on_screen_text_a_sentence_and_a_question() -> None:
    found = variants_from_brief(parse_brief_text(BRIEF))
    assert [p.name for p in found] == ["napis", "zdanie", "pytanie"]
    assert found[0].text == "Zgodziło się. A teraz nie chce."
    assert found[1].text.startswith("Dziecko miało posprzątać pokój")
    assert found[2].text == "Co zrobisz, gdy dziecko miało posprzątać pokój?"


def test_a_variant_replaces_only_the_first_caption() -> None:
    track = CaptionTrack(
        cues=[
            CaptionCue(index=1, start=0.0, end=2.0, text="stare",
                       words=[CaptionWord(text="stare", start=0.0, end=2.0)]),
            CaptionCue(index=2, start=2.0, end=3.0, text="dalej"),
        ]
    )  # fmt: skip
    variant = with_first_caption(track, "Zgodziło się. A teraz nie chce.")
    assert variant.cues[0].text == "Zgodziło się. A teraz nie chce."
    assert [w.text for w in variant.cues[0].words][-1] == "chce."
    assert variant.cues[0].words[-1].end == pytest.approx(2.0)
    assert variant.cues[1].text == "dalej"


def test_the_head_keeps_four_seconds_of_edit_and_plan() -> None:
    edl = EDL(
        ranges=[
            EDLRange(source="plac", start=0.0, end=5.1, speed=0.85, audio_source="glos",
                     audio_start=16.7, audio_end=22.7),
            EDLRange(source="kamera", start=100, end=110),
        ],
        end_hold=2.0,
    )  # fmt: skip
    plan = MotionPlan(
        rationale="r",
        elements=[MotionElement(type="label", start=0, end=7.5, text="Zgodziło się", reason="r")],
        punch_ins=[PunchIn(start=2.0, end=4.6, scale=1.08, reason="r"),
                   PunchIn(start=5.0, end=6.0, scale=1.08, reason="r")],
    )  # fmt: skip
    head, head_plan = head_of(edl, plan, 4.0)
    assert head.total_duration == pytest.approx(4.0)
    assert head.ranges[0].audio_end == pytest.approx(20.7)
    assert head_plan is not None
    assert head_plan.elements[0].end == pytest.approx(4.0)
    assert [p.start for p in head_plan.punch_ins] == [2.0]
