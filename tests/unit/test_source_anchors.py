"""Times given in the recording, and scene labels from the edit's beats."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError
from typer.testing import CliRunner

from social_video.cli import app
from social_video.motion.anchors import anchor_to_sources, anchor_to_words
from social_video.motion.layout import labels_from_beats
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import (
    Effect,
    MotionElement,
    MotionPlan,
    PunchIn,
    Shake,
    SourceAnchor,
)
from social_video.workspace.layout import Workspace


def _edl() -> EDL:
    """Two recordings; the second is used twice, with eight seconds cut out of it."""
    return EDL(
        ranges=[
            EDLRange(source="wstep", start=1.0, end=4.0, beat="Wstęp"),
            EDLRange(source="rozmowa", start=10.0, end=16.0, beat="Rozwinięcie"),
            EDLRange(source="rozmowa", start=24.0, end=30.0, beat="Rozwinięcie"),
            EDLRange(source="rozmowa", start=40.0, end=42.0, beat="Na koniec"),
        ]
    )


def _label(text: str, **anchors) -> MotionElement:
    return MotionElement(type="label", start=0.0, end=2.0, text=text, reason="Scena.", **anchors)


def test_a_moment_of_a_recording_lands_where_the_edit_shows_it() -> None:
    plan = MotionPlan(
        rationale="Kotwice w nagraniu.",
        elements=[
            _label(
                "Druga część",
                at_source={"source": "rozmowa", "time": 24.0},
                until_source={"source": "rozmowa", "time": 29.5},
            ),
            MotionElement(
                type="callout", start=0.0, end=1.5, text="Uwaga", reason="Akcent.",
                at_source=SourceAnchor(source="rozmowa", time=12.0),
            ),
        ],
        punch_ins=[
            PunchIn(start=0.0, end=1.2, scale=1.1, reason="Najazd.",
                    at_source={"source": "rozmowa", "time": 14.0})
        ],
        shakes=[
            Shake(start=0.0, end=0.4, reason="Wstrząs.", at_source={"source": "wstep", "time": 2.5})
        ],
        effects=[
            Effect(type="tilt", start=2.0, end=3.0, reason="Akcent.",
                   at_source={"source": "rozmowa", "time": 41.0})
        ],
    )  # fmt: skip

    anchored, notes = anchor_to_sources(plan, _edl())

    callout, label = anchored.elements
    assert (callout.start, callout.end) == (5.0, 6.5), "its length is kept"
    assert (label.start, label.end) == (9.0, 14.5), "until_source sets the end"
    assert (anchored.punch_ins[0].start, anchored.punch_ins[0].end) == (7.0, 8.2)
    assert (anchored.shakes[0].start, anchored.shakes[0].end) == (1.5, 1.9)
    assert anchored.effects[0].start == 16.0
    assert len(notes) == 5 and "from rozmowa 24s" in " ".join(notes)
    again, quiet = anchor_to_sources(anchored, _edl())
    assert again == anchored and quiet == [], "anchoring twice changes nothing"


def test_the_same_plan_follows_the_edit_after_a_recompile() -> None:
    plan = MotionPlan(
        rationale="Po przebudowie.",
        elements=[_label("Druga część", at_source={"source": "rozmowa", "time": 25.0})],
    )
    shorter = EDL(ranges=[EDLRange(source="rozmowa", start=24.0, end=30.0)])

    assert anchor_to_sources(plan, _edl())[0].elements[0].start == 10.0
    assert anchor_to_sources(plan, shorter)[0].elements[0].start == 1.0


def test_a_moment_the_edit_cut_out_is_named_not_guessed() -> None:
    plan = MotionPlan(
        rationale="Wycięte.",
        elements=[_label("Zgubione", at_source={"source": "rozmowa", "time": 20.0})],
    )

    with pytest.raises(ValueError, match="20s of 'rozmowa' is not in the edit"):
        anchor_to_sources(plan, _edl())
    with pytest.raises(ValueError, match="'nieznane' is not in the edit"):
        anchor_to_sources(
            MotionPlan(
                rationale="Złe id.",
                elements=[_label("Złe", at_source={"source": "nieznane", "time": 1.0})],
            ),
            _edl(),
        )


def test_anchors_are_one_at_a_time_and_until_needs_a_start() -> None:
    with pytest.raises(PydanticValidationError, match="give one of them"):
        MotionElement(
            type="sticker", start=1.0, end=2.0, emoji="👍", reason="Reakcja.",
            at_word="tak", at_source={"source": "rozmowa", "time": 12.0},
        )  # fmt: skip
    with pytest.raises(PydanticValidationError, match="give both"):
        _label("Bez początku", until_source={"source": "rozmowa", "time": 12.0})
    with pytest.raises(PydanticValidationError, match="give one of them"):
        PunchIn(start=0, end=1, scale=1.1, reason="Najazd.", at_word="tak",
                at_source={"source": "rozmowa", "time": 12.0})  # fmt: skip


def test_word_anchoring_places_source_anchors_first_when_given_the_edit() -> None:
    plan = MotionPlan(
        rationale="Razem.",
        elements=[_label("Druga część", at_source={"source": "rozmowa", "time": 24.0})],
    )

    anchored, notes = anchor_to_words(plan, None, duration=17.0, edl=_edl())
    untouched, none = anchor_to_words(plan, None, duration=17.0)

    assert anchored.elements[0].start == 9.0 and notes
    assert untouched.elements[0].start == 0.0 and none == []


def test_scenes_become_labels_on_the_edits_own_times() -> None:
    made, skipped = labels_from_beats(_edl())

    assert [(e.text, e.start, e.end) for e in made] == [
        ("Wstęp", 0.0, 3.0),
        ("Rozwinięcie", 3.0, 15.0),
        ("Na koniec", 15.0, 17.0),
    ], "ranges that follow each other with one beat are one scene"
    assert skipped == []

    brief = EDL(
        ranges=[
            EDLRange(source="rozmowa", start=1.0, end=1.5, beat="Mgnienie"),
            EDLRange(source="rozmowa", start=5.0, end=9.0),
        ]
    )
    made, skipped = labels_from_beats(brief)
    assert made == [] and "too short for a label" in skipped[0]


def test_the_command_writes_the_labels_and_keeps_what_is_not_a_scene(tmp_path: Path) -> None:
    ws = Workspace.at(tmp_path / "edit").ensure()
    save_artifact(_edl(), ws.edl)
    save_artifact(
        MotionPlan(
            rationale="Przed etykietami.",
            elements=[
                _label("Rozwinięcie"),
                _label("Własna etykieta"),
                MotionElement(type="callout", start=4.0, end=5.0, text="Uwaga", reason="Akcent."),
            ],
        ),
        ws.motion_plan,
    )

    done = CliRunner().invoke(app, ["motion", "labels", "-w", str(ws.root), "--json"])

    assert done.exit_code == 0, done.output
    assert [item["text"] for item in json.loads(done.stdout)["labels"]] == [
        "Wstęp", "Rozwinięcie", "Na koniec",
    ]  # fmt: skip
    plan = load_artifact(MotionPlan, ws.motion_plan)
    texts = sorted(e.text for e in plan.elements)
    assert texts == ["Na koniec", "Rozwinięcie", "Uwaga", "Wstęp", "Własna etykieta"]
    scene = next(e for e in plan.elements if e.text == "Rozwinięcie")
    assert (scene.start, scene.end) == (3.0, 15.0), "the stale label was replaced"

    CliRunner().invoke(app, ["motion", "labels", "-w", str(ws.root), "--replace"])
    replaced = load_artifact(MotionPlan, ws.motion_plan)
    assert "Własna etykieta" not in {e.text for e in replaced.elements}

    save_artifact(EDL(ranges=[EDLRange(source="rozmowa", start=0, end=4)]), ws.edl)
    none = CliRunner().invoke(app, ["motion", "labels", "-w", str(ws.root)])
    assert none.exit_code == 1
    assert "no range of the edit has a beat" in " ".join(none.output.split())
