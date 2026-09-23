"""Four ways to make imagery, and the CLI can only see two of them.

The defect these cover: the absence of `OPENAI_API_KEY` and `GEMINI_API_KEY`
was treated as proof that no image could be generated. On a host whose agent
has a native image tool that is false -- the agent generates without any key of
the user's own, and this CLI's job is to register the result with its
provenance rather than to pretend it called anything.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from social_video.errors import ValidationError
from social_video.imagegen import (
    AGENT_MUST_DETERMINE,
    CLOUD_SOURCES,
    LOCAL_SOURCES,
    PLATE_GUARDRAIL,
    SOURCE_PRIORITY,
    build_prompt,
    detect_image_provider,
    load_capabilities,
    local_api_capabilities,
    record_capabilities,
    register_visual,
    resolve_consent,
)
from social_video.schemas.base import load_artifact
from social_video.schemas.brand import BrandProfile
from social_video.schemas.config import BrandContract
from social_video.schemas.visuals import (
    CapabilityState,
    GeneratedVisual,
    ImageProviderName,
    ImageSource,
    ImageTool,
    VisualAssets,
    VisualKind,
)
from social_video.workspace.layout import Workspace

NO_KEYS: dict[str, str] = {}
OPENAI_ONLY = {"OPENAI_API_KEY": "sk-test-not-a-real-key"}
GEMINI_ONLY = {"GEMINI_API_KEY": "ai-studio-test-key"}


def _contract(*, policy_enabled: bool) -> BrandContract:
    return BrandContract(
        project_config_path="c.yaml",
        project_config_sha256="f" * 64,
        project_root="/p",
        brand=BrandProfile(),
        output_width=1080,
        output_height=1920,
        output_fps="30/1",
        image_generation_enabled=policy_enabled,
    )


def _workspace(tmp_path: Path, *, policy_enabled: bool = True) -> Workspace:
    workspace = Workspace.at(tmp_path / "edit")
    workspace.ensure()
    from social_video.schemas.base import save_artifact

    save_artifact(_contract(policy_enabled=policy_enabled), workspace.brand_contract)
    return workspace


def _plate(path: Path, size: tuple[int, int] = (1080, 1920)) -> Path:
    """A plain vertical plate with no text in it, as the guardrail requires."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (18, 24, 34)).save(path)
    return path


# --- the four capability states ---------------------------------------------


def test_native_tool_available_with_no_api_keys_can_still_generate(tmp_path: Path) -> None:
    """The reported scenario: a native tool, no keys, and generation works."""
    status = detect_image_provider(NO_KEYS)
    workspace = _workspace(tmp_path)

    # The CLI cannot draw it, and says only that.
    assert status.cli_can_generate is False
    assert status.to_dict()["native_imagegen"] == "unknown_to_cli"

    # The agent has the tool, so it records that and chooses it.
    record = record_capabilities(
        workspace,
        chosen_source=ImageSource.CHATGPT_NATIVE,
        reason="The end card needs a calm abstract background that no frame of this "
        "interview provides.",
        native_imagegen=CapabilityState.AVAILABLE,
        env=NO_KEYS,
    )
    assert record.native_imagegen is CapabilityState.AVAILABLE
    assert record.openai_api is CapabilityState.UNAVAILABLE
    assert record.gemini_api is CapabilityState.UNAVAILABLE

    # And the plate it produced is registered, with its real provenance.
    visual = register_visual(
        workspace,
        VisualKind.END_CARD_PLATE,
        _plate(tmp_path / "native.png"),
        prompt=build_prompt("calm night-sky gradient"),
        purpose="background behind the Remotion end card",
    )
    assert visual.provider is ImageProviderName.CHATGPT_NATIVE
    assert visual.tool is ImageTool.NATIVE_IMAGEGEN
    assert visual.model is None, "a tool that reports no model must not acquire one"
    assert Path(visual.path).is_file()


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        (OPENAI_ONLY, ImageProviderName.OPENAI_API),
        (GEMINI_ONLY, ImageProviderName.GEMINI_API),
    ],
    ids=["openai", "gemini"],
)
def test_without_a_native_tool_the_available_api_is_chosen(
    env: dict[str, str], expected: ImageProviderName
) -> None:
    status = detect_image_provider(env)

    assert status.cli_can_generate is True
    assert status.provider is not None and status.provider.name is expected
    assert status.provider.api_key not in json.dumps(status.to_dict())


def test_no_generator_at_all_falls_back_to_something_local(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    record = record_capabilities(
        workspace,
        chosen_source=ImageSource.VIDEO_FRAME,
        reason="No generator is available and the speaker's own frame is the honest "
        "background for this cover.",
        native_imagegen=CapabilityState.UNAVAILABLE,
        canva=CapabilityState.UNAVAILABLE,
        env=NO_KEYS,
    )

    assert record.chosen_source in LOCAL_SOURCES
    assert load_capabilities(workspace) == record


def test_a_capability_the_session_does_not_have_cannot_be_chosen(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    with pytest.raises(ValidationError, match="records as unavailable"):
        record_capabilities(
            workspace,
            chosen_source=ImageSource.CANVA,
            reason="A company template would look smarter.",
            canva=CapabilityState.UNAVAILABLE,
            env=NO_KEYS,
        )


def test_a_checkable_capability_may_not_be_recorded_as_unknown(tmp_path: Path) -> None:
    """The CLI can see API keys, so "unknown" would be an evasion there."""
    workspace = _workspace(tmp_path)

    record = record_capabilities(
        workspace,
        chosen_source=ImageSource.OPENAI_API,
        reason="An abstract plate suits the end card and the API key is present.",
        env=OPENAI_ONLY,
    )

    assert record.openai_api is CapabilityState.AVAILABLE


# --- policy outranks capability ---------------------------------------------


def test_policy_none_blocks_generation_even_with_a_native_tool(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, policy_enabled=False)

    with pytest.raises(ValidationError, match="image_generation_policy is 'none'"):
        register_visual(
            workspace,
            VisualKind.COVER_PLATE,
            _plate(tmp_path / "native.png"),
            prompt=build_prompt("abstract gradient"),
        )
    with pytest.raises(ValidationError, match="image_generation_policy is 'none'"):
        resolve_consent(_contract(policy_enabled=False), allow_flag=True)
    with pytest.raises(ValidationError, match="policy is 'none'"):
        record_capabilities(
            workspace,
            chosen_source=ImageSource.CHATGPT_NATIVE,
            reason="It would look nice.",
            native_imagegen=CapabilityState.AVAILABLE,
            env=NO_KEYS,
        )


def test_the_native_tool_is_treated_as_a_cloud_service() -> None:
    """A host-provided tool still sends the prompt off the machine."""
    assert ImageSource.CHATGPT_NATIVE in CLOUD_SOURCES
    assert ImageSource.LOCAL_COMPOSITION not in CLOUD_SOURCES


def test_a_direct_request_consents_to_one_image_only() -> None:
    assert resolve_consent(None, user_request=True) == "user_request"
    # Without a basis, nothing is implied.
    with pytest.raises(ValidationError):
        resolve_consent(None)


# --- provenance --------------------------------------------------------------


def test_registration_records_prompt_consent_and_hash(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source = _plate(tmp_path / "outside" / "plate.png")

    register_visual(
        workspace,
        VisualKind.COVER_PLATE,
        source,
        prompt=build_prompt("soft teal gradient, uncluttered centre"),
        purpose="cover background",
        model=None,
    )

    recorded = load_artifact(VisualAssets, workspace.visual_assets).visuals
    assert [item.kind for item in recorded] == [VisualKind.COVER_PLATE]
    entry = recorded[0]
    assert entry.provider is ImageProviderName.CHATGPT_NATIVE
    assert entry.tool is ImageTool.NATIVE_IMAGEGEN
    assert entry.prompt.startswith(PLATE_GUARDRAIL)
    assert "soft teal gradient" in entry.prompt
    assert entry.consent == "project_config"
    assert entry.purpose == "cover background"
    assert entry.source_path == str(source)
    assert entry.qa_accepted is None
    assert len(entry.sha256) == 64
    assert entry.width == 1080 and entry.height == 1920
    assert Path(entry.path).is_file()
    assert Path(entry.path) != source, "the workspace keeps its own copy"


@pytest.mark.parametrize("suffix", [".jpg", ".jpeg", ".webp"])
def test_a_lossy_plate_keeps_its_format(tmp_path: Path, suffix: str) -> None:
    workspace = _workspace(tmp_path)

    visual = register_visual(
        workspace,
        VisualKind.COVER_PLATE,
        _plate(tmp_path / f"plate{suffix}"),
        prompt=build_prompt("warm studio bokeh"),
    )

    assert Path(visual.path).suffix == suffix
    with Image.open(visual.path) as image:
        assert image.format == ("WEBP" if suffix == ".webp" else "JPEG")


def test_a_registered_prompt_is_never_double_guarded(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    guarded = build_prompt("warm studio bokeh")

    visual = register_visual(
        workspace, VisualKind.COVER_PLATE, _plate(tmp_path / "p.png"), prompt=guarded
    )

    assert visual.prompt == guarded
    assert visual.prompt.count("Absolute requirements:") == 1


def test_registering_a_file_that_is_not_an_image_is_refused(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    fake = tmp_path / "not-an-image.png"
    fake.write_text("nope", encoding="utf-8")

    with pytest.raises(ValidationError, match="not a readable image"):
        register_visual(workspace, VisualKind.COVER_PLATE, fake, prompt=build_prompt("x"))
    with pytest.raises(ValidationError, match="no such image"):
        register_visual(
            workspace, VisualKind.COVER_PLATE, tmp_path / "missing.png", prompt=build_prompt("x")
        )


def test_a_provenance_record_cannot_misattribute_the_tool() -> None:
    with pytest.raises(ValueError, match="is drawn by"):
        GeneratedVisual(
            kind=VisualKind.COVER_PLATE,
            provider=ImageProviderName.CHATGPT_NATIVE,
            tool=ImageTool.OPENAI_IMAGES_API,
            prompt="x",
            path="/tmp/x.png",
            width=1,
            height=1,
            sha256="0" * 64,
            created_at="2026-09-21T00:00:00Z",
            consent="user_request",
        )


def test_a_visuals_file_from_before_the_rename_still_loads() -> None:
    """Old records said `openai`; they must keep loading."""
    visual = GeneratedVisual.model_validate(
        {
            "kind": "cover_plate",
            "provider": "openai",
            "tool": "openai_images_api",
            "model": "gpt-image-1-mini",
            "prompt": "x",
            "path": "/tmp/x.png",
            "width": 1,
            "height": 1,
            "sha256": "0" * 64,
            "created_at": "2026-09-18T00:00:00Z",
            "consent": "project_config",
        }
    )

    assert visual.provider is ImageProviderName.OPENAI_API


# --- the guardrail and the division of labour -------------------------------


def test_the_default_prompt_forbids_text_in_the_image() -> None:
    prompt = build_prompt("a calm abstract background")

    lowered = prompt.casefold()
    for banned in ("no text", "no letters", "no numbers", "no words", "no captions"):
        assert banned in lowered, banned
    assert "no watermarks" in lowered
    assert "no logos" in lowered
    assert "no human faces" in lowered
    assert "typography can be placed over it later" in lowered


def test_the_priority_order_prefers_real_material_over_generation() -> None:
    order = list(SOURCE_PRIORITY)

    assert order.index(ImageSource.EXISTING_ASSET) < order.index(ImageSource.VIDEO_FRAME)
    assert order.index(ImageSource.VIDEO_FRAME) < order.index(ImageSource.CANVA)
    assert order.index(ImageSource.CANVA) < order.index(ImageSource.CHATGPT_NATIVE)
    assert order.index(ImageSource.CHATGPT_NATIVE) < order.index(ImageSource.OPENAI_API)
    assert order.index(ImageSource.OPENAI_API) < order.index(ImageSource.LOCAL_COMPOSITION)


def test_nothing_chooses_a_source_automatically() -> None:
    """Availability is not a reason. The agent records a reason of its own."""
    import social_video.imagegen.capabilities as module

    assert not any(name.startswith(("choose_", "select_", "pick_")) for name in dir(module)), (
        "a function that picks the source would make availability the decision"
    )


def test_local_api_capabilities_answers_only_what_it_can_check() -> None:
    reported = local_api_capabilities(OPENAI_ONLY)

    assert set(reported) == {"openai_api", "gemini_api"}
    assert reported["openai_api"] is CapabilityState.AVAILABLE
    assert reported["gemini_api"] is CapabilityState.UNAVAILABLE
    assert "native_imagegen" in AGENT_MUST_DETERMINE
