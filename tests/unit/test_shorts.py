"""One long recording into several standalone shorts."""

from __future__ import annotations

from pathlib import Path

import pytest

from social_video.errors import ValidationError
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.edl import EDL, ReframeMode
from social_video.schemas.plan import CandidateScores, CandidateSet, ClipCandidate
from social_video.schemas.source import SourceEntry, SourceManifest
from social_video.shorts import load_candidates, materialize_shorts, selected_candidates
from social_video.workspace.layout import Workspace


def _manifest(tmp_path: Path) -> SourceManifest:
    media = tmp_path / "talk.mp4"
    media.write_bytes(b"video")
    return SourceManifest(
        sources=[
            SourceEntry(
                id="talk",
                path=str(media),
                fingerprint="f" * 16,
                size_bytes=5,
                duration=600.0,
                width=1920,
                height=1080,
                frame_rate="30/1",
            )
        ]
    )


def _candidate(name: str, start: float, end: float, *, selected: bool = True) -> ClipCandidate:
    return ClipCandidate(
        id=name,
        source="talk",
        start=start,
        end=end,
        topic=f"temat {name}",
        transcript="Najważniejsza teza tego fragmentu.",
        reason="Stoi samodzielnie: teza i jej uzasadnienie.",
        selected=selected,
        scores=CandidateScores(
            hook_quality=0.8,
            standalone=0.9,
            information_density=0.7,
            payoff=0.8,
            ending_quality=0.7,
            context_dependency=0.2,
        ),
    )


def _workspace(tmp_path: Path, candidates: list[ClipCandidate]) -> Workspace:
    workspace = Workspace.at(tmp_path / "edit").ensure()
    save_artifact(_manifest(tmp_path), workspace.source_manifest)
    save_artifact(CandidateSet(source="talk", candidates=candidates), workspace.candidate_set)
    return workspace


def test_a_missing_candidate_set_names_what_to_write(tmp_path: Path) -> None:
    workspace = Workspace.at(tmp_path / "edit").ensure()
    with pytest.raises(ValidationError, match=r"candidates\.json"):
        load_candidates(workspace)


def test_an_unreviewed_candidate_set_produces_nothing(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, [_candidate("a", 10, 40, selected=False)])
    with pytest.raises(ValidationError, match="editorial decision"):
        materialize_shorts(workspace)


def test_each_selected_candidate_gets_its_own_workspace_and_edl(tmp_path: Path) -> None:
    workspace = _workspace(
        tmp_path,
        [_candidate("hook-claim", 12.4, 47.9), _candidate("story", 120.0, 165.0)],
    )
    index = materialize_shorts(workspace)
    assert len(index.shorts) == 2
    for entry in index.shorts:
        child = Path(entry.workspace)
        assert child.is_dir()
        edl = load_artifact(EDL, Path(entry.edl))
        assert len(edl.ranges) == 1
        assert edl.ranges[0].source == "talk"
        assert edl.ranges[0].reason
        assert (child / "candidate.json").is_file()
        assert (child / "source-manifest.json").is_file()
    assert load_artifact(EDL, Path(index.shorts[0].edl)).ranges[0].start == 12.4


def test_transcription_is_reused_rather_than_repeated(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, [_candidate("a", 10, 40)])
    (workspace.transcripts / "talk.json").write_text('{"words": []}', encoding="utf-8")
    index = materialize_shorts(workspace)
    child = Workspace.at(Path(index.shorts[0].workspace))
    assert (child.transcripts / "talk.json").is_file()


def test_only_selects_explicit_candidates_and_rejects_unknown_ids(tmp_path: Path) -> None:
    workspace = _workspace(
        tmp_path, [_candidate("a", 10, 40), _candidate("b", 60, 90, selected=False)]
    )
    index = materialize_shorts(workspace, only=["b"])
    assert [entry.id for entry in index.shorts] == ["b"]
    with pytest.raises(ValidationError, match="unknown candidate"):
        materialize_shorts(workspace, only=["nie-ma"])


def test_a_fragment_is_refused_rather_than_rendered(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, [_candidate("krotki", 10.0, 11.5)])
    with pytest.raises(ValidationError, match="fragment"):
        materialize_shorts(workspace)


def test_a_candidate_naming_an_unknown_source_is_refused(tmp_path: Path) -> None:
    candidate = _candidate("a", 10, 40)
    candidate.source = "nie-ma-takiego"
    workspace = _workspace(tmp_path, [candidate])
    with pytest.raises(ValidationError, match="not in"):
        materialize_shorts(workspace)


def test_a_candidate_id_cannot_escape_the_candidates_directory(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, [_candidate("../../etc/passwd", 10, 40)])
    index = materialize_shorts(workspace)
    child = Path(index.shorts[0].workspace).resolve()
    assert workspace.candidates.resolve() in child.parents


def test_the_framing_mode_can_be_set_for_every_clip(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, [_candidate("a", 10, 40)])
    index = materialize_shorts(workspace, reframe=ReframeMode.SPEAKER)
    assert load_artifact(EDL, Path(index.shorts[0].edl)).default_reframe is ReframeMode.SPEAKER


def test_ranking_puts_the_strongest_candidate_first(tmp_path: Path) -> None:
    weak = _candidate("weak", 10, 40)
    weak.scores = CandidateScores(
        hook_quality=0.2,
        standalone=0.3,
        information_density=0.2,
        payoff=0.2,
        ending_quality=0.2,
        context_dependency=0.9,
    )
    workspace = _workspace(tmp_path, [weak, _candidate("strong", 60, 100)])
    ranked = load_candidates(workspace).ranked()
    assert ranked[0].id == "strong"
    assert [c.id for c in selected_candidates(load_candidates(workspace))] == ["weak", "strong"]
