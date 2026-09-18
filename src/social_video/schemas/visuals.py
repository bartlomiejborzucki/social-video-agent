"""Still images: what a cloud model drew, and what we composed from it.

Generated imagery is the one part of this pipeline that leaves the machine, so
every plate carries its provider, model, exact prompt, consent basis and hash.
A cover is then composed locally from the brand contract; the image model never
renders text, because it garbles diacritics and cannot honour a brand contract.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field

from social_video.schemas.base import Artifact


class VisualKind(str, Enum):
    #: Background behind the composed cover/thumbnail.
    COVER_PLATE = "cover_plate"
    #: Background behind the Remotion end card.
    END_CARD_PLATE = "end_card_plate"


class ImageProviderName(str, Enum):
    OPENAI = "openai"
    GEMINI = "gemini"


class GeneratedVisual(Artifact):
    """One plate produced by a cloud image model."""

    kind: VisualKind
    provider: ImageProviderName
    model: str = Field(min_length=1, max_length=120)
    #: Exactly what was sent, including the no-text guardrail preamble.
    prompt: str = Field(min_length=1, max_length=4000)
    path: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: str
    #: Why this upload was permitted. Absence of a basis is never consent.
    consent: Literal["project_config", "explicit_flag"]
    cost_note: str = Field(default="", max_length=200)


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
