"""Picture effects, inserts, props and punch-ins on listed words."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError as PydanticValidationError

from social_video.errors import ValidationError
from social_video.motion.anchors import anchor_to_words
from social_video.motion.energy import effect_problems, energy_preset
from social_video.motion.props import load_props, plan_props, prop_box
from social_video.motion.suggest import Word as SpokenWord
from social_video.motion.suggest import _effects, _props, _word_punches
from social_video.pipeline import _effect_evidence, _ending_evidence
from social_video.qa.motion import _effects as effect_checks
from social_video.qa.motion import _punch_words
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import Effect, MotionElement, MotionPlan, PunchIn
from social_video.schemas.qa import QAReport


def _effect(kind: str = "frame_in_frame", start: float = 4.0, end: float = 5.2, **f) -> Effect:
    return Effect(type=kind, start=start, end=end, reason="A turn in the argument.", **f)


def _track(*words: tuple[str, float]) -> CaptionTrack:
    return CaptionTrack(
        cues=[
            CaptionCue(
                index=n, start=at, end=at + 0.4, text=text,
                words=[CaptionWord(text=text, start=at, end=at + 0.4)],
            )
            for n, (text, at) in enumerate(words, start=1)
        ]
    )  # fmt: skip


def test_effects_keep_their_lengths_and_the_opening() -> None:
    _effect("bw_flash", 3.0, 3.3)
    with pytest.raises(PydanticValidationError, match=r"0\.2-0\.4 s"):
        _effect("bw_flash", 3.0, 4.0)
    with pytest.raises(PydanticValidationError, match="opening"):
        _effect(start=0.5, end=1.5)
    assert _effect("tilt").tilt_deg == 4.0
    with pytest.raises(PydanticValidationError, match="2-5 degrees"):
        _effect("tilt", tilt_deg=1.0)
    with pytest.raises(PydanticValidationError, match="only used by a tilt"):
        _effect(tilt_deg=3.0)


def test_effects_never_overlap_or_run_under_the_hook_title() -> None:
    with pytest.raises(PydanticValidationError, match="one effect at a time"):
        MotionPlan(effects=[_effect(), _effect(start=4.5, end=5.5)], rationale="x")
    title = MotionElement(
        type="hook_title", start=0.4, end=3.4, text="Kto pierwszy ustąpi?", reason="Title."
    )
    with pytest.raises(PydanticValidationError, match="under the hook_title"):
        MotionPlan(elements=[title], effects=[_effect(start=2.0, end=3.0)], rationale="x")


def test_the_energy_budget_and_the_project_switch() -> None:
    plan = MotionPlan(
        effects=[_effect(start=2 + 6 * i, end=3 + 6 * i) for i in range(3)], rationale="x"
    )
    assert effect_problems(plan, energy="lively", duration=30.0) != []
    assert effect_problems(plan, energy="bold", duration=30.0) == []
    assert effect_problems(plan, energy="calm", duration=30.0) != []
    assert (
        "motion_effects: off"
        in effect_problems(plan, energy="bold", duration=30.0, policy="off")[0]
    )


def test_effects_are_anchored_and_recorded() -> None:
    plan = MotionPlan(
        effects=[_effect("halftone_bg", at_word="nagle")],
        punch_ins=[PunchIn(start=1, end=2, scale=1.1, at_word="ważne", reason="x")],
        rationale="x",
    )
    placed, notes = anchor_to_words(plan, _track(("ważne", 2.5), ("nagle", 6.0)))
    assert placed.effects[0].start == 6.0 and placed.punch_ins[0].start == 2.5
    assert len(notes) == 2
    assert _effect_evidence(placed) == [
        {"type": "halftone_bg", "start": 6.0, "end": 7.2, "mask": "none"}
    ]


def test_motion_qa_spaces_effects_and_warns_on_a_sensitive_reel() -> None:
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=30)])
    plan = MotionPlan(
        effects=[_effect("tear", 4.0, 4.8), _effect("bw_flash", 6.0, 6.3)],
        sensitive_topic=True,
        rationale="x",
    )
    report = QAReport(output="x", edl="main")
    effect_checks(report, edl, plan, _track(("Koniec.", 3.6)), energy_preset("bold"))
    failed = {c.name for c in report.checks if not c.passed}
    assert any("spaced" in name for name in failed)
    assert any("sensitive topic" in name for name in failed)
    assert any("sentence boundary" in name and "bw_flash" in name for name in failed)
    assert not any("sentence boundary" in name and "tear" in name for name in failed)


def test_a_listed_word_said_without_a_push_is_noted() -> None:
    plan = MotionPlan(
        punch_ins=[PunchIn(start=2.45, end=3.3, scale=1.12, reason="x")], rationale="x"
    )
    report = QAReport(output="x", edl="main")
    _punch_words(
        report, plan, _track(("Ważne:", 2.5), ("zapamiętaj", 8.0)), ["ważne", "zapamiętaj"]
    )
    results = {c.name: c.passed for c in report.checks}
    assert results["'ważne' at 2.50s marked"] is True
    assert results["'zapamiętaj' at 8.00s marked"] is False


def _words(*items: tuple[str, float]) -> list[SpokenWord]:
    return [SpokenWord(text, at, at + 0.3) for text, at in items]


def test_suggest_proposes_effects_on_sentences_within_budget() -> None:
    sentences = [_words((f"Zdanie{i}.", 3.0 * i)) for i in range(10)]
    found = _effects(sentences, energy_preset("lively"), 30.0, after=3.4)
    starts = [c.effect.start for c in found]
    assert starts and starts[0] >= 3.4
    assert len(found) <= 2
    assert all(b - a >= 6.0 for a, b in pairwise(starts))
    assert _effects(sentences, energy_preset("calm"), 30.0) == []
    loud = {c.effect.type.value for c in _effects(sentences, energy_preset("bold"), 30.0)}
    quiet = {
        c.effect.type.value
        for c in _effects(sentences, energy_preset("bold"), 30.0, sensitive=True)
    }
    assert "speed_lines" in loud and quiet <= {"frame_in_frame", "triptych", "tilt"}


def test_suggest_pushes_in_on_listed_words() -> None:
    found = _word_punches(
        _words(("Ważne!", 2.0), ("kubek", 3.0)), ["ważne"], energy_preset("lively"), 20.0
    )
    assert len(found) == 1
    assert found[0].punch_in.at_word == "Ważne" and found[0].punch_in.scale <= 1.18


def _library(tmp_path: Path, rights: str = "own photo", child: bool = False) -> Path:
    directory = tmp_path / "assets" / "props"
    directory.mkdir(parents=True)
    Image.new("RGB", (400, 600), "white").save(directory / "okladka.png")
    quoted = rights or "''"
    (directory / "props.yaml").write_text(
        "props:\n  - id: okladka\n    file: okladka.png\n    keywords: [poradnik]\n"
        f"    rights: {quoted}\n    child_face_visible: {str(child).lower()}\n",
        encoding="utf-8",
    )
    return directory


def _prop(**fields) -> MotionElement:
    return MotionElement(
        **{"type": "prop", "start": 3, "end": 5.5, "prop": "okladka", "reason": "x", **fields}
    )


def test_a_prop_comes_from_the_library_with_its_rights(tmp_path: Path) -> None:
    directory = _library(tmp_path)
    plan = MotionPlan(elements=[_prop()], rationale="x")
    files, evidence = plan_props(plan, directory)
    assert files["okladka"].name == "okladka.png"
    assert evidence[0]["rights"] == "own photo" and len(evidence[0]["sha256"]) == 64
    left, top, right, bottom = prop_box(_prop(), files["okladka"])
    assert 0 < left < right < 1 and 0 < top < bottom < 1
    missing = MotionPlan(elements=[_prop(prop="zegar")], rationale="x")
    with pytest.raises(ValidationError, match="not in the library"):
        plan_props(missing, directory)


@pytest.mark.parametrize(("rights", "child", "match"), [("", False, "no rights"),
                                                        ("own", True, "child")])  # fmt: skip
def test_a_prop_without_rights_or_with_a_child_is_refused(
    tmp_path: Path, rights: str, child: bool, match: str
) -> None:
    directory = _library(tmp_path, rights=rights, child=child)
    with pytest.raises(ValidationError, match=match):
        plan_props(MotionPlan(elements=[_prop()], rationale="x"), directory)


def test_suggest_finds_a_prop_by_its_keywords(tmp_path: Path) -> None:
    library = load_props(_library(tmp_path))
    found = _props(_words(("poradnika", 4.0)), library, 20.0)
    assert len(found) == 1 and found[0].element.prop == "okladka"


def test_an_insert_is_a_short_second_shot_with_rights() -> None:
    insert = MotionElement(
        type="insert", start=4, end=5.5, video_asset="ksiazka.mp4", rights="own footage",
        cut_style="whoosh", at_word="książka", reason="The book, shown.",
    )  # fmt: skip
    assert insert.cut_style is not None
    with pytest.raises(PydanticValidationError, match="rights"):
        MotionElement(type="insert", start=4, end=5, video_asset="k.mp4", reason="x")
    with pytest.raises(PydanticValidationError, match=r"0\.5-2\.5 s"):
        MotionElement(type="insert", start=4, end=8, video_asset="k.mp4", rights="own", reason="x")
    with pytest.raises(PydanticValidationError, match="opening"):
        MotionElement(
            type="insert", start=0.4, end=1.4, video_asset="k.mp4", rights="own", reason="x"
        )


def test_the_ending_evidence_names_what_closes_the_reel() -> None:
    teaser = MotionElement(type="end_teaser", start=16, end=20, text="Jutro dalej", reason="Next.")
    plan = MotionPlan(elements=[teaser], rationale="x")
    assert _ending_evidence(plan, 20.0)["overlay"] is True
    assert _ending_evidence(MotionPlan(rationale="x"), 20.0) == {
        "overlay": False, "end_card": False, "cta": False, "window_s": 3.0
    }  # fmt: skip


def test_accept_skips_an_effect_under_the_hook_title() -> None:
    from social_video.motion.suggest import accept_accents
    from social_video.schemas.motion import AccentCandidate, AccentCandidateSet

    title = MotionElement(
        type="hook_title", start=0.4, end=3.0, text="Kto pierwszy ustąpi?", reason="Title."
    )
    plan = MotionPlan(elements=[title], rationale="x")
    found = AccentCandidateSet(
        edl="main",
        energy="bold",
        candidates=[
            AccentCandidate(id="acc-001", kind="effect", confidence="high", at=1.4,
                            reason="x", effect=_effect(start=1.4, end=2.6)),
            AccentCandidate(id="acc-002", kind="effect", confidence="high", at=8.0,
                            reason="x", effect=_effect(start=8.0, end=9.2)),
        ],
    )  # fmt: skip
    updated, skipped = accept_accents(plan, found, ["acc-001", "acc-002"])
    assert [e.start for e in updated.effects] == [8.0]
    assert skipped and "hook_title" in skipped[0]
