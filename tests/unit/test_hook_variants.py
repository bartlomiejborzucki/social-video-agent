"""Opening variants along one axis, and a short head of the edit to preview them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from social_video.editorial.brief import parse_brief_text
from social_video.errors import ValidationError
from social_video.motion.hook_variants import (
    VariantAxis,
    drop_first_scene_labels,
    first_shot_edl,
    head_of,
    load_variant_set,
    opening_text_end,
    parse_shot,
    shift_plan,
    variants_from_brief,
    verbatim_first_caption,
    with_opening_text,
)
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord
from social_video.schemas.edl import EDL, EDLRange, SoundEffect
from social_video.schemas.motion import MotionElement, MotionElementType, MotionPlan, PunchIn
from social_video.schemas.transcript import Transcript, TranscriptToken
from social_video.transcribe.normalize import synthesize_spacing

BRIEF = (
    "Scenariusz:\n- 0-4 s | Kuchnia | Kawa miała być gotowa przed wyjściem. A teraz… "
    "słychać: „Nie ma mleka!” | Plan był prosty. A teraz nie jest.\n"
)


def _track() -> CaptionTrack:
    words = [
        CaptionWord(text=t, start=0.4 * i, end=0.4 * i + 0.35)
        for i, t in enumerate(["Kawa", "miała", "być", "gotowa."])
    ]
    return CaptionTrack(
        cues=[
            CaptionCue(index=1, start=0.0, end=1.6, text="Kawa miała być gotowa.", words=words),
            CaptionCue(index=2, start=1.6, end=3.0, text="dalej"),
        ]
    )


def test_the_brief_gives_two_lines_and_no_invented_question() -> None:
    found = variants_from_brief(parse_brief_text(BRIEF))
    assert found == ["Plan był prosty. A teraz nie jest.", "Kawa miała być gotowa przed wyjściem."]


def test_a_line_that_is_said_may_become_the_first_caption() -> None:
    track = _track()
    assert verbatim_first_caption(track, "kawa miała być gotowa") is track
    shorter = verbatim_first_caption(track, "być gotowa")
    assert shorter is not None
    assert shorter.cues[0].text == "być gotowa."
    assert shorter.cues[0].start == 0.0  # the first caption still opens the video
    assert shorter.cues[0].words[0].start == pytest.approx(0.8)  # real timings kept
    assert shorter.cues[1].text == "dalej"


def test_a_line_that_is_not_said_is_never_a_caption() -> None:
    assert verbatim_first_caption(_track(), "Plan był prosty.") is None


def test_an_unsaid_line_becomes_on_screen_text() -> None:
    plan = MotionPlan(rationale="r")
    end = opening_text_end(_track())
    first, _ = with_opening_text(plan, "Plan był prosty.", end=end)
    again, before = with_opening_text(first, "Inny plan.", end=end)
    labels = [e for e in again.elements if e.type is MotionElementType.LABEL]
    assert [label.text for label in labels] == ["Inny plan."]
    assert labels[0].start == 0.0
    assert labels[0].end == 2.0
    assert before == ""


def test_the_scene_label_gives_way_to_the_opening_line() -> None:
    plan = MotionPlan(
        rationale="r",
        elements=[
            MotionElement(type="label", start=0.0, end=4.0, text="Kuchnia", reason="r"),
            MotionElement(type="label", start=4.0, end=6.0, text="Wyjście", reason="r"),
        ],
    )
    varied, before = with_opening_text(plan, "Plan był prosty.", end=2.0)
    assert before == "Kuchnia"
    shown = [(e.text, e.start, e.end) for e in varied.elements]
    assert shown == [
        ("Plan był prosty.", 0.0, 2.0), ("Kuchnia", 2.0, 4.0), ("Wyjście", 4.0, 6.0)
    ]  # fmt: skip
    short, _ = with_opening_text(plan, "Plan był prosty.", end=3.6)
    assert [e.text for e in short.elements] == ["Plan był prosty.", "Wyjście"]


def test_shots_parse_and_bad_ones_are_refused() -> None:
    assert parse_shot("kamera:12.5-15") == ("kamera", 12.5, 15.0)
    with pytest.raises(ValidationError):
        parse_shot("kamera:15-12")
    with pytest.raises(ValidationError):
        parse_shot("kamera")


def _transcript() -> Transcript:
    texts = ["Najpierw", "kawa.", "Potem", "wyjście", "z", "domu."]
    words = [
        TranscriptToken(text=t, start=10.0 + i * 0.5, end=10.0 + i * 0.5 + 0.4)
        for i, t in enumerate(texts)
    ]
    return Transcript(
        source_id="kamera", source_fingerprint="f" * 16, duration=30.0, provider="fake",
        tokens=synthesize_spacing(words),
    )  # fmt: skip


def test_a_first_shot_variant_changes_only_the_first_range() -> None:
    edl = EDL(
        ranges=[
            EDLRange(source="kamera", start=0.0, end=4.0, quote="stare", zoom=1.1),
            EDLRange(source="kamera", start=20.0, end=24.0),
            EDLRange(source="kamera", start=25.0, end=28.0),
        ]
    )
    variant, warnings = first_shot_edl(edl, "kamera", 11.0, 12.9, _transcript(), "b")
    assert variant.name == "main-b"
    assert variant.ranges[1:] == edl.ranges[1:]
    assert variant.ranges[0].quote == "Potem wyjście z domu."
    assert variant.ranges[0].zoom == 1.1  # same source: its framing is kept
    assert warnings == []
    _, warned = first_shot_edl(edl, "kamera", 11.5, 12.9, _transcript(), "c")
    assert any("starts mid-sentence" in w for w in warned)
    _, cut_short = first_shot_edl(edl, "kamera", 11.0, 11.9, _transcript(), "d")
    assert any("ends mid-sentence" in w and "kamera:10.92-12.90" in w for w in cut_short)


def test_a_first_shot_variant_moves_the_sound_effects_with_it() -> None:
    edl = EDL(
        ranges=[EDLRange(source="kamera", start=0.0, end=4.0),
                EDLRange(source="kamera", start=20.0, end=24.0)],
        sound_effects=[
            SoundEffect(path="a.wav", at=1.0, reason="r"),
            SoundEffect(path="b.wav", at=3.5, reason="r"),
            SoundEffect(path="c.wav", at=6.0, reason="r"),
        ],
    )  # fmt: skip
    variant, warnings = first_shot_edl(edl, "kamera", 11.0, 12.9, _transcript(), "b")
    moved = round(2.0 + variant.ranges[0].output_duration, 4)
    assert [(e.path, e.at) for e in variant.sound_effects] == [("a.wav", 1.0), ("c.wav", moved)]
    assert any("3.50s fell past" in w for w in warnings)


def test_labels_of_the_replaced_first_shot_are_left_off() -> None:
    plan = MotionPlan(
        rationale="r",
        elements=[
            MotionElement(type="label", start=0.0, end=4.0, text="Kuchnia", reason="r"),
            MotionElement(type="label", start=0.0, end=8.0, text="Rano", reason="r"),
            MotionElement(type="label", start=5.0, end=6.0, text="Dalej", reason="r"),
        ],
    )
    kept, gone = drop_first_scene_labels(plan, old_first=4.0, new_first=2.0)
    assert gone == ["Kuchnia", "Rano"]
    assert [(e.text, e.start) for e in kept.elements] == [("Rano", 4.0), ("Dalej", 5.0)]


def test_the_plan_moves_with_the_first_range() -> None:
    plan = MotionPlan(
        rationale="r",
        elements=[
            MotionElement(type="label", start=0.0, end=3.0, text="a", reason="r"),
            MotionElement(type="label", start=5.0, end=6.0, text="b", reason="r"),
            MotionElement(type="callout", start=1.0, end=7.0, text="c", reason="r"),
        ],
    )
    moved = shift_plan(plan, old_first=4.0, new_first=2.0)
    assert [(e.start, e.end) for e in moved.elements] == [(0.0, 2.0), (3.0, 4.0), (1.0, 5.0)]


def test_a_2_6_record_reads_as_a_text_set(tmp_path: Path) -> None:
    path = tmp_path / "hook-variants.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "variants": [
                    {"name": "x", "text": "t", "file": "p.mp4", "seconds": 4.0},
                    {"name": "y", "text": "u", "file": "f.mp4"},
                ],
            }
        ),
        encoding="utf-8",
    )
    found = load_variant_set(path)
    assert found is not None
    assert found.axis is VariantAxis.TEXT
    assert found.variants[0].preview == "p.mp4"
    assert found.variants[1].full == "f.mp4"


def test_the_head_keeps_four_seconds_of_edit_and_plan() -> None:
    edl = EDL(
        ranges=[
            EDLRange(source="plac", start=0.0, end=5.1, speed=0.85, audio_source="glos",
                     audio_start=16.7, audio_end=22.7),
            EDLRange(source="kamera", start=100, end=110),
        ],
        end_hold=2.0,
        sound_effects=[SoundEffect(path="a.wav", at=1.0, reason="r"),
                       SoundEffect(path="b.wav", at=8.0, reason="r")],
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
    assert [e.path for e in head.sound_effects] == ["a.wav"]
    assert head_plan is not None
    assert head_plan.elements[0].end == pytest.approx(4.0)
    assert [p.start for p in head_plan.punch_ins] == [2.0]


@pytest.mark.parametrize(
    ("request_args", "message"),
    [
        ({"texts": ["A"], "first_shots": ["k:1-2"]}, "a set varies one thing"),
        ({"axis": VariantAxis.TEXT, "pickups": ["x"]}, "belong to the first_shot axis"),
        ({"axis": VariantAxis.FIRST_SHOT, "texts": ["A"]}, "belong to the text axis"),
        ({"texts": ["A", "B"], "hypotheses": ["one"]}, "give one per variant"),
        ({"axis": VariantAxis.PACING}, "not built yet"),
        ({"only": ["a"]}, "no variants recorded yet"),
        ({}, "give --text lines or --from-brief"),
    ],
)
def test_variant_requests_that_do_not_hold_together_are_refused(
    tmp_path: Path, request_args: dict, message: str
) -> None:
    from social_video.motion.variant_service import VariantRequest, _proposals
    from social_video.workspace.layout import Workspace

    with pytest.raises(ValidationError, match=message):
        _proposals(Workspace.at(tmp_path), VariantRequest(**request_args), None)


def test_variants_are_named_in_order_with_their_hypotheses(tmp_path: Path) -> None:
    from social_video.motion.variant_service import VariantRequest, _proposals
    from social_video.workspace.layout import Workspace

    axis, found = _proposals(
        Workspace.at(tmp_path),
        VariantRequest(first_shots=["k:1-2"], pickups=["a close-up"], hypotheses=["x", "y"]),
        None,
    )
    assert axis is VariantAxis.FIRST_SHOT
    assert [(p.name, p.first_shot, p.pickup, h) for p, h in found] == [
        ("a", "k:1-2", None, "x"),
        ("b", None, "a close-up", "y"),
    ]
