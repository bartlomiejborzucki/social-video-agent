"""Record what this session can do about imagery, and which source it chose.

Two of the four ways to make imagery are invisible to a Python process: the
host's native image tool and an MCP connection to Canva both belong to the
agent. So this module does not detect them -- it takes the agent's finding,
checks it for internal consistency, adds what the CLI *can* check, and writes
the result where Stage 0 and later stages can read it.

The choice of source is editorial and stays the agent's. Nothing here picks a
source, because "it was available" is not a reason to use it: a real frame of
the speaker usually beats a generated background, and a company template only
earns its place when the edit actually calls for one. What this module enforces
is that a recorded choice is coherent -- you cannot choose Canva you do not
have, or a cloud generator the project's policy forbids.
"""

from __future__ import annotations

from pathlib import Path

from social_video.errors import ValidationError
from social_video.fsutil import utc_timestamp
from social_video.imagegen.providers import local_api_capabilities
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.config import BrandContract
from social_video.schemas.visuals import (
    CapabilityState,
    ImageSource,
    VisualCapabilities,
)
from social_video.workspace.layout import Workspace

#: Preference order for imagery. Earlier is preferred, but only when the edit
#: is actually served by it; this is a tie-breaker, not a decision procedure.
SOURCE_PRIORITY: tuple[ImageSource, ...] = (
    ImageSource.EXISTING_ASSET,
    ImageSource.VIDEO_FRAME,
    ImageSource.CANVA,
    ImageSource.CHATGPT_NATIVE,
    ImageSource.OPENAI_API,
    ImageSource.GEMINI_API,
    ImageSource.LOCAL_COMPOSITION,
)

#: Sources that send a prompt to somebody else's service, and therefore need
#: the project's consent. The native tool is on this list: a host-provided tool
#: is still a cloud service, and the prompt still leaves the machine.
CLOUD_SOURCES = frozenset(
    {
        ImageSource.CANVA,
        ImageSource.CHATGPT_NATIVE,
        ImageSource.OPENAI_API,
        ImageSource.GEMINI_API,
    }
)

#: Sources that need nothing but the project's own material.
LOCAL_SOURCES = frozenset(
    {ImageSource.EXISTING_ASSET, ImageSource.VIDEO_FRAME, ImageSource.LOCAL_COMPOSITION}
)

_REQUIRED_CAPABILITY = {
    ImageSource.CANVA: "canva",
    ImageSource.CHATGPT_NATIVE: "native_imagegen",
    ImageSource.OPENAI_API: "openai_api",
    ImageSource.GEMINI_API: "gemini_api",
}


def record_capabilities(
    workspace: Workspace,
    *,
    chosen_source: ImageSource,
    reason: str,
    native_imagegen: CapabilityState = CapabilityState.UNKNOWN_TO_CLI,
    canva: CapabilityState = CapabilityState.UNKNOWN_TO_CLI,
    env: dict[str, str] | None = None,
) -> VisualCapabilities:
    """Write the session's visual capabilities and the source the agent chose."""
    contract = _contract(workspace)
    local = local_api_capabilities(env)
    policy = _policy(contract)
    record = VisualCapabilities(
        native_imagegen=native_imagegen,
        canva=canva,
        openai_api=local["openai_api"],
        gemini_api=local["gemini_api"],
        policy=policy,
        chosen_source=chosen_source,
        reason=" ".join(reason.split()),
        recorded_at=utc_timestamp(),
        recorded_by="agent",
    )
    _check(record)
    save_artifact(record, workspace.visual_capabilities)
    return record


def load_capabilities(workspace: Workspace) -> VisualCapabilities | None:
    path = Path(workspace.visual_capabilities)
    return load_artifact(VisualCapabilities, path) if path.is_file() else None


def _contract(workspace: Workspace) -> BrandContract | None:
    return (
        load_artifact(BrandContract, workspace.brand_contract)
        if workspace.brand_contract.is_file()
        else None
    )


def _policy(contract: BrandContract | None) -> str:
    if contract is None:
        return "none"
    return "optional" if contract.image_generation_enabled else "none"


def _check(record: VisualCapabilities) -> None:
    """Refuse a record that contradicts itself."""
    source = record.chosen_source
    if source in LOCAL_SOURCES:
        return
    capability = _REQUIRED_CAPABILITY[source]
    state = getattr(record, capability)
    if state is CapabilityState.UNAVAILABLE:
        raise ValidationError(
            f"chosen_source={source.value} needs {capability}, which this session "
            f"records as unavailable. Choose a source that exists, or correct the "
            f"capability if it was recorded wrongly."
        )
    if state is CapabilityState.UNKNOWN_TO_CLI and capability in {"openai_api", "gemini_api"}:
        raise ValidationError(
            f"{capability} is checkable from here, so it must be recorded as available "
            "or unavailable rather than unknown"
        )
    if source in CLOUD_SOURCES and record.policy == "none":
        raise ValidationError(
            f"chosen_source={source.value} sends a prompt to a cloud service, but this "
            "project's image_generation_policy is 'none'. That applies to the agent's "
            "native image tool as well: a host-provided tool is still a cloud service. "
            "Change the policy deliberately, or choose a local source."
        )
