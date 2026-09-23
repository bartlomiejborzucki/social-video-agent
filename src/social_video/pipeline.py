"""Stage orchestration.

Each stage reads and writes artifacts on disk, so a run is resumable: if
transcription succeeds and rendering fails, re-running does not re-transcribe.
Stages are individually callable from the CLI, which is how an agent drives
them one at a time while thinking in between.
"""

from __future__ import annotations

import json
import logging
from fractions import Fraction
from pathlib import Path

from social_video.analysis.scenes import detect_scenes, scene_cut_times
from social_video.captions.ass import write_ass
from social_video.captions.chunk import build_caption_track
from social_video.captions.features import (
    CAPTION_LAYOUT_ESTIMATED,
    CAPTION_LAYOUT_MEASURED,
    caption_features,
    highlight_possible,
)
from social_video.captions.srt import write_srt
from social_video.editorial.compile import compile_plan
from social_video.editorial.draft import draft_edit_plan
from social_video.edl.render import QUALITIES, Quality, render_edl
from social_video.edl.timeline import Timeline
from social_video.errors import ValidationError
from social_video.ffmpeg.fonts import default_caption_font
from social_video.ffmpeg.probe import probe
from social_video.fsutil import utc_timestamp
from social_video.profiles import load_brand, load_profile
from social_video.qa.checks import check_render
from social_video.qa.contact_sheet import boundary_sheets, contact_sheet
from social_video.reframe.plan import plan_reframe
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.brand import BrandProfile, OutputProfile
from social_video.schemas.captions import CaptionTrack
from social_video.schemas.config import BrandContract
from social_video.schemas.edl import EDL, ReframeMode
from social_video.schemas.motion import MotionPlan
from social_video.schemas.plan import EditPlan
from social_video.schemas.qa import QACheck, QAReport, QASeverity, RenderManifest
from social_video.schemas.source import SourceManifest
from social_video.schemas.transcript import Transcript
from social_video.schemas.workflow import RemotionLicenseAttestation, Renderer
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
        "at": utc_timestamp(),
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
    # Pack every transcript in the workspace, not just this one: a project with
    # several sources would otherwise lose the others from the agent's view
    # each time a new source was transcribed.
    _repack(workspace)
    record_stage(
        workspace,
        "transcribe",
        {"provider": transcript.provider, "words": len(transcript.words)},
    )
    return transcript


def _repack(workspace: Workspace) -> None:
    """Rebuild the packed transcript from everything in the workspace."""
    transcripts = []
    for path in sorted(workspace.transcripts.glob("*.json")):
        try:
            transcripts.append(load_artifact(Transcript, path))
        except ValidationError as exc:
            log.warning("skipping unreadable transcript %s: %s", path.name, exc)
    if transcripts:
        pack_transcripts(transcripts, output=workspace.packed_transcript)


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
    if workspace.project_context.is_file():
        from social_video.schemas.project_context import ProjectContext

        context = load_artifact(ProjectContext, workspace.project_context)
        plan.style_sources = context.style_sources
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
    if workspace.brand_contract.is_file():
        from social_video.project_config import apply_contract_to_edl

        contract = load_artifact(BrandContract, workspace.brand_contract)
        edl = apply_contract_to_edl(edl, contract)
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
        source = manifest.by_id(rng.effective_video_source).resolved_path()
        rng.reframe = plan_reframe(
            source,
            start=rng.effective_video_start,
            end=rng.visual_content_end,
            out_width=edl.output_width,
            out_height=edl.output_height,
            mode=edl.default_reframe,
            scene_cuts=scene_cuts,
            # Speaker detection correlates mouth movement with the audio that was
            # transcribed, which is not always the video file's own first track.
            audio_source=manifest.by_id(rng.effective_audio_source).resolved_path(),
            turns=_speaker_turns(workspace, rng),
        )
    save_artifact(edl, workspace.edl)
    record_stage(workspace, "reframe", {"mode": edl.default_reframe.value})
    return edl


def _speaker_turns(workspace: Workspace, rng) -> list[tuple[float, float, str]] | None:
    """Diarized turns for a range, when its picture and sound share a clock.

    Turns are in the audio source's time. They only describe the picture when
    the video comes from the same file at the same offset.
    """
    from social_video.transcribe.diarize import turns_from_transcript

    same_clock = (
        rng.effective_audio_source == rng.effective_video_source
        and abs(rng.effective_audio_start - rng.effective_video_start) < 1e-3
    )
    path = workspace.transcript_for(rng.effective_audio_source, rng.audio_track)
    if not same_clock or not path.is_file():
        return None
    turns = turns_from_transcript(load_artifact(Transcript, path))
    return [(turn.start, turn.end, turn.speaker) for turn in turns] or None


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


def load_workspace_brand(workspace: Workspace, fallback: str = "default") -> BrandProfile:
    if workspace.brand_contract.is_file():
        contract = load_artifact(BrandContract, workspace.brand_contract)
        contract.validate_assets()
        return contract.brand
    return load_brand(fallback)


def stage_render(
    edl: EDL,
    manifest: SourceManifest,
    workspace: Workspace,
    *,
    quality: str = "final",
    captions: Path | None = None,
    output: Path | None = None,
    renderer: Renderer = Renderer.FFMPEG,
    motion_plan: MotionPlan | None = None,
    remotion_license_attestation: RemotionLicenseAttestation | None = None,
    audio_cleanup: bool = True,
) -> Path:
    contract: BrandContract | None = None
    if workspace.brand_contract.is_file():
        contract = load_artifact(BrandContract, workspace.brand_contract)
        contract.validate_assets()
        if edl.brand_profile != contract.project_config_sha256:
            raise ValidationError(
                "EDL brand_profile does not match the compiled project brand contract; "
                "recompile Stage 2 before rendering"
            )
    elif edl.brand_profile:
        # Backward-compatible named profiles remain supported; arbitrary names do not.
        load_brand(edl.brand_profile)
    if contract is not None:
        _check_audio_policy(edl, contract)
        _check_movement(edl, motion_plan if renderer is Renderer.REMOTION else None, contract)
    # A rounded caption box on the FFmpeg route is drawn by libass from the
    # same measured layout the Remotion compositor uses.
    rounded_on_ffmpeg = (
        renderer is Renderer.FFMPEG
        and contract is not None
        and captions is not None
        and contract.brand.captions.background_style.value == "rounded_box"
    )
    q: Quality = QUALITIES[quality]
    out_dir = workspace.previews if quality != "final" else workspace.final
    output = output or out_dir / ("final.mp4" if quality == "final" else "preview.mp4")
    render_target = output
    if renderer is Renderer.REMOTION:
        if remotion_license_attestation is None:
            raise ValidationError("Remotion rendering requires a saved license attestation")
        if motion_plan is None:
            raise ValidationError(
                f"Remotion is enabled but MotionPlan was not provided ({workspace.motion_plan})"
            )
        render_target = workspace.cache / "remotion" / f"base-{quality}.mp4"
    caption_track: CaptionTrack | None = None
    remotion_caption_style = None
    base_captions = captions
    if captions is not None and contract is not None:
        json_path = captions.with_suffix(".json")
        if renderer is Renderer.REMOTION and not json_path.is_file():
            raise ValidationError(
                f"caption data required for branded Remotion captions is missing: {json_path}"
            )
        if json_path.is_file():
            caption_track = load_artifact(CaptionTrack, json_path)
        if renderer is Renderer.REMOTION:
            remotion_caption_style = contract.brand.captions
            base_captions = None
    caption_fonts_dir: Path | None = None
    boxed_layout = None
    if rounded_on_ffmpeg:
        assert contract is not None and captions is not None
        base_captions, boxed_layout, caption_fonts_dir = _rounded_box_captions(
            captions, contract, edl, workspace
        )
        caption_track = load_artifact(CaptionTrack, captions.with_suffix(".json"))
    # The project decides whether the voice is repaired; `audio_cleanup=False`
    # is the per-render escape hatch, so one render can be compared with the
    # untouched audio without editing the contract.
    cleanup_policy = (
        contract.audio_cleanup_policy if contract is not None and audio_cleanup else "none"
    )
    manifest_obj = render_edl(
        edl,
        manifest,
        render_target,
        quality=q,
        caption_file=base_captions,
        audio_cleanup_policy=cleanup_policy,
        caption_fonts_dir=caption_fonts_dir,
    )
    if renderer is Renderer.REMOTION:
        from social_video.remotion import render_motion_design

        assert motion_plan is not None  # checked before the technical base render
        base_info = probe(render_target)
        if base_info.video is None:
            raise ValidationError("technical base render has no video stream")
        rate = float(Fraction(manifest_obj.frame_rate))
        duration_in_frames = (
            base_info.video.nb_frames
            if base_info.video.nb_frames is not None
            else round(manifest_obj.duration * rate)
        )
        render_plan = motion_plan.model_copy(deep=True)
        if contract is not None:
            render_plan.font_family = contract.brand.captions.font_family
            render_plan.font_path = contract.resolved_font_file
            render_plan.accent_color = contract.brand.accent_colour
            render_plan.text_color = contract.brand.captions.primary_colour
            render_plan.background_color = contract.brand.background_colour
        _rendered, applied_caption_features, caption_layout = render_motion_design(
            render_target,
            output,
            render_plan,
            duration_in_frames=duration_in_frames,
            fps=rate,
            width=base_info.video.width,
            height=base_info.video.height,
            staging_root=workspace.cache / "remotion",
            captions=caption_track,
            caption_style=remotion_caption_style,
            logo_path=(
                Path(contract.resolved_logo_file)
                if contract and contract.resolved_logo_file
                else None
            ),
            logo_usage=contract.brand.logo_usage if contract else "none",
            safe_margins=contract.safe_margins if contract else None,
        )
        final_info = probe(output)
        manifest_obj.output = str(output)
        manifest_obj.duration = final_info.duration
        if final_info.video is None:
            raise ValidationError("Remotion output has no video stream")
        manifest_obj.width = final_info.video.width
        manifest_obj.height = final_info.video.height
        from social_video.remotion_runtime import locate_runtime

        runtime = locate_runtime()
        manifest_obj.tool_versions["remotion"] = runtime.locked_version if runtime else "unknown"
    else:
        # libass draws the ASS track; it honours the same contracted features.
        # A plain track wraps inside libass, so there is no measured layout to
        # record; a rounded-box track was laid out here and records its layout.
        caption_layout = boxed_layout
        style = contract.brand.captions if contract else None
        applied_caption_features = caption_features(
            style,
            caption_track,
            highlight=highlight_possible(style, caption_track),
        )
        if boxed_layout is not None:
            applied_caption_features.append(
                CAPTION_LAYOUT_MEASURED if boxed_layout.measured else CAPTION_LAYOUT_ESTIMATED
            )
    if contract is not None:
        manifest_obj.brand_contract_sha256 = contract.project_config_sha256
        manifest_obj.caption_style = contract.brand.captions.model_dump(
            mode="json", exclude={"schema_version"}
        )
        manifest_obj.caption_renderer = (
            ("remotion" if renderer is Renderer.REMOTION else "libass")
            if captions is not None
            else ""
        )
        manifest_obj.caption_features = applied_caption_features if captions is not None else []
        if caption_layout is not None and captions is not None:
            manifest_obj.caption_layout = caption_layout.evidence()
    manifest_obj.captions_burned = captions is not None
    manifest_obj.logo_applied = bool(
        contract
        and contract.resolved_logo_file
        and contract.brand.logo_usage != "none"
        and renderer is Renderer.REMOTION
    )
    manifest_obj.brand_safe_margins = contract.safe_margins if contract else {}
    save_artifact(manifest_obj, workspace.renders / f"{output.stem}.manifest.json")
    record_stage(
        workspace,
        f"render:{quality}",
        {"output": str(output), "renderer": renderer.value},
    )
    return output


def _rounded_box_captions(captions: Path, contract: BrandContract, edl: EDL, workspace: Workspace):
    """Lay out the caption track and write it as a rounded-box ASS document."""
    from social_video.captions.ass import render_boxed_ass
    from social_video.captions.fit import layout_captions
    from social_video.ffmpeg.fonts import font_family_name
    from social_video.fsutil import atomic_write_bytes

    json_path = captions.with_suffix(".json")
    if not json_path.is_file():
        raise ValidationError(
            f"caption data required to draw rounded caption boxes is missing: {json_path}"
        )
    track = load_artifact(CaptionTrack, json_path)
    style = contract.brand.captions
    font_file = Path(contract.resolved_font_file) if contract.resolved_font_file else None
    layout = layout_captions(
        list(track.cues),
        style,
        width=edl.output_width,
        height=edl.output_height,
        safe_margins=contract.safe_margins,
        font_file=font_file,
    )
    document = render_boxed_ass(
        track,
        style,
        layout,
        width=edl.output_width,
        height=edl.output_height,
        safe_margins=contract.safe_margins,
        font_name=(font_family_name(font_file) if font_file else None) or style.font_family,
    )
    target = workspace.cache / "captions" / f"{captions.stem}.rounded.ass"
    atomic_write_bytes(target, document.encode("utf-8"))
    return target, layout, (font_file.parent if font_file else None)


def _check_movement(edl: EDL, plan: MotionPlan | None, contract: BrandContract) -> None:
    """Hold every zoom -- a range's static one and a timed punch-in -- to the brand."""
    limit = contract.brand.punch_in_max
    problems = [
        f"range {index} zooms to {rng.zoom:g}, above the brand limit {limit:g}"
        for index, rng in enumerate(edl.ranges)
        if rng.zoom > limit + 1e-9
    ]
    if plan is not None:
        problems += plan.punch_in_problems(limit=limit, intensity=contract.brand.motion_intensity)
    if problems:
        raise ValidationError(
            "movement exceeds the project's brand contract:\n"
            + "\n".join(f"  - {p}" for p in problems)
        )


def _check_audio_policy(edl: EDL, contract: BrandContract) -> None:
    """Make music_policy and sfx_policy executable instead of decorative."""
    if edl.audio_bed is not None and contract.music_policy == "none":
        raise ValidationError(
            "this EDL mixes a music bed, but the project config sets music_policy: none. "
            "Set music_policy: optional to allow it, or remove audio_bed."
        )
    if edl.audio_bed is None and contract.music_policy == "required":
        raise ValidationError(
            "the project config sets music_policy: required, but this EDL has no audio_bed"
        )
    if edl.sound_effects and contract.sfx_policy == "none":
        raise ValidationError(
            "this EDL places sound effects, but the project config sets sfx_policy: none"
        )
    if not edl.sound_effects and contract.sfx_policy == "required":
        raise ValidationError(
            "the project config sets sfx_policy: required, but this EDL places no effects"
        )


def stage_qa(
    output: Path,
    edl: EDL,
    workspace: Workspace,
    *,
    captions: CaptionTrack | None = None,
    attempt: int = 1,
    sheets: bool = True,
    platforms: list[str] | None = None,
) -> QAReport:
    caption_problem: str | None = None
    if captions is None and edl.captions:
        captions, caption_problem = resolve_caption_track(Path(edl.captions))
    report = check_render(output, edl, captions=captions, attempt=attempt)
    if caption_problem:
        report.checks.append(
            QACheck(
                name="caption QA data available",
                severity=QASeverity.ERROR,
                passed=False,
                message=caption_problem,
            )
        )
    elif edl.captions:
        report.checks.append(
            QACheck(
                name="caption QA data available",
                severity=QASeverity.INFO,
                passed=True,
                message="structured caption JSON was loaded",
            )
        )
    if sheets:
        boundaries = Timeline(edl).cut_boundaries()
        # Only generate stills where a check actually flagged something, or at
        # the cuts, rather than sampling the whole timeline.
        flagged = [c.at for c in report.checks if not c.passed and c.at is not None]
        ending_starts = [
            c.at for c in report.checks if c.name == "ending visual continuity" and c.at is not None
        ]
        targets = sorted({round(t, 2) for t in (*boundaries, *flagged, *ending_starts)})[:12]
        if targets:
            made = boundary_sheets(output, targets, workspace.qa)
            report.artifacts.extend(str(path) for path in made)
            log.info("wrote %d diagnostic sheet(s) to %s", len(made), workspace.qa)
        privacy_targets: set[float] = set()
        timeline = Timeline(edl)
        for sl in timeline.slices:
            limit = sl.range.max_visual_source_time
            if limit is None:
                continue
            at = sl.output_start + max(
                0.0, (limit - sl.range.effective_video_start) / sl.range.speed
            )
            privacy_targets.update(
                {
                    max(0.0, at - 0.25),
                    max(0.0, at - 0.04),
                    at,
                    at + 0.04,
                    at + 0.25,
                    max(0.0, timeline.duration - 1.0),
                    timeline.duration,
                }
            )
        if privacy_targets:
            privacy_dir = workspace.qa / "privacy-review"
            made = boundary_sheets(output, sorted(privacy_targets), privacy_dir, window=0.04)
            report.artifacts.extend(str(path) for path in made)
        ending_sheet = contact_sheet(
            output,
            workspace.qa / "ending-contact-sheet.png",
            start=max(0.0, probe(output).duration - 10.0),
            columns=5,
            rows=4,
            tile_width=240,
        )
        report.artifacts.append(str(ending_sheet))
        # The hook decides whether anything after it is watched, so it gets the
        # same dense treatment the ending already had.
        opening_sheet = contact_sheet(
            output,
            workspace.qa / "opening-contact-sheet.png",
            start=0.0,
            end=min(3.0, probe(output).duration),
            columns=5,
            rows=2,
            tile_width=240,
        )
        report.artifacts.append(str(opening_sheet))
    contract_for_platform = (
        load_artifact(BrandContract, workspace.brand_contract)
        if workspace.brand_contract.is_file()
        else None
    )
    configured = contract_for_platform.target_platforms if contract_for_platform else []
    requested = platforms or configured
    if requested:
        from social_video.profiles import load_platform
        from social_video.qa.platform import platform_checks

        info = probe(output)
        for name in requested:
            report.checks.extend(
                platform_checks(
                    load_platform(name),
                    duration=info.duration,
                    width=info.video.width if info.video else None,
                    height=info.video.height if info.video else None,
                    contract=contract_for_platform,
                )
            )
    save_artifact(report, workspace.qa / "qa-report.json")
    save_artifact(report, workspace.technical_qa)
    if workspace.brand_contract.is_file():
        from social_video.qa.brand import check_brand

        contract = load_artifact(BrandContract, workspace.brand_contract)
        manifest_path = workspace.renders / f"{output.stem}.manifest.json"
        render_manifest = load_artifact(RenderManifest, manifest_path)
        brand_report = check_brand(
            output,
            contract,
            render_manifest,
            accepted_deviations=set(edl.accepted_qa_warnings),
        )
        save_artifact(brand_report, workspace.brand_qa)
    record_stage(
        workspace,
        "qa",
        {"passed": report.passed, "status": report.status, "attempt": attempt},
    )
    return report


def resolve_caption_track(caption_source: Path) -> tuple[CaptionTrack | None, str | None]:
    """Resolve JSON directly or the structured peer of SRT/ASS for QA."""
    suffix = caption_source.suffix.casefold()
    if suffix not in {".json", ".srt", ".ass"}:
        return None, f"unsupported caption artifact for QA: {caption_source}"
    if suffix != ".json" and not caption_source.is_file():
        return None, f"configured caption artifact is missing: {caption_source}"
    json_path = caption_source if suffix == ".json" else caption_source.with_suffix(".json")
    if not json_path.is_file():
        return (
            None,
            f"caption QA data is missing: {json_path}; the configured {suffix} "
            "artifact cannot be checked",
        )
    track = load_artifact(CaptionTrack, json_path)
    if suffix != ".json":
        text = caption_source.read_text(encoding="utf-8", errors="replace")
        derived_count = (
            text.count("-->")
            if suffix == ".srt"
            else sum(line.startswith("Dialogue:") for line in text.splitlines())
        )
        if derived_count != len(track.cues):
            return (
                None,
                f"caption artifacts are inconsistent: {caption_source} has "
                f"{derived_count} cue(s), {json_path} has {len(track.cues)}",
            )
    return track, None


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
    force: bool = False,
) -> tuple[Path, QAReport]:
    """The whole talking-head pipeline, end to end."""
    profile = load_profile(profile_name)
    brand = load_workspace_brand(workspace, brand_name)

    manifest = stage_ingest(source, workspace)
    transcript = stage_transcribe(
        source,
        workspace,
        options=options or TranscriptionOptions(),
        backend=backend,
        force=force,
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
