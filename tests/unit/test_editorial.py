"""Boundary snapping, the mechanical draft pass, and plan compilation."""

from __future__ import annotations

import pytest

from social_video.editorial.boundaries import snap_range, snap_ranges, text_in
from social_video.editorial.compile import compile_plan, keep_intervals
from social_video.editorial.draft import draft_edit_plan
from social_video.profiles import load_profile
from social_video.schemas.plan import EditPlan, PlanAction, PlanItem
from social_video.schemas.transcript import TokenType, Transcript, TranscriptToken
from social_video.transcribe.normalize import synthesize_spacing


def transcript_of(words: list[tuple[str, float, float]], duration: float = 30.0):
    tokens = [TranscriptToken(type=TokenType.WORD, text=t, start=s, end=e) for t, s, e in words]
    return Transcript(
        source_id="clip",
        source_fingerprint="f",
        duration=duration,
        provider="test",
        tokens=synthesize_spacing(tokens),
    )


SIMPLE = [("Hello", 1.0, 1.5), ("there", 1.6, 2.1), ("friend", 2.2, 2.8)]


class TestSnapRange:
    def test_snaps_in_point_to_a_word_start(self):
        tr = transcript_of(SIMPLE)
        out = snap_range(tr, 1.05, 2.8, padding=0.0)
        assert out.start == pytest.approx(1.0)
        assert "Hello" in out.start_reason

    def test_snaps_out_point_to_a_word_end(self):
        tr = transcript_of(SIMPLE)
        out = snap_range(tr, 1.0, 2.75, padding=0.0)
        assert out.end == pytest.approx(2.8)

    def test_never_cuts_inside_a_word(self):
        tr = transcript_of(SIMPLE)
        # 1.25 is mid-"Hello" and far from any edge; it must back up, not clip.
        out = snap_range(tr, 1.25, 2.8, padding=0.0, search=0.05)
        assert out.start == pytest.approx(1.0)

    def test_padding_does_not_pull_in_the_previous_word(self):
        tr = transcript_of(SIMPLE)
        # Only 0.1s of silence sits before "there"; padding must not exceed it.
        out = snap_range(tr, 1.6, 2.1, padding=0.5)
        assert out.start >= 1.5

    def test_padding_is_applied_when_there_is_room(self):
        tr = transcript_of(SIMPLE)
        out = snap_range(tr, 1.0, 1.5, padding=0.3)
        assert out.start == pytest.approx(0.7)

    def test_padding_is_bounded_by_the_source(self):
        tr = transcript_of([("word", 0.0, 0.5)], duration=1.0)
        out = snap_range(tr, 0.0, 0.5, padding=5.0, source_duration=1.0)
        assert out.start == 0.0
        assert out.end <= 1.0

    def test_transcript_with_no_words_is_left_alone(self):
        tr = transcript_of([])
        out = snap_range(tr, 1.0, 2.0)
        assert (out.start, out.end) == (1.0, 2.0)

    def test_does_not_invert_a_range(self):
        tr = transcript_of(SIMPLE)
        out = snap_range(tr, 2.0, 2.05, padding=0.0)
        assert out.end > out.start


class TestSnapRanges:
    def test_merges_ranges_that_padding_pushed_together(self):
        tr = transcript_of(SIMPLE)
        out = snap_ranges(tr, [(1.0, 1.5), (1.6, 2.1)], padding=0.1, merge_gap=0.2)
        assert len(out) == 1

    def test_keeps_genuinely_separate_ranges_apart(self):
        tr = transcript_of([("a", 0.0, 0.5), ("b", 10.0, 10.5)])
        out = snap_ranges(tr, [(0.0, 0.5), (10.0, 10.5)], padding=0.05)
        assert len(out) == 2

    def test_empty(self):
        assert snap_ranges(transcript_of(SIMPLE), []) == []


class TestDraftPlan:
    def test_marks_long_dead_air_for_removal(self):
        tr = transcript_of([("before", 0.0, 0.5), ("after", 6.0, 6.5)], duration=8.0)
        plan = draft_edit_plan(tr, load_profile("talking-head"))
        drops = [i for i in plan.items if i.action is PlanAction.DROP]
        assert any("dead air" in i.reason for i in drops)

    def test_leaves_short_pauses_alone(self):
        # A natural pause is speech rhythm, not a defect.
        tr = transcript_of([("a", 0.0, 0.5), ("b", 0.8, 1.2)], duration=2.0)
        plan = draft_edit_plan(tr, load_profile("talking-head"))
        assert not any("dead air" in i.reason for i in plan.items)

    def test_calm_profile_tolerates_longer_pauses(self):
        tr = transcript_of([("a", 0.0, 0.5), ("b", 1.7, 2.2)], duration=3.0)
        calm = draft_edit_plan(tr, load_profile("calm-expert"))
        fast = draft_edit_plan(tr, load_profile("fast-social"))
        calm_drops = sum("dead air" in i.reason for i in calm.items)
        fast_drops = sum("dead air" in i.reason for i in fast.items)
        assert fast_drops > calm_drops

    def test_removes_isolated_filler(self):
        tr = transcript_of([("So", 0.0, 0.4), ("um", 1.0, 1.3), ("anyway", 2.0, 2.6)], duration=4.0)
        plan = draft_edit_plan(tr, load_profile("talking-head"))
        assert any("filler" in i.reason for i in plan.items)

    def test_keeps_filler_that_is_inside_fluent_speech(self):
        # No surrounding pauses: this is how the person talks.
        tr = transcript_of([("So", 0.0, 0.4), ("um", 0.4, 0.6), ("anyway", 0.6, 1.2)], duration=2.0)
        plan = draft_edit_plan(tr, load_profile("talking-head"))
        assert not any("filler" in i.reason for i in plan.items)

    def test_detects_a_false_start(self):
        words = [
            ("the", 0.0, 0.2),
            ("thing", 0.2, 0.5),
            ("is", 0.5, 0.7),
            ("the", 0.8, 1.0),
            ("thing", 1.0, 1.3),
            ("is", 1.3, 1.5),
            ("simple", 1.6, 2.2),
        ]
        plan = draft_edit_plan(transcript_of(words), load_profile("talking-head"))
        assert any("false start" in i.reason for i in plan.items)

    def test_empty_transcript_asks_rather_than_crashes(self):
        plan = draft_edit_plan(transcript_of([]), load_profile("talking-head"))
        assert plan.items == []
        assert plan.open_questions


class TestKeepIntervals:
    def test_drops_become_gaps(self):
        plan = EditPlan(
            goal="g", items=[PlanItem(action=PlanAction.DROP, source="a", start=2.0, end=4.0)]
        )
        assert keep_intervals(plan, 10.0) == [(0.0, 2.0, ""), (4.0, 10.0, "")]

    def test_explicit_keeps_win_over_drops(self):
        plan = EditPlan(
            goal="g",
            items=[
                PlanItem(action=PlanAction.KEEP, source="a", start=1.0, end=2.0, reason="best bit"),
                PlanItem(action=PlanAction.DROP, source="a", start=5.0, end=6.0),
            ],
        )
        assert keep_intervals(plan, 10.0) == [(1.0, 2.0, "best bit")]

    def test_no_items_keeps_everything(self):
        assert keep_intervals(EditPlan(goal="g"), 10.0) == [(0.0, 10.0, "whole source kept")]

    def test_overlapping_drops_are_handled(self):
        plan = EditPlan(
            goal="g",
            items=[
                PlanItem(action=PlanAction.DROP, source="a", start=2.0, end=5.0),
                PlanItem(action=PlanAction.DROP, source="a", start=3.0, end=4.0),
            ],
        )
        assert keep_intervals(plan, 10.0) == [(0.0, 2.0, ""), (5.0, 10.0, "")]


class TestCompilePlan:
    def test_produces_word_aligned_ranges_with_reasons(self):
        tr = transcript_of(
            [("keep", 0.0, 0.5), ("cut", 4.0, 4.5), ("keep2", 9.0, 9.5)], duration=10.0
        )
        plan = EditPlan(
            goal="g",
            items=[
                PlanItem(
                    action=PlanAction.DROP, source="clip", start=3.8, end=4.7, reason="off topic"
                ),
            ],
        )
        edl = compile_plan(plan, tr, load_profile("talking-head"))
        joined = " ".join(r.quote for r in edl.ranges)
        assert "cut" not in joined
        assert "keep" in joined and "keep2" in joined
        assert all(r.reason for r in edl.ranges)

    def test_uses_the_profile_canvas_and_reframe(self):
        tr = transcript_of(SIMPLE)
        edl = compile_plan(EditPlan(goal="g"), tr, load_profile("landscape-16x9"))
        assert (edl.output_width, edl.output_height) == (1920, 1080)
        assert edl.default_reframe.value == "fit"

    def test_a_plan_that_removes_everything_says_so(self):
        tr = transcript_of(SIMPLE, duration=3.0)
        plan = EditPlan(
            goal="g", items=[PlanItem(action=PlanAction.DROP, source="clip", start=0.0, end=3.0)]
        )
        with pytest.raises(ValueError, match="removes everything"):
            compile_plan(plan, tr, load_profile("talking-head"))


def test_text_in_returns_only_fully_contained_words():
    tr = transcript_of(SIMPLE)
    assert text_in(tr, 1.0, 2.1) == "Hello there"
