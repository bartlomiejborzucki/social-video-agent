"""Stage orchestration.

Each stage reads and writes artifacts on disk, so a run is resumable: if
transcription succeeds and rendering fails, re-running does not re-transcribe.
Stages are individually callable from the CLI, which is how an agent drives
them one at a time while thinking in between.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from social_video.analysis.scenes import detect_scenes, scene_cut_times
from social_video.captions.ass import write_ass
from social_video.captions.chunk import build_caption_track
from social_video.captions.srt import write_srt
from social_video.editorial.compile import compile_plan
from social_video.editorial.draft import draft_edit_plan
from social_video.edl.render import QUALITIES, Quality, render_edl
from social_video.edl.timeline import Timeline
from social_video.ffmpeg.fonts import default_caption_font
from social_video.profiles import load_brand, load_profile
from social_video.qa.checks import check_render
from social_video.qa.contact_sheet import boundary_sheets
from social_video.reframe.plan import plan_reframe
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.brand import BrandProfile, OutputProfile
from social_video.schemas.captions import CaptionTrack
from social_video.schemas.edl import EDL, ReframeMode
from social_video.schemas.plan import EditPlan
from social_video.schemas.qa import QAReport
from social_video.schemas.source import SourceManifest
from social_video.schemas.transcript import Transcript
from social_video.sources import build_manifest
from social_video.transcribe.base import TranscriptionOptions
from social_video.transcribe.service import transcribe_source
from social_video.transcript.pack import pack_transcripts
from social_video.workspace.layout import Workspace

log = logging.getLogger(__name__)


def record_stage(workspace: Workspace, stage: str, detail: dict | None = None) -> None:
    """Persist stage completion so a later run can tell what is already done."""
    state: dict = {}
    if workspace.state.is_file():
        try:
            state = json.loads(workspace.state.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = {}
    state[stage] = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **(detail or {}),
    }
    workspace.state.parent.mkdir(parents=True, exist_ok=True)
    workspace.state.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def stage_ingest(source: Path, workspace: Workspace) -> SourceManifest:
    """Probe the sources and write the manifest."""
    workspace.ensure()
    manifest = build_manifest([source])
    save_artifact(manifest, workspace.source_manifest)
    record_stage(workspace, "ingest", {"sources": manifest.ids})
    return manifest


def stage_transcribe(
    source: Path,
    workspace: Workspace,
    *,
    options: TranscriptionOptions,
    backend: str | None = None,
    force: bool = False,
) -> Transcript:
    transcript = transcribe_source(
        source, workspace, options=options, backend_name=backend, force=force
    )
    pack_transcripts([transcript], output=workspace.packed_transcript)
    record_stage(
        workspace,
        "transcribe",
        {"provider": transcript.provider, "words": len(transcript.words)},
    )
    return transcript


def stage_analyze(source: Path, workspace: Workspace) -> list[float]:
    """Scene detection. Informs framing and cut placement; decides nothing."""
    scenes = detect_scenes(source)
    cuts = scene_cut_times(scenes)
    workspace.analysis.mkdir(parents=True, exist_ok=True)
    (workspace.analysis / f"{source.stem}.scenes.json").write_text(
        json.dumps(
            {"scenes": [{"start": s, "end": e} for s, e in scenes], "cuts": cuts},
            indent=2,
        ),
        encoding="utf-8",
    )
    record_stage(workspace, "analyze", {"scenes": len(scenes)})
    return cuts


def stage_plan(
    transcript: Transcript,
    workspace: Workspace,
    profile: OutputProfile,
    *,
    goal: str = "",
) -> EditPlan:
    plan = draft_edit_plan(transcript, profile, goal=goal)
    save_artifact(plan, workspace.edit_plan)
    record_stage(workspace, "plan", {"items": len(plan.items)})
    return plan


def stage_compile(
    plan: EditPlan,
    transcript: Transcript,
    workspace: Workspace,
    profile: OutputProfile,
    *,
    reframe: ReframeMode | None = None,
) -> EDL:
    edl = compile_plan(plan, transcript, profile, reframe_mode=reframe)
    save_artifact(edl, workspace.edl)
    record_stage(workspace, "compile", {"ranges": len(edl.ranges)})
    return edl


def stage_reframe(
    edl: EDL,
    manifest: SourceManifest,
    workspace: Workspace,
    *,
    scene_cuts: list[float] | None = None,
) -> EDL:
    """Attach a reframe plan to each range that needs one."""
    if edl.default_reframe is ReframeMode.FIT:
        return edl
    for rng in edl.ranges:
        if rng.reframe is not None:
            continue
        source = manifest.by_id(rng.source).resolved_path()
        rng.reframe = plan_reframe(
            source,
            start=rng.start,
            end=rng.end,
            out_width=edl.output_width,
            out_height=edl.output_height,
            mode=edl.default_reframe,
            scene_cuts=scene_cuts,
        )
    save_artifact(edl, workspace.edl)
    record_stage(workspace, "reframe", {"mode": edl.default_reframe.value})
    return edl


def stage_captions(
    transcript: Transcript,
    edl: EDL,
    workspace: Workspace,
    brand: BrandProfile,
) -> tuple[CaptionTrack, Path]:
    """Build caption data and render it to ASS, ready for the final burn-in."""
    timeline = Timeline(edl)
    track = build_caption_track(transcript, timeline, style=brand.captions)
    save_artifact(track, workspace.captions / f"{edl.name}.json")
    write_srt(track, workspace.captions / f"{edl.name}.srt")

    font = default_caption_font()
    if font is None:
        log.warning("no usable caption font found; captions may render incorrectly")
    ass_path = write_ass(
        track,
        brand.captions,
        workspace.captions / f"{edl.name}.ass",
        width=edl.output_width,
        height=edl.output_height,
        font_name=brand.captions.font_family or (font.family if font else None),
    )
    edl.captions = str(ass_path)
    save_artifact(edl, workspace.edl)
    record_stage(workspace, "captions", {"cues": len(track.cues)})
    return track, ass_path


def stage_render(
    edl: EDL,
    manifest: SourceManifest,
    workspace: Workspace,
    *,
    quality: str = "final",
    captions: Path | None = None,
) -> Path:
    q: Quality = QUALITIES[quality]
    out_dir = workspace.previews if quality != "final" else workspace.final
    output = out_dir / f"{edl.name}{'' if quality == 'final' else '_' + quality}.mp4"
    manifest_obj = render_edl(edl, manifest, output, quality=q, caption_file=captions)
    save_artifact(manifest_obj, workspace.renders / f"{output.stem}.manifest.json")
    record_stage(workspace, f"render:{quality}", {"output": str(output)})
    return output


def stage_qa(
    output: Path,
    edl: EDL,
    workspace: Workspace,
    *,
    captions: CaptionTrack | None = None,
    attempt: int = 1,
    sheets: bool = True,
) -> QAReport:
    report = check_render(output, edl, captions=captions, attempt=attempt)
    if sheets:
        boundaries = Timeline(edl).cut_boundaries()
        # Only generate stills where a check actually flagged something, or at
        # the cuts, rather than sampling the whole timeline.
        flagged = [c.at for c in report.checks if not c.passed and c.at is not None]
        targets = sorted({round(t, 2) for t in (*boundaries, *flagged)})[:12]
        if targets:
            made = boundary_sheets(output, targets, workspace.qa)
            log.info("wrote %d diagnostic sheet(s) to %s", len(made), workspace.qa)
    save_artifact(report, workspace.qa / f"{output.stem}.qa.json")
    record_stage(workspace, "qa", {"passed": report.passed, "attempt": attempt})
    return report


def run_edit(
    source: Path,
    workspace: Workspace,
    *,
    profile_name: str = "talking-head",
    brand_name: str = "default",
    quality: str = "final",
    options: TranscriptionOptions | None = None,
    backend: str | None = None,
    goal: str = "",
    reframe: ReframeMode | None = None,
    skip_captions: bool = False,
) -> tuple[Path, QAReport]:
    """The whole talking-head pipeline, end to end."""
    profile = load_profile(profile_name)
    brand = load_brand(brand_name)

    manifest = stage_ingest(source, workspace)
    transcript = stage_transcribe(
        source, workspace, options=options or TranscriptionOptions(), backend=backend
    )
    scene_cuts = stage_analyze(source, workspace)
    plan = stage_plan(transcript, workspace, profile, goal=goal)
    edl = stage_compile(plan, transcript, workspace, profile, reframe=reframe)
    edl = stage_reframe(edl, manifest, workspace, scene_cuts=scene_cuts)

    track: CaptionTrack | None = None
    caption_file: Path | None = None
    if profile.captions_enabled and not skip_captions:
        track, caption_file = stage_captions(transcript, edl, workspace, brand)

    output = stage_render(edl, manifest, workspace, quality=quality, captions=caption_file)
    report = stage_qa(output, edl, workspace, captions=track)
    return output, report


def load_workspace_artifacts(
    workspace: Workspace,
) -> tuple[SourceManifest, EDL]:
    """Read back what a previous stage wrote."""
    manifest = load_artifact(SourceManifest, workspace.source_manifest)
    edl = load_artifact(EDL, workspace.edl)
    return manifest, edl
