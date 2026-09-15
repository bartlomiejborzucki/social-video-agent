"""Schema validation.

Upstream reads its EDL by raw dict indexing, so a typo is a KeyError and an
inverted range reaches ffmpeg as a negative duration. These tests pin down that
bad artifacts fail early and say what is wrong.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError as PydanticError

from social_video.errors import ValidationError
from social_video.schemas.base import SCHEMA_VERSION, load_artifact, save_artifact
from social_video.schemas.edl import EDL, CropKeyframe, EDLRange, ReframeMode, ReframePlan
from social_video.schemas.source import SourceEntry, SourceManifest


class TestEDLRange:
    def test_rejects_inverted_range(self):
        with pytest.raises(Exception, match="not after"):
            EDLRange(source="a", start=5.0, end=2.0)

    def test_rejects_zero_length_range(self):
        with pytest.raises(Exception, match="not after"):
            EDLRange(source="a", start=5.0, end=5.0)

    def test_rejects_negative_start(self):
        with pytest.raises(PydanticError):
            EDLRange(source="a", start=-1.0, end=2.0)

    def test_output_duration_accounts_for_speed(self):
        assert EDLRange(source="a", start=0, end=10, speed=2.0).output_duration == 5.0

    def test_rejects_absurd_speed(self):
        with pytest.raises(PydanticError):
            EDLRange(source="a", start=0, end=1, speed=0)


class TestEDL:
    def test_requires_at_least_one_range(self):
        with pytest.raises(PydanticError):
            EDL(ranges=[])

    def test_rejects_odd_canvas(self):
        # yuv420p subsamples chroma by two; odd dimensions fail in ffmpeg.
        with pytest.raises(Exception, match="even"):
            EDL(ranges=[EDLRange(source="a", start=0, end=1)], output_height=1921)

    def test_total_duration_sums_output_durations(self):
        edl = EDL(
            ranges=[
                EDLRange(source="a", start=0, end=4),
                EDLRange(source="a", start=10, end=16, speed=2.0),
            ]
        )
        assert edl.total_duration == pytest.approx(7.0)

    def test_source_ids_are_deduplicated_in_order(self):
        edl = EDL(
            ranges=[
                EDLRange(source="b", start=0, end=1),
                EDLRange(source="a", start=0, end=1),
                EDLRange(source="b", start=2, end=3),
            ]
        )
        assert edl.source_ids() == ["b", "a"]

    def test_unknown_field_is_rejected(self):
        # A hallucinated field should fail loudly, not be silently ignored.
        with pytest.raises(PydanticError):
            EDL(ranges=[EDLRange(source="a", start=0, end=1)], nonsense=True)


class TestReframePlan:
    def test_tracked_mode_requires_geometry(self):
        with pytest.raises(Exception, match="crop_width"):
            ReframePlan(mode=ReframeMode.FACE)

    def test_tracked_mode_requires_keyframes(self):
        with pytest.raises(Exception, match="keyframe"):
            ReframePlan(mode=ReframeMode.FACE, crop_width=100, crop_height=200)

    def test_fit_mode_needs_nothing(self):
        assert ReframePlan(mode=ReframeMode.FIT).crop_width is None

    def test_valid_tracked_plan(self):
        plan = ReframePlan(
            mode=ReframeMode.FACE,
            crop_width=404,
            crop_height=720,
            keyframes=[CropKeyframe(t=0.0, x=10, y=0)],
        )
        assert len(plan.keyframes) == 1


class TestSourceManifest:
    def test_lookup_by_id(self):
        entry = SourceEntry(
            id="clip",
            path="/x/clip.mp4",
            fingerprint="f",
            size_bytes=1,
            duration=1.0,
            width=1920,
            height=1080,
            frame_rate="25/1",
        )
        assert SourceManifest(sources=[entry]).by_id("clip").path == "/x/clip.mp4"

    def test_unknown_id_names_the_alternatives(self):
        entry = SourceEntry(
            id="clip",
            path="/x/clip.mp4",
            fingerprint="f",
            size_bytes=1,
            duration=1.0,
            width=1920,
            height=1080,
            frame_rate="25/1",
        )
        with pytest.raises(KeyError, match="clip"):
            SourceManifest(sources=[entry]).by_id("typo")

    def test_rotation_swaps_display_size(self):
        entry = SourceEntry(
            id="phone",
            path="/x/p.mp4",
            fingerprint="f",
            size_bytes=1,
            duration=1.0,
            width=1920,
            height=1080,
            rotation=90,
            frame_rate="30/1",
        )
        assert entry.display_size == (1080, 1920)
        assert entry.is_portrait


class TestPersistence:
    def test_round_trip(self, tmp_path):
        edl = EDL(ranges=[EDLRange(source="a", start=0, end=2, reason="why")])
        path = save_artifact(edl, tmp_path / "edl.json")
        assert load_artifact(EDL, path).ranges[0].reason == "why"

    def test_written_as_utf8(self, tmp_path):
        edl = EDL(ranges=[EDLRange(source="a", start=0, end=2, quote="Zażółć gęślą")])
        path = save_artifact(edl, tmp_path / "edl.json")
        assert "Zażółć gęślą" in path.read_text(encoding="utf-8")

    def test_malformed_json_names_the_location(self, tmp_path):
        p = tmp_path / "edl.json"
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValidationError, match="not valid JSON"):
            load_artifact(EDL, p)

    def test_schema_violation_names_the_field(self, tmp_path):
        p = tmp_path / "edl.json"
        p.write_text(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "ranges": [{"source": "a", "start": 5, "end": 1}],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValidationError, match="ranges"):
            load_artifact(EDL, p)

    def test_version_mismatch_is_reported_not_guessed(self, tmp_path):
        p = tmp_path / "edl.json"
        p.write_text(
            json.dumps({"schema_version": SCHEMA_VERSION + 99, "ranges": []}),
            encoding="utf-8",
        )
        with pytest.raises(ValidationError, match="schema_version"):
            load_artifact(EDL, p)

    def test_missing_file(self, tmp_path):
        with pytest.raises(ValidationError, match="not found"):
            load_artifact(EDL, tmp_path / "nope.json")
