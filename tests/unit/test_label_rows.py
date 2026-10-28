"""A brief that names one scene's label on two rows, or two labels on one scene."""

from __future__ import annotations

from pathlib import Path

import pytest

from social_video.errors import ValidationError
from social_video.motion.layout import pin_labels
from social_video.pipeline import stage_compile
from social_video.schemas.base import save_artifact
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import MotionElement, MotionElementType, MotionPlan
from social_video.workspace.layout import Workspace
from tests.unit.test_multi_source import CHILD, KUBEK, ODRUCH, PROFILE, SPROBUJ, _plan

EDIT = EDL(ranges=[EDLRange(source="a", start=0, end=4, beat="Pora spać"),
                   EDLRange(source="b", start=0, end=5, beat="Co wtedy")])  # fmt: skip


def _label(text: str, start: float, end: float) -> MotionElement:
    return MotionElement(type=MotionElementType.LABEL, start=start, end=end, text=text,
                         reason="brief")  # fmt: skip


def test_two_rows_of_one_label_are_one_label_over_its_scene() -> None:
    rows = [_label("Pora spać", 0.0, 1.0), _label("Pora spać", 1.0, 4.0),
            _label("Co wtedy", 4.0, 9.0)]  # fmt: skip

    pinned, notes = pin_labels(rows, EDIT)

    assert [(e.text, e.start, e.end) for e in pinned] == [
        ("Pora spać", 0.0, 4.0),
        ("Co wtedy", 4.0, 9.0),
    ]
    assert "label 'Pora spać' 1.00-4.00 s joined with the same label before it" in notes


def test_rows_of_one_label_without_a_beat_are_joined_too() -> None:
    edit = EDL(ranges=[EDLRange(source="a", start=0, end=4), EDLRange(source="b", start=0, end=5)])
    pinned, _notes = pin_labels([_label("Wieczór", 0.0, 1.0), _label("Wieczór", 1.0, 4.0)], edit)
    assert [(e.start, e.end) for e in pinned] == [(0.0, 4.0)]


def test_two_labels_on_one_scene_are_refused_with_what_to_do() -> None:
    rows = [_label("Pora spać", 0.0, 2.0), _label("Kąpiel", 0.0, 3.0)]
    with pytest.raises(ValidationError, match="'Pora spać' and 'Kąpiel' both land on the scene"):
        pin_labels(rows, EDIT)


def test_a_compile_the_labels_refuse_leaves_the_old_edl(tmp_path: Path) -> None:
    ws = Workspace.at(tmp_path / "edit")
    ws.ensure()
    save_artifact(EDIT, ws.edl)
    before = ws.edl.read_bytes()
    rows = [_label("Jeden", 0.0, 2.0), _label("Dwa", 0.0, 3.0)]
    save_artifact(MotionPlan(rationale="r", elements=rows), ws.motion_plan)
    others = {"dziecko": CHILD, "odruch": ODRUCH, "sprobuj": SPROBUJ}

    with pytest.raises(ValidationError, match="both land on the scene"):
        stage_compile(_plan(), KUBEK, ws, PROFILE, transcripts=others)

    assert ws.edl.read_bytes() == before
