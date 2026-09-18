"""Turning one long recording into several standalone shorts.

Selection stays editorial: the agent writes `candidates/candidates.json` after
reading the packed transcript, with a score and a written reason per candidate.
This module does the mechanical half -- give each selected candidate its own
workspace and EDL so every existing command (render, qa, cover, deliver) works
on it unchanged.

Transcription is never repeated. The parent's transcripts are copied into each
child workspace, so captions for a clip are cut from the same words that were
recognised once.
"""

from __future__ import annotations

import logging
import shutil

from social_video.errors import ValidationError
from social_video.project_config import apply_contract_to_edl
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.config import BrandContract
from social_video.schemas.edl import EDL, EDLRange, ReframeMode
from social_video.schemas.plan import CandidateSet, ClipCandidate, ShortEntry, ShortsIndex
from social_video.schemas.source import SourceManifest
from social_video.workspace.layout import Workspace

log = logging.getLogger(__name__)

#: Anything shorter than this is a fragment, not a short.
MIN_SHORT_DURATION = 3.0


def load_candidates(workspace: Workspace) -> CandidateSet:
    if not workspace.candidate_set.is_file():
        raise ValidationError(
            f"no candidate set at {workspace.candidate_set}. Read the packed transcript and "
            "write candidates.json first: which spans stand alone, scored, with a reason each."
        )
    return load_artifact(CandidateSet, workspace.candidate_set)


def selected_candidates(
    candidates: CandidateSet, only: list[str] | None = None
) -> list[ClipCandidate]:
    """Selected means selected: an unreviewed candidate set produces nothing."""
    if only:
        by_id = {candidate.id: candidate for candidate in candidates.candidates}
        missing = [name for name in only if name not in by_id]
        if missing:
            known = ", ".join(sorted(by_id)) or "<none>"
            raise ValidationError(
                f"unknown candidate id(s): {', '.join(missing)}. Available: {known}"
            )
        return [by_id[name] for name in only]
    chosen = [candidate for candidate in candidates.candidates if candidate.selected]
    if not chosen:
        raise ValidationError(
            "no candidate is marked selected. Choosing which moments stand alone is an "
            "editorial decision; set selected: true on the ones you are keeping, or name "
            "them explicitly. Prefer fewer, better clips."
        )
    return chosen


def materialize_shorts(
    workspace: Workspace,
    *,
    only: list[str] | None = None,
    reframe: ReframeMode | None = None,
) -> ShortsIndex:
    """Give every selected candidate its own workspace and single-range EDL."""
    candidates = load_candidates(workspace)
    chosen = selected_candidates(candidates, only)
    if not workspace.source_manifest.is_file():
        raise ValidationError(f"no source manifest at {workspace.source_manifest}")
    manifest = load_artifact(SourceManifest, workspace.source_manifest)
    known_sources = {source.id for source in manifest.sources}
    contract = (
        load_artifact(BrandContract, workspace.brand_contract)
        if workspace.brand_contract.is_file()
        else None
    )

    entries: list[ShortEntry] = []
    for candidate in chosen:
        if candidate.source not in known_sources:
            raise ValidationError(
                f"candidate {candidate.id!r} names source {candidate.source!r}, which is not in "
                f"{workspace.source_manifest}. Known: {', '.join(sorted(known_sources))}"
            )
        if candidate.duration < MIN_SHORT_DURATION:
            raise ValidationError(
                f"candidate {candidate.id!r} is {candidate.duration:.1f}s; anything under "
                f"{MIN_SHORT_DURATION:.0f}s is a fragment, not a standalone short"
            )
        child = Workspace.at(workspace.candidates / _safe_id(candidate.id) / "edit").ensure()
        save_artifact(manifest, child.source_manifest)
        _reuse_transcripts(workspace, child)
        edl = EDL(
            name=_safe_id(candidate.id),
            ranges=[
                EDLRange(
                    source=candidate.source,
                    start=candidate.start,
                    end=candidate.end,
                    beat="HOOK",
                    quote=candidate.transcript[:200],
                    reason=candidate.reason or f"standalone moment: {candidate.topic}",
                )
            ],
            default_reframe=reframe or ReframeMode.FACE,
        )
        if contract is not None:
            edl = apply_contract_to_edl(edl, contract)
        save_artifact(edl, child.edl)
        save_artifact(candidate, child.root / "candidate.json")
        entries.append(
            ShortEntry(
                id=candidate.id,
                workspace=str(child.root),
                edl=str(child.edl),
                source=candidate.source,
                start=candidate.start,
                end=candidate.end,
                topic=candidate.topic,
            )
        )
        log.info("prepared short %s (%.1fs) in %s", candidate.id, candidate.duration, child.root)

    index = ShortsIndex(parent_workspace=str(workspace.root), shorts=entries)
    save_artifact(index, workspace.shorts_index)
    return index


def _reuse_transcripts(parent: Workspace, child: Workspace) -> None:
    """Copy the recognised words across. Never re-transcribe for a clip."""
    if not parent.transcripts.is_dir():
        return
    child.transcripts.mkdir(parents=True, exist_ok=True)
    for transcript in sorted(parent.transcripts.glob("*.json")):
        shutil.copy2(transcript, child.transcripts / transcript.name)


def _safe_id(value: str) -> str:
    """Candidate ids become directory names, so they may not escape one."""
    cleaned = "".join(char if char.isalnum() or char in "-_" else "-" for char in value).strip("-")
    if not cleaned:
        raise ValidationError(f"candidate id {value!r} does not produce a usable directory name")
    return cleaned[:60]


def shorts_summary(index: ShortsIndex) -> list[dict[str, object]]:
    return [
        {
            "id": entry.id,
            "topic": entry.topic,
            "duration": round(entry.end - entry.start, 2),
            "workspace": entry.workspace,
            "edl": entry.edl,
        }
        for entry in index.shorts
    ]
