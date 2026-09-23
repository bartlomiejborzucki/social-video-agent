"""Stumbles are found and offered, and only accepted ones reach the EDL."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pytest
from typer.testing import CliRunner

from social_video.editorial.compile import compile_plan
from social_video.editorial.cuts import accept_cuts, find_cut_candidates
from social_video.errors import ValidationError
from social_video.profiles import load_profile
from social_video.schemas.plan import CutConfidence, CutKind, EditPlan
from social_video.schemas.transcript import TokenType, Transcript, TranscriptToken
from social_video.transcribe.normalize import synthesize_spacing

PROFILE = load_profile("talking-head")


def _transcript(words: list[tuple[str, float, float]], *, duration: float | None = None):
    tokens = [TranscriptToken(text=text, start=start, end=end) for text, start, end in words]
    return Transcript(
        source_id="clip",
        source_fingerprint="f" * 16,
        duration=duration if duration is not None else words[-1][2] + 0.2,
        provider="test",
        tokens=synthesize_spacing(tokens),
    )


def _kinds(transcript: Transcript) -> list[tuple[str, str, str]]:
    return [
        (c.kind.value, c.confidence.value, c.quote)
        for c in find_cut_candidates(transcript, PROFILE).candidates
    ]


def test_a_hesitation_between_pauses_is_certain_and_inside_a_sentence_is_not() -> None:
    transcript = _transcript(
        [
            ("Dzisiaj", 0.0, 0.4),
            ("yyy", 0.8, 1.1),
            ("pokażę", 1.5, 1.9),
            ("eee", 1.92, 2.1),
            ("wam", 2.12, 2.4),
        ]
    )

    assert _kinds(transcript) == [
        ("filler", "high", "yyy"),
        ("filler", "medium", "eee"),
    ]


def test_polish_no_is_a_candidate_only_when_it_stands_alone() -> None:
    inline = _transcript([("To", 0.0, 0.2), ("no", 0.22, 0.4), ("właśnie", 0.42, 0.9)])
    alone = _transcript([("To", 0.0, 0.2), ("no", 0.6, 0.8), ("właśnie", 1.2, 1.7)])

    assert _kinds(inline) == []
    assert _kinds(alone) == [("filler", "high", "no")]


def test_a_doubled_word_is_a_stutter_and_a_deliberate_one_needs_a_listen() -> None:
    transcript = _transcript(
        [
            ("to", 0.0, 0.2),
            ("to", 0.3, 0.5),
            ("jest", 0.55, 0.8),
            ("bardzo", 0.85, 1.2),
            ("bardzo", 1.25, 1.6),
            ("ważne", 1.65, 2.1),
        ]
    )

    assert _kinds(transcript) == [
        ("stutter", "high", "to"),
        ("stutter", "medium", "bardzo"),
    ]


def test_the_first_take_of_a_restarted_phrase_is_the_candidate() -> None:
    transcript = _transcript(
        [
            ("Chcę", 0.0, 0.3),
            ("wam", 0.35, 0.5),
            ("pokazać,", 0.55, 0.9),
            ("chcę", 1.2, 1.5),
            ("wam", 1.55, 1.7),
            ("pokazać", 1.75, 2.1),
            ("nowość", 2.15, 2.6),
        ]
    )

    (candidate,) = find_cut_candidates(transcript, PROFILE).candidates
    assert candidate.kind is CutKind.FALSE_START
    assert candidate.confidence is CutConfidence.HIGH
    assert candidate.quote == "Chcę wam pokazać,"
    # The abandoned take goes with the gap after it, keeping a breath.
    assert candidate.start == 0.0
    assert candidate.end == pytest.approx(1.15)


def test_long_pauses_are_tightened_not_closed_and_dead_air_is_trimmed() -> None:
    transcript = _transcript(
        [("Start", 1.5, 1.9), ("koniec", 3.5, 3.9)],
        duration=6.0,
    )

    candidates = find_cut_candidates(transcript, PROFILE).candidates

    assert [c.kind for c in candidates] == [CutKind.PAUSE] * 3
    lead, middle, tail = candidates
    assert lead.start == 0.0 and lead.end < 1.5
    kept_breath = (middle.start - 1.9) + (3.5 - middle.end)
    assert kept_breath == pytest.approx(PROFILE.min_pause)
    assert tail.end == 6.0


def test_candidates_never_overlap_and_are_numbered_in_time_order() -> None:
    transcript = _transcript(
        [
            ("to", 0.0, 0.2),
            ("to", 0.3, 0.5),
            ("to", 2.0, 2.2),
            ("jest", 2.3, 2.6),
        ]
    )

    candidates = find_cut_candidates(transcript, PROFILE).candidates

    assert [c.id for c in candidates] == [f"cut-{n:03d}" for n in range(1, len(candidates) + 1)]
    for first, second in pairwise(candidates):
        assert first.end <= second.start


def _plan() -> EditPlan:
    return EditPlan(goal="test")


def test_accepting_adds_each_candidate_once_with_its_reason() -> None:
    transcript = _transcript([("Dzisiaj", 0.0, 0.4), ("yyy", 0.8, 1.1), ("wam", 1.5, 1.9)])
    found = find_cut_candidates(transcript, PROFILE)
    plan = _plan()

    first = accept_cuts(plan, found, ["cut-001"])
    again = accept_cuts(plan, found, ["cut-001"])

    assert len(first) == 1 and again == []
    (item,) = plan.items
    assert item.cut == "cut-001"
    assert item.reason.startswith("accepted cut-001: hesitation 'yyy'")


def test_an_unknown_candidate_is_refused_by_name() -> None:
    found = find_cut_candidates(_transcript([("a", 0.0, 0.2)]), PROFILE)

    with pytest.raises(ValidationError, match="unknown cut candidate 'cut-999'"):
        accept_cuts(_plan(), found, ["cut-999"])


def test_an_accepted_filler_is_removed_exactly_even_inside_a_kept_span() -> None:
    """Snapping must not pull a short filler back in at a cut edge."""
    transcript = _transcript(
        [
            ("Dzisiaj", 0.0, 0.4),
            ("yyy", 0.6, 0.75),
            ("pokażę", 1.1, 1.5),
            ("wam", 1.55, 1.9),
        ],
        duration=2.0,
    )
    found = find_cut_candidates(transcript, PROFILE)
    plan = EditPlan.model_validate(
        {
            "goal": "test",
            "items": [{"action": "keep", "source": "clip", "start": 0.0, "end": 1.9}],
        }
    )
    accept_cuts(plan, found, [c.id for c in found.candidates if c.kind is CutKind.FILLER])

    edl = compile_plan(plan, transcript, PROFILE)

    spoken = [
        t.text
        for rng in edl.ranges
        for t in transcript.tokens
        if t.type is TokenType.WORD and t.start >= rng.start and t.end <= rng.end
    ]
    assert spoken == ["Dzisiaj", "pokażę", "wam"]
    assert "cut-001 removed" in edl.ranges[1].reason


def test_the_cli_finds_accepts_and_compiles(tmp_path: Path, monkeypatch) -> None:
    from social_video.cli import app
    from social_video.schemas.base import load_artifact, save_artifact
    from social_video.schemas.edl import EDL
    from social_video.workspace.layout import Workspace

    transcript = _transcript(
        [("Dzisiaj", 0.0, 0.4), ("yyy", 0.8, 1.1), ("pokażę", 1.5, 1.9)], duration=2.0
    )
    monkeypatch.setattr("social_video.pipeline.stage_transcribe", lambda *a, **k: transcript)
    workspace = Workspace.at(tmp_path / "edit")
    workspace.ensure()
    save_artifact(_plan(), workspace.edit_plan)
    runner = CliRunner()
    source = str(tmp_path / "clip.mp4")

    found = runner.invoke(app, ["cuts", "find", source, "-w", str(workspace.root), "--json"])
    accepted = runner.invoke(
        app, ["cuts", "accept", "-w", str(workspace.root), "--kind", "filler", "--json"]
    )
    compiled = runner.invoke(app, ["compile", source, "-w", str(workspace.root)])
    refused = runner.invoke(app, ["compile", source, "-w", str(workspace.root)])

    assert found.exit_code == 0, found.output
    assert accepted.exit_code == 0, accepted.output
    assert compiled.exit_code == 0, compiled.output
    assert refused.exit_code == 1 and "--force" in refused.output
    edl = load_artifact(EDL, workspace.edl)
    assert all(not (r.start < 1.1 and r.end > 0.8) for r in edl.ranges)


def test_a_kind_filter_that_matches_nothing_is_not_an_error(tmp_path: Path, monkeypatch) -> None:
    from social_video.cli import app
    from social_video.schemas.base import save_artifact
    from social_video.workspace.layout import Workspace

    transcript = _transcript([("Dzisiaj", 0.0, 0.4), ("pokażę", 0.5, 0.9)], duration=1.0)
    monkeypatch.setattr("social_video.pipeline.stage_transcribe", lambda *a, **k: transcript)
    workspace = Workspace.at(tmp_path / "edit")
    workspace.ensure()
    save_artifact(_plan(), workspace.edit_plan)
    runner = CliRunner()
    runner.invoke(app, ["cuts", "find", str(tmp_path / "clip.mp4"), "-w", str(workspace.root)])

    result = runner.invoke(app, ["cuts", "accept", "-w", str(workspace.root), "--kind", "pause"])

    assert result.exit_code == 0, result.output
    assert "0 cut(s) added" in result.output
