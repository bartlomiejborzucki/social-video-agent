"""Still images: what a cloud model drew, and what we composed from it.

Generated imagery is the one part of this pipeline that leaves the machine, so
every plate carries its provider, model, exact prompt, consent basis and hash.
A cover is then composed locally from the brand contract; the image model never
renders text, because it garbles diacritics and cannot honour a brand contract.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from social_video.schemas.base import Artifact


class VisualKind(str, Enum):
    #: Background behind the composed cover/thumbnail.
    COVER_PLATE = "cover_plate"
    #: Background behind the Remotion end card.
    END_CARD_PLATE = "end_card_plate"


class ImageProviderName(str, Enum):
    """Where a plate came from.

    ``chatgpt_native`` is the image tool a host such as ChatGPT or Codex hands
    to the agent. It needs no API key of the user's own, it cannot be called
    from Python, and the agent invokes it directly -- so a plate from it is
    *registered* with this CLI rather than produced by it.
    """

    #: The host's own image tool, called by the agent, not by this CLI.
    CHATGPT_NATIVE = "chatgpt_native"
    OPENAI_API = "openai_api"
    GEMINI_API = "gemini_api"


#: Values written before the native tool existed. Read, never written.
_LEGACY_PROVIDERS = {"openai": "openai_api", "gemini": "gemini_api"}


class ImageTool(str, Enum):
    """The specific tool that drew the image, which is not the same as the provider."""

    #: The host-provided agent tool. Its own name varies by host.
    NATIVE_IMAGEGEN = "native_imagegen"
    OPENAI_IMAGES_API = "openai_images_api"
    GEMINI_GENERATE_CONTENT = "gemini_generate_content"


class GeneratedVisual(Artifact):
    """One plate, and everything needed to say where it came from.

    The image tool draws backgrounds, illustrations, textures and untyped
    plates. It never draws a word: every caption, headline, CTA and logo in the
    finished video is rendered locally by Remotion, because that is the only way
    Polish diacritics, the brand contract and the safe area all survive.
    """

    kind: VisualKind
    provider: ImageProviderName
    tool: ImageTool
    #: Absent when the tool does not disclose one. A native image tool usually
    #: does not, and inventing a plausible model name would be a lie in the
    #: provenance record.
    model: str | None = Field(default=None, max_length=120)
    #: Exactly what was sent, including the no-text guardrail preamble.
    prompt: str = Field(min_length=1, max_length=4000)
    path: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: str
    #: Why this upload was permitted. Absence of a basis is never consent.
    #: ``user_request`` covers one image the user asked for in so many words,
    #: and does not extend to the next one.
    consent: Literal["project_config", "explicit_flag", "user_request"]
    #: What the plate is for, in the words of the edit plan.
    purpose: str = Field(default="", max_length=300)
    #: Where a registered file came from before it was copied into the
    #: workspace. Empty for a plate this CLI generated itself.
    source_path: str = ""
    #: None until brand QA has looked at it.
    qa_accepted: bool | None = None
    cost_note: str = Field(default="", max_length=200)

    @field_validator("provider", mode="before")
    @classmethod
    def _accept_legacy_provider(cls, value: object) -> object:
        """Keep reading a visuals.json written before the native tool existed."""
        if isinstance(value, str) and value in _LEGACY_PROVIDERS:
            return _LEGACY_PROVIDERS[value]
        return value

    @model_validator(mode="after")
    def _tool_matches_provider(self) -> GeneratedVisual:
        expected = {
            ImageProviderName.CHATGPT_NATIVE: ImageTool.NATIVE_IMAGEGEN,
            ImageProviderName.OPENAI_API: ImageTool.OPENAI_IMAGES_API,
            ImageProviderName.GEMINI_API: ImageTool.GEMINI_GENERATE_CONTENT,
        }[self.provider]
        if self.tool is not expected:
            raise ValueError(
                f"provider {self.provider.value} is drawn by {expected.value}, "
                f"not {self.tool.value}"
            )
        return self


class CapabilityState(str, Enum):
    """Whether a way of making imagery can be used right now."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    #: This CLI cannot see the agent's own tools or its MCP connections, so it
    #: reports what it checked instead of guessing. Only the agent can settle
    #: this, and an absent API key is not evidence either way.
    UNKNOWN_TO_CLI = "unknown_to_cli"


class ImageSource(str, Enum):
    """Where this edit's imagery comes from, in order of preference."""

    #: The user's own material, or a real frame of their video.
    EXISTING_ASSET = "existing_asset"
    VIDEO_FRAME = "video_frame"
    #: A company template, when the connection exists and the template earns it.
    CANVA = "canva"
    #: The host's image tool, called by the agent.
    CHATGPT_NATIVE = "chatgpt_native"
    OPENAI_API = "openai_api"
    GEMINI_API = "gemini_api"
    #: Composed locally: a brand gradient, a solid, or a frame.
    LOCAL_COMPOSITION = "local_composition"


class VisualCapabilities(Artifact):
    """What this session can actually do about imagery, and what it chose.

    Half of this is only knowable by the agent: a native image tool and an MCP
    connection to Canva are not visible to a Python process. So the CLI fills
    in what it can check -- local API credentials -- and the agent records the
    rest. Nothing here is inferred from a subscription.
    """

    native_imagegen: CapabilityState = CapabilityState.UNKNOWN_TO_CLI
    canva: CapabilityState = CapabilityState.UNKNOWN_TO_CLI
    openai_api: CapabilityState = CapabilityState.UNAVAILABLE
    gemini_api: CapabilityState = CapabilityState.UNAVAILABLE
    #: The project's image_generation_policy at the time of recording.
    policy: str = "none"
    chosen_source: ImageSource
    #: Why this source, in terms of the edit rather than of availability.
    #: Something being available is not a reason to use it.
    reason: str = Field(min_length=1, max_length=600)
    recorded_at: str
    recorded_by: Literal["agent", "cli"] = "agent"


class VisualAssets(Artifact):
    """Every plate generated for this edit."""

    visuals: list[GeneratedVisual] = Field(default_factory=list)


class CoverDesign(Artifact):
    """The composed cover: brand typography over a frame or a generated plate."""

    path: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=120)
    subtitle: str | None = Field(default=None, max_length=160)
    background: Literal["frame", "plate", "solid"]
    #: Timestamp of the output frame used, when the background is a real frame.
    frame_at: float | None = Field(default=None, ge=0.0)
    plate: str | None = None
    font_file: str | None = None
    logo_file: str | None = None
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: str
