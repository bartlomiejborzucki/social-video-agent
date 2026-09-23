"""Put a plate into a workspace, with consent and provenance recorded.

Two routes arrive here. This CLI can draw a plate itself when an API
credential is present. Or the agent calls its host's own image tool -- which no
Python process can invoke -- and registers the resulting file. The second route
is a registration, not a pretence that this code generated anything: the
provenance record names the tool that really drew it, and leaves the model
empty when the tool does not disclose one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from social_video.errors import ValidationError
from social_video.fsutil import atomic_target, atomic_write_bytes, utc_timestamp
from social_video.imagegen.providers import ImageProviderStatus, detect_image_provider
from social_video.imagegen.service import (
    Transport,
    build_prompt,
    generate_plate,
    strip_guardrail,
)
from social_video.imaging import sha256_file
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.config import BrandContract
from social_video.schemas.visuals import (
    GeneratedVisual,
    ImageProviderName,
    ImageTool,
    VisualAssets,
    VisualKind,
)
from social_video.workspace.layout import Workspace

#: Which tool draws for which provider. The pairing is fixed, so a provenance
#: record cannot claim the native tool drew an OpenAI API image.
_TOOLS = {
    ImageProviderName.CHATGPT_NATIVE: ImageTool.NATIVE_IMAGEGEN,
    ImageProviderName.OPENAI_API: ImageTool.OPENAI_IMAGES_API,
    ImageProviderName.GEMINI_API: ImageTool.GEMINI_GENERATE_CONTENT,
}

CONSENT_HELP = (
    "Generating a plate sends your prompt text to a cloud image model. That is true "
    "of the agent's own native image tool as well: the prompt still leaves the "
    "machine. Enable it for this project with image_generation_policy: optional in "
    "the project config, pass --allow-cloud-image for a one-off, or pass "
    "--consent user-request when the user asked for this specific image in so many "
    "words. Media, transcripts and brand assets are never uploaded either way."
)

Consent = Literal["project_config", "explicit_flag", "user_request"]


def resolve_consent(
    contract: BrandContract | None,
    *,
    allow_flag: bool = False,
    user_request: bool = False,
) -> Consent:
    """Name the basis for this upload, or refuse. Silence is never consent.

    A project whose policy is `none` refuses every basis, including a native
    tool and including a direct request: the policy is the project's standing
    decision, and a one-off cannot overrule it.
    """
    if contract is not None and not contract.image_generation_enabled:
        raise ValidationError(
            "image_generation_policy is 'none' for this project, so no image may be "
            "generated or registered -- by this CLI, by the agent's native image tool, "
            "or by anything else. Change the policy deliberately if that is wrong.\n" + CONSENT_HELP
        )
    if contract is not None and contract.image_generation_enabled:
        return "project_config"
    if allow_flag:
        return "explicit_flag"
    if user_request:
        # Covers the image the user asked for, and not the next one.
        return "user_request"
    raise ValidationError(CONSENT_HELP)


def generate_workspace_plate(
    workspace: Workspace,
    kind: VisualKind,
    description: str,
    *,
    allow_flag: bool = False,
    user_request: bool = False,
    purpose: str = "",
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
    consent = resolve_consent(contract, allow_flag=allow_flag, user_request=user_request)
    resolved = status or detect_image_provider()
    if not resolved.available or resolved.provider is None:
        raise ValidationError(
            f"this CLI cannot draw a plate itself: {resolved.reason}\n"
            "If the agent has a native image tool, call it and register the file with "
            "`image register`. Otherwise compose the cover from a real frame and keep "
            "the end card typographic."
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
        tool=_TOOLS[resolved.provider.name],
        model=resolved.provider.model,
        prompt=prompt,
        path=str(target),
        width=size[0],
        height=size[1],
        sha256=sha256_file(target),
        created_at=utc_timestamp(),
        consent=consent,
        purpose=purpose,
        cost_note=resolved.provider.cost_note,
    )
    _record(workspace, visual)
    return visual


def register_visual(
    workspace: Workspace,
    kind: VisualKind,
    source: Path,
    *,
    prompt: str,
    provider: ImageProviderName = ImageProviderName.CHATGPT_NATIVE,
    model: str | None = None,
    allow_flag: bool = False,
    user_request: bool = False,
    purpose: str = "",
) -> GeneratedVisual:
    """Adopt a file the agent's own image tool produced.

    The native tool is the agent's, not this process's, so this function does
    not pretend to have called anything. It records what the agent says it
    used, copies the file into the workspace so the edit is self-contained, and
    hashes it. ``model`` stays empty unless the tool actually reported one:
    a plausible-looking model name in a provenance record is a lie.
    """
    contract = (
        load_artifact(BrandContract, workspace.brand_contract)
        if workspace.brand_contract.is_file()
        else None
    )
    consent = resolve_consent(contract, allow_flag=allow_flag, user_request=user_request)
    original = Path(source).expanduser()
    if not original.is_file():
        raise ValidationError(f"no such image to register: {original}")
    guarded = build_prompt(strip_guardrail(prompt))
    from PIL import Image

    try:
        with Image.open(original) as image:
            image.load()
            size = image.size
            data = image.convert("RGB")
            workspace.generated.mkdir(parents=True, exist_ok=True)
            target = workspace.generated / f"{kind.value}{_suffix(original)}"
            _write_image(target, data, original)
    except OSError as exc:
        raise ValidationError(f"{original} is not a readable image: {exc}") from exc
    visual = GeneratedVisual(
        kind=kind,
        provider=provider,
        tool=_TOOLS[provider],
        model=(model or None),
        prompt=guarded,
        path=str(target),
        width=size[0],
        height=size[1],
        sha256=sha256_file(target),
        created_at=utc_timestamp(),
        consent=consent,
        purpose=purpose,
        source_path=str(original),
    )
    _record(workspace, visual)
    return visual


_FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}


def _suffix(original: Path) -> str:
    suffix = original.suffix.casefold()
    return suffix if suffix in {".png", ".jpg", ".jpeg", ".webp"} else ".png"


def _write_image(target: Path, data, original: Path) -> None:
    """Copy the pixels, not the file: a stray EXIF payload is not wanted."""
    with atomic_target(target) as partial:
        # The staging name hides the real extension, so Pillow is told the
        # format rather than left to guess it from ``.partial``.
        suffix = _suffix(original)
        if suffix == ".png":
            data.save(partial, format="PNG", optimize=True)
        else:
            data.save(partial, format=_FORMATS[suffix], quality=95)


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
    atomic_write_bytes(target, data)
