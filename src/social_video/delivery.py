"""Mechanical, immutable Stage 5 delivery variants."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from social_video.captions.srt import write_srt, write_vtt
from social_video.errors import ValidationError
from social_video.ffmpeg.run import run_ffmpeg
from social_video.pipeline import load_workspace_artifacts, stage_render
from social_video.qa.checks import check_render
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.captions import CaptionTrack
from social_video.schemas.config import BrandContract
from social_video.schemas.delivery import DeliveryItem, DeliveryManifest
from social_video.schemas.motion import MotionPlan
from social_video.schemas.workflow import Renderer
from social_video.workflow import load_workflow
from social_video.workspace.layout import Workspace


def deliver_workspace(
    workspace: Workspace,
    destination: Path | None,
    *,
    with_captions: bool,
    no_captions: bool,
    srt: bool,
    vtt: bool,
    poster: bool,
    resolutions: list[str] | None = None,
    allow_temporary: bool = False,
) -> DeliveryManifest:
    manifest, edl = load_workspace_artifacts(workspace)
    contract = (
        load_artifact(BrandContract, workspace.brand_contract)
        if workspace.brand_contract.is_file()
        else None
    )
    if destination is None and contract and contract.delivery_output:
        destination = Path(contract.delivery_output)
    if destination is None:
        raise ValidationError(
            "Stage 5 needs a durable --output directory or delivery_output in project config"
        )
    destination = destination.expanduser().resolve()
    if not allow_temporary and (destination == Path("/tmp") or Path("/tmp") in destination.parents):
        raise ValidationError("Stage 5 destination must be durable and cannot be under /tmp")
    destination.mkdir(parents=True, exist_ok=True)
    if not any((with_captions, no_captions, srt, vtt, poster, bool(resolutions))):
        raise ValidationError("select at least one delivery variant")

    before = _sha256(workspace.edl)
    caption_track, _caption_path = _captions(edl)
    items: list[DeliveryItem] = []
    workflow = load_workflow(workspace) if workspace.workflow_state.is_file() else None
    renderer = workflow.renderer if workflow else Renderer.FFMPEG
    motion_plan = (
        load_artifact(MotionPlan, workspace.motion_plan) if renderer is Renderer.REMOTION else None
    )
    attestation = workflow.remotion_license_attestation if workflow else None

    if with_captions:
        source = workspace.final / "final.mp4"
        if not source.is_file():
            raise ValidationError(f"approved final with captions does not exist: {source}")
        target = destination / "final.mp4"
        _copy_atomic(source, target)
        items.append(_video_item(target, edl, caption_track, destination))
    if no_captions:
        target = destination / "final-no-captions.mp4"
        clean_edl = edl.model_copy(deep=True)
        clean_edl.captions = None
        stage_render(
            clean_edl,
            manifest,
            workspace,
            quality="final",
            captions=None,
            output=target,
            renderer=renderer,
            motion_plan=motion_plan,
            remotion_license_attestation=attestation,
        )
        items.append(_video_item(target, clean_edl, None, destination))
    for resolution in resolutions or []:
        width, height = _parse_resolution(resolution)
        variant_edl = edl.model_copy(deep=True)
        variant_edl.output_width = width
        variant_edl.output_height = height
        target = destination / f"final-{width}x{height}.mp4"
        stage_render(
            variant_edl,
            manifest,
            workspace,
            quality="final",
            captions=_caption_path,
            output=target,
            renderer=renderer,
            motion_plan=motion_plan,
            remotion_license_attestation=attestation,
        )
        items.append(_video_item(target, variant_edl, caption_track, destination))
    if srt:
        if caption_track is None:
            raise ValidationError("cannot deliver SRT: structured caption JSON is missing")
        target = write_srt(caption_track, destination / "captions.srt")
        items.append(_file_item("captions", target, "srt"))
    if vtt:
        if caption_track is None:
            raise ValidationError("cannot deliver VTT: structured caption JSON is missing")
        target = write_vtt(caption_track, destination / "captions.vtt")
        items.append(_file_item("captions", target, "vtt"))
    if poster:
        source = destination / "final.mp4"
        if not source.is_file():
            source = destination / "final-no-captions.mp4"
        if not source.is_file():
            raise ValidationError("poster requires a delivered video variant")
        target = destination / "poster.jpg"
        run_ffmpeg(
            ["-y", "-ss", "0", "-i", str(source), "-frames:v", "1", "-q:v", "2", str(target)],
            desc="extract delivery poster",
        )
        items.append(_file_item("poster", target, "jpeg"))

    after = _sha256(workspace.edl)
    if before != after:
        raise ValidationError("Stage 5 changed edl.json; delivery was aborted")
    result = DeliveryManifest(
        workspace=str(workspace.root),
        destination=str(destination),
        edl_path=str(workspace.edl),
        edl_sha256_before=before,
        edl_sha256_after=after,
        items=items,
    )
    save_artifact(result, destination / "delivery-manifest.json")
    save_artifact(result, workspace.delivery_manifest)
    validate_delivery_manifest(result)
    return result


def validate_delivery_manifest(manifest: DeliveryManifest) -> None:
    if manifest.edl_sha256_before != manifest.edl_sha256_after:
        raise ValidationError("delivery manifest records a changed EDL")
    if _sha256(Path(manifest.edl_path)) != manifest.edl_sha256_after:
        raise ValidationError("current EDL hash no longer matches delivery manifest")
    for item in manifest.items:
        path = Path(item.path)
        if not path.is_file():
            raise ValidationError(f"delivered file is missing: {path}")
        if _sha256(path) != item.sha256:
            raise ValidationError(f"delivered file hash mismatch: {path}")
        if item.qa_report:
            report_path = Path(item.qa_report)
            if not report_path.is_file():
                raise ValidationError(f"delivery QA report is missing: {report_path}")
            if item.qa_report_sha256 != _sha256(report_path):
                raise ValidationError(f"delivery QA report hash mismatch: {report_path}")


def _captions(edl) -> tuple[CaptionTrack | None, Path | None]:
    if not edl.captions:
        return None, None
    path = Path(edl.captions)
    json_path = path if path.suffix.casefold() == ".json" else path.with_suffix(".json")
    return (load_artifact(CaptionTrack, json_path), path) if json_path.is_file() else (None, path)


def _video_item(path: Path, edl, captions: CaptionTrack | None, destination: Path) -> DeliveryItem:
    report = check_render(path, edl, captions=captions)
    report_path = destination / f"{path.stem}.qa.json"
    save_artifact(report, report_path)
    if not report.passed:
        raise ValidationError(f"delivery QA failed for {path}: {report.status}")
    return DeliveryItem(
        kind="video",
        path=str(path),
        size_bytes=path.stat().st_size,
        format="mp4",
        sha256=_sha256(path),
        qa_status=str(report.status),
        qa_report=str(report_path),
        qa_report_sha256=_sha256(report_path),
    )


def _file_item(kind: str, path: Path, format_name: str) -> DeliveryItem:
    return DeliveryItem(
        kind=kind,
        path=str(path),
        size_bytes=path.stat().st_size,
        format=format_name,
        sha256=_sha256(path),
        qa_status="not_applicable",
    )


def _copy_atomic(source: Path, target: Path) -> None:
    partial = target.with_suffix(target.suffix + ".partial")
    shutil.copy2(source, partial)
    partial.replace(target)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_resolution(value: str) -> tuple[int, int]:
    try:
        width_text, height_text = value.lower().split("x", 1)
        width, height = int(width_text), int(height_text)
    except ValueError as exc:
        raise ValidationError(f"invalid delivery resolution {value!r}; use WIDTHxHEIGHT") from exc
    if width <= 0 or height <= 0 or width % 2 or height % 2:
        raise ValidationError("delivery resolution must contain positive even dimensions")
    return width, height
