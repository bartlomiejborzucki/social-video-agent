"""Schema validation.

Upstream reads its EDL by raw dict indexing, so a typo is a KeyError and an
inverted range reaches ffmpeg as a negative duration. These tests pin down that
bad artifacts fail early and say what is wrong.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError as PydanticError

from social_video.editorial.review import apply_editorial_qa
from social_video.errors import ValidationError
from social_video.schemas.base import SCHEMA_VERSION, load_artifact, save_artifact
from social_video.schemas.editorial_qa import EditorialFix, EditorialQA, EditorialQAStatus
from social_video.schemas.edl import (
    EDL,
    CropKeyframe,
    EDLRange,
    ReframeMode,
    ReframePlan,
    VisualFillStrategy,
)
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

    def test_split_av_and_freeze_define_one_output_range(self):
        item = EDLRange(
            source="video",
            start=0,
            end=2,
            audio_source="voice",
            audio_start=3,
            audio_end=6,
            freeze_at=1.5,
            freeze_duration=1.5,
            max_visual_source_time=1.5,
            visual_fill_strategy=VisualFillStrategy.FREEZE,
            intentional_hold=True,
            technical_reason="Do not show frames after the approved privacy boundary.",
        )
        assert item.effective_video_source == "video"
        assert item.effective_audio_source == "voice"
        assert item.visual_content_end == 1.5
        assert item.output_duration == 3.0

    def test_freeze_cannot_cross_privacy_boundary(self):
        with pytest.raises(PydanticError, match="max_visual_source_time"):
            EDLRange(
                source="video",
                start=0,
                end=2,
                freeze_at=1.8,
                max_visual_source_time=1.5,
            )

    def test_long_audio_and_7_10_safe_video_requires_fill_strategy(self):
        with pytest.raises(PydanticError, match=r"outlasts safe moving video by 3\.760s"):
            EDLRange(
                source="b-roll",
                start=0,
                end=10.86,
                video_end=10.86,
                audio_end=10.86,
                freeze_at=7.10,
                max_visual_source_time=7.10,
            )

    def test_short_explicit_freeze_below_default_limit_is_allowed(self):
        item = EDLRange(
            source="b-roll",
            start=0,
            end=7.7,
            freeze_at=7.0,
            max_visual_source_time=7.0,
            freeze_duration=0.7,
            visual_fill_strategy=VisualFillStrategy.FREEZE,
            visual_fill_reason="Brief hold to finish the final word.",
        )
        assert item.output_duration == pytest.approx(7.7)

    def test_long_freeze_requires_explicit_approval_and_reason(self):
        common = {
            "source": "b-roll",
            "start": 0,
            "end": 10.86,
            "freeze_at": 7.10,
            "max_visual_source_time": 7.10,
            "freeze_duration": 3.76,
            "visual_fill_strategy": VisualFillStrategy.FREEZE,
        }
        with pytest.raises(PydanticError, match="max_static_hold"):
            EDLRange(**common)
        with pytest.raises(PydanticError, match="written reason"):
            EDLRange(**common, intentional_hold=True)
        approved = EDLRange(
            **common,
            intentional_hold=True,
            visual_fill_reason="Deliberate still ending approved by the supervising editor.",
        )
        assert approved.freeze_duration == 3.76


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


class TestEditorialQA:
    def test_approved_is_always_an_explicit_empty_contract(self):
        qa = EditorialQA(status=EditorialQAStatus.APPROVED, fixes=[])
        assert qa.model_dump(mode="json") == {
            "schema_version": SCHEMA_VERSION,
            "status": "approved",
            "fixes": [],
        }

    def test_changes_requested_requires_exact_fixes(self):
        qa = EditorialQA(
            status=EditorialQAStatus.CHANGES_REQUESTED,
            fixes=[EditorialFix(path="ranges[2].end", value=4.2, reason="trim pause")],
        )
        assert qa.fixes[0].path == "ranges[2].end"

    @pytest.mark.parametrize(
        "payload",
        [
            {"status": "approved", "fixes": [{"path": "ranges[0].end", "value": 1}]},
            {"status": "changes_requested", "fixes": []},
            {"status": "maybe", "fixes": []},
            {"status": "approved", "fixes": [], "unknown": True},
        ],
    )
    def test_rejects_ambiguous_or_unknown_contracts(self, payload):
        with pytest.raises(PydanticError):
            EditorialQA.model_validate(payload)

    def test_approved_does_not_change_edl(self):
        edl = EDL(ranges=[EDLRange(source="a", start=0, end=2)])
        updated, changed = apply_editorial_qa(
            edl, EditorialQA(status=EditorialQAStatus.APPROVED, fixes=[])
        )
        assert updated is edl
        assert not changed

    def test_applies_only_the_listed_fix(self):
        edl = EDL(ranges=[EDLRange(source="a", start=0, end=2, quote="keep")])
        review = EditorialQA(
            status=EditorialQAStatus.CHANGES_REQUESTED,
            fixes=[EditorialFix(path="ranges[0].end", value=1.5, reason="tighten")],
        )
        updated, changed = apply_editorial_qa(edl, review)
        assert changed
        assert updated.ranges[0].end == 1.5
        assert updated.ranges[0].quote == "keep"

    def test_rejects_fix_for_unknown_path(self):
        edl = EDL(ranges=[EDLRange(source="a", start=0, end=2)])
        review = EditorialQA(
            status=EditorialQAStatus.CHANGES_REQUESTED,
            fixes=[EditorialFix(path="ranges[7].end", value=1.5)],
        )
        with pytest.raises(ValidationError, match="does not exist"):
            apply_editorial_qa(edl, review)
