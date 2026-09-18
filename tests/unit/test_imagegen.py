"""Provider detection, consent, and the no-text guardrail. Never hits the network."""

from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from social_video.errors import ImageGenerationError, ValidationError
from social_video.imagegen import (
    build_prompt,
    detect_image_provider,
    generate_plate,
    generate_workspace_plate,
)
from social_video.schemas.base import load_artifact
from social_video.schemas.visuals import ImageProviderName, VisualAssets, VisualKind
from social_video.workspace.layout import Workspace


def _png(size: tuple[int, int] = (1024, 1536)) -> str:
    buffer = BytesIO()
    Image.new("RGB", size, (12, 18, 24)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_claude_host_without_keys_explains_why_there_is_no_image_api() -> None:
    status = detect_image_provider({"CLAUDECODE": "1"})
    assert not status.available
    assert status.host == "claude"
    assert "no image-generation api" in status.reason.casefold()


def test_a_chatgpt_plan_alone_is_not_api_access() -> None:
    status = detect_image_provider({"CODEX_HOME": "/home/x/.codex"})
    assert not status.available
    assert "does not include api image generation" in status.reason.casefold()


def test_codex_host_prefers_openai_and_gemini_cli_prefers_gemini() -> None:
    both = {"GEMINI_API_KEY": "g", "OPENAI_API_KEY": "o"}
    codex = detect_image_provider({**both, "CODEX_HOME": "/x"})
    gemini = detect_image_provider({**both, "GEMINI_CLI": "1"})
    assert codex.provider is not None and codex.provider.name is ImageProviderName.OPENAI
    assert gemini.provider is not None and gemini.provider.name is ImageProviderName.GEMINI


def test_without_a_host_hint_the_free_tier_wins() -> None:
    status = detect_image_provider({"GEMINI_API_KEY": "g", "OPENAI_API_KEY": "o"})
    assert status.provider is not None
    assert status.provider.name is ImageProviderName.GEMINI


def test_explicit_override_can_disable_or_select() -> None:
    off = detect_image_provider({"SOCIAL_VIDEO_IMAGE_PROVIDER": "none", "GEMINI_API_KEY": "g"})
    assert not off.available
    missing = detect_image_provider({"SOCIAL_VIDEO_IMAGE_PROVIDER": "openai"})
    assert not missing.available and "OPENAI_API_KEY" in missing.reason
    unknown = detect_image_provider({"SOCIAL_VIDEO_IMAGE_PROVIDER": "midjourney"})
    assert not unknown.available and "not supported" in unknown.reason


def test_the_api_key_never_appears_in_the_reported_status() -> None:
    status = detect_image_provider({"OPENAI_API_KEY": "sk-secret-value"})
    assert "sk-secret-value" not in json.dumps(status.to_dict())


def test_the_guardrail_bans_text_and_refuses_pasted_content() -> None:
    prompt = build_prompt("spokojne studio, ciepłe światło")
    assert "no text" in prompt and "no human faces" in prompt
    with pytest.raises(ValidationError):
        build_prompt("x" * 2000)


def test_a_gemini_plate_records_exactly_the_prompt_that_was_sent() -> None:
    status = detect_image_provider({"GEMINI_API_KEY": "g"})
    assert status.provider is not None
    sent: dict[str, str] = {}

    def transport(url: str, payload: dict, headers: dict) -> dict:
        sent["prompt"] = payload["contents"][0]["parts"][0]["text"]
        sent["key"] = headers["x-goog-api-key"]
        return {"candidates": [{"content": {"parts": [{"inlineData": {"data": _png()}}]}}]}

    raw, prompt = generate_plate(
        status.provider, "kontrastowe tło", width=1080, height=1920, transport=transport
    )
    assert raw.startswith(b"\x89PNG")
    assert prompt == sent["prompt"]
    assert "vertical 9:16" in prompt
    assert sent["key"] == "g"


def test_openai_portrait_requests_the_closest_supported_shape() -> None:
    status = detect_image_provider({"OPENAI_API_KEY": "o"})
    assert status.provider is not None
    seen: dict[str, str] = {}

    def transport(url: str, payload: dict, headers: dict) -> dict:
        seen["size"] = payload["size"]
        return {"data": [{"b64_json": _png()}]}

    generate_plate(status.provider, "tło", width=1080, height=1920, transport=transport)
    assert seen["size"] == "1024x1536"


def test_a_provider_error_surfaces_the_providers_own_message() -> None:
    status = detect_image_provider({"OPENAI_API_KEY": "o"})
    assert status.provider is not None
    with pytest.raises(ImageGenerationError, match="billing hard limit"):
        generate_plate(
            status.provider,
            "tło",
            width=1080,
            height=1920,
            transport=lambda *_: {"error": {"message": "billing hard limit reached"}},
        )


def test_a_non_image_payload_fails_before_it_reaches_the_workspace() -> None:
    status = detect_image_provider({"OPENAI_API_KEY": "o"})
    assert status.provider is not None
    junk = base64.b64encode(b"not an image").decode("ascii")
    with pytest.raises(ImageGenerationError, match="readable image"):
        generate_plate(
            status.provider,
            "tło",
            width=1080,
            height=1920,
            transport=lambda *_: {"data": [{"b64_json": junk}]},
        )


def test_generation_refuses_without_consent_and_records_provenance_with_it(
    tmp_path: Path,
) -> None:
    workspace = Workspace.at(tmp_path / "edit").ensure()
    status = detect_image_provider({"OPENAI_API_KEY": "o"})

    def transport(url: str, payload: dict, headers: dict) -> dict:
        return {"data": [{"b64_json": _png()}]}

    with pytest.raises(ValidationError, match="allow-cloud-image"):
        generate_workspace_plate(
            workspace,
            VisualKind.COVER_PLATE,
            "tło",
            status=status,
            transport=transport,
        )

    visual = generate_workspace_plate(
        workspace,
        VisualKind.COVER_PLATE,
        "tło",
        allow_flag=True,
        status=status,
        transport=transport,
    )
    assert visual.consent == "explicit_flag"
    assert Path(visual.path).is_file()
    assert len(visual.sha256) == 64
    recorded = load_artifact(VisualAssets, workspace.visual_assets)
    assert [item.kind for item in recorded.visuals] == [VisualKind.COVER_PLATE]

    # Regenerating replaces the entry for that kind rather than piling up.
    generate_workspace_plate(
        workspace,
        VisualKind.COVER_PLATE,
        "inne tło",
        allow_flag=True,
        status=status,
        transport=transport,
    )
    assert len(load_artifact(VisualAssets, workspace.visual_assets).visuals) == 1


def test_an_unavailable_provider_points_at_the_local_fallback(tmp_path: Path) -> None:
    workspace = Workspace.at(tmp_path / "edit").ensure()
    status = detect_image_provider({"CLAUDECODE": "1"})
    with pytest.raises(ValidationError, match="typographic"):
        generate_workspace_plate(
            workspace, VisualKind.COVER_PLATE, "tło", allow_flag=True, status=status
        )
