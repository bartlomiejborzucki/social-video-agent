"""Generate a plate into a workspace, with consent and provenance recorded."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from social_video.errors import ValidationError
from social_video.imagegen.providers import ImageProviderStatus, detect_image_provider
from social_video.imagegen.service import Transport, generate_plate
from social_video.imaging import sha256_file
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.config import BrandContract
from social_video.schemas.visuals import GeneratedVisual, VisualAssets, VisualKind
from social_video.workspace.layout import Workspace

CONSENT_HELP = (
    "Generating a plate sends your prompt text to a cloud image model. Enable it "
    "for this project with image_generation_policy: optional in the project config, "
    "or pass --allow-cloud-image for a one-off. Media, transcripts and brand assets "
    "are never uploaded either way."
)


def resolve_consent(
    contract: BrandContract | None, *, allow_flag: bool
) -> Literal["project_config", "explicit_flag"]:
    """Name the basis for this upload, or refuse. Silence is never consent."""
    if contract is not None and contract.image_generation_enabled:
        return "project_config"
    if allow_flag:
        return "explicit_flag"
    raise ValidationError(CONSENT_HELP)


def generate_workspace_plate(
    workspace: Workspace,
    kind: VisualKind,
    description: str,
    *,
    allow_flag: bool = False,
    width: int | None = None,
    height: int | None = None,
    status: ImageProviderStatus | None = None,
    transport: Transport | None = None,
) -> GeneratedVisual:
    """Draw one plate, write it into the workspace, and record where it came from."""
    contract = (
        load_artifact(BrandContract, workspace.brand_contract)
        if workspace.brand_contract.is_file()
        else None
    )
    consent = resolve_consent(contract, allow_flag=allow_flag)
    resolved = status or detect_image_provider()
    if not resolved.available or resolved.provider is None:
        raise ValidationError(
            f"no image provider is available: {resolved.reason}\n"
            "Compose the cover from a real frame and keep the end card typographic."
        )
    canvas_width = width or (contract.output_width if contract else 1080)
    canvas_height = height or (contract.output_height if contract else 1920)
    raw, prompt = generate_plate(
        resolved.provider,
        description,
        width=canvas_width,
        height=canvas_height,
        transport=transport,
    )
    workspace.generated.mkdir(parents=True, exist_ok=True)
    target = workspace.generated / f"{kind.value}.png"
    _write_atomic(target, raw)
    from PIL import Image

    with Image.open(target) as image:
        size = image.size
    visual = GeneratedVisual(
        kind=kind,
        provider=resolved.provider.name,
        model=resolved.provider.model,
        prompt=prompt,
        path=str(target),
        width=size[0],
        height=size[1],
        sha256=sha256_file(target),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        consent=consent,
        cost_note=resolved.provider.cost_note,
    )
    _record(workspace, visual)
    return visual


def _record(workspace: Workspace, visual: GeneratedVisual) -> None:
    assets = (
        load_artifact(VisualAssets, workspace.visual_assets)
        if workspace.visual_assets.is_file()
        else VisualAssets()
    )
    assets.visuals = [item for item in assets.visuals if item.kind is not visual.kind]
    assets.visuals.append(visual)
    save_artifact(assets, workspace.visual_assets)


def _write_atomic(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.partial")
    try:
        partial.write_bytes(data)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
