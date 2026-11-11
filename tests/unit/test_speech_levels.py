"""Each recording's speech at one level, inside a ceiling."""

from __future__ import annotations

import pytest

from social_video.edl.levels import (
    LEVEL_TOLERANCE_LU,
    MAX_LEVEL_GAIN_DB,
    NO_LEVELS,
    plan_levels,
)
from social_video.schemas.edl import EDL, EDLRange


def test_one_recording_is_left_alone() -> None:
    plan = plan_levels({"kamera": -19.0}, {"kamera": 30.0})

    assert not plan.changed and plan.gains == {}
    assert not NO_LEVELS.changed and NO_LEVELS.evidence()["measured_lufs"] == {}


def test_recordings_move_toward_the_level_they_share_by_how_long_each_is_heard() -> None:
    plan = plan_levels({"gosc": -13.0, "prowadzacy": -17.0}, {"gosc": 5.0, "prowadzacy": 45.0})

    assert plan.target == pytest.approx(-16.6, abs=0.01)
    assert plan.gains["gosc"] == pytest.approx(-3.6, abs=0.01), "the short one moves most"
    assert "prowadzacy" not in plan.gains, "0.4 dB is not worth a move"
    assert plan.spread_after <= LEVEL_TOLERANCE_LU
    assert "gosc -3.6 dB" in plan.reason()


def test_recordings_already_together_are_left_alone() -> None:
    plan = plan_levels({"a": -16.0, "b": -16.3}, {"a": 10.0, "b": 10.0})

    assert not plan.changed


def test_a_move_stops_at_its_ceiling_and_the_evidence_says_what_is_left() -> None:
    plan = plan_levels({"blisko": -10.0, "daleko": -30.0}, {"blisko": 10.0, "daleko": 10.0})

    assert plan.gains == {"blisko": -MAX_LEVEL_GAIN_DB, "daleko": MAX_LEVEL_GAIN_DB}
    evidence = plan.evidence()
    assert evidence["spread_after_lu"] == 8.0
    assert evidence["max_gain_db"] == MAX_LEVEL_GAIN_DB
    assert evidence["measured_lufs"] == {"blisko": -10.0, "daleko": -30.0}


def test_the_gain_is_carried_by_a_copy_of_the_edit_not_the_edit() -> None:
    edl = EDL(
        ranges=[
            EDLRange(source="gosc", start=0, end=4),
            EDLRange(source="prowadzacy", start=0, end=20, audio_gain_db=1.0),
        ]
    )
    plan = plan_levels({"gosc": -13.0, "prowadzacy": -17.0}, {"gosc": 4.0, "prowadzacy": 20.0})

    levelled = plan.applied_to(edl)

    assert [r.audio_gain_db for r in edl.ranges] == [0.0, 1.0], "the EDL is not changed"
    assert levelled.ranges[0].audio_gain_db == pytest.approx(plan.gains["gosc"])
    assert levelled.ranges[1].audio_gain_db == pytest.approx(1.0 + plan.gains["prowadzacy"])
    assert NO_LEVELS.applied_to(edl) is edl
