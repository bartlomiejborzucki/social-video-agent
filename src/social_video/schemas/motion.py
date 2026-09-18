"""Intentional motion design rendered by Remotion after the technical edit."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import Field, model_validator

from social_video.schemas.base import Artifact


class MotionElementType(str, Enum):
    HOOK = "hook"
    LOWER_THIRD = "lower_third"
    CALLOUT = "callout"
    END_CARD = "end_card"


class MotionElement(Artifact):
    type: MotionElementType
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=180)
    secondary_text: str | None = Field(default=None, max_length=180)
    reason: str = Field(min_length=1, max_length=300)
    #: Optional background image for an end card. A local PNG/JPEG/WebP, either a
    #: project asset or a plate recorded in visuals.json. Text is never part of
    #: it: the words above are drawn by the compositor from the brand contract.
    image_asset: str | None = None
    #: How much the plate is darkened so the end-card text stays readable.
    image_dim_pct: float = Field(default=45.0, ge=0.0, le=90.0)

    @model_validator(mode="after")
    def _valid_interval(self) -> MotionElement:
        if self.end <= self.start:
            raise ValueError("motion element end must be after start")
        if self.image_asset is not None:
            if self.type is not MotionElementType.END_CARD:
                raise ValueError(
                    "image_asset is only supported on an end_card; a plate behind a hook "
                    "or callout covers the speaker the edit was made for"
                )
            suffix = Path(self.image_asset).suffix.casefold()
            if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
                raise ValueError("image_asset must be a .png, .jpg, .jpeg or .webp file")
        return self


class MotionPlan(Artifact):
    """A restrained, reviewable visual layer; never a bag of random effects."""

    style: str = "editorial_clean"
    accent_color: str = Field(default="#FFD400", pattern=r"^#[0-9A-Fa-f]{6}$")
    text_color: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    background_color: str = Field(default="#101114", pattern=r"^#[0-9A-Fa-f]{6}$")
    font_family: str = Field(default="Inter", min_length=1, max_length=120)
    font_path: str | None = None
    elements: list[MotionElement] = Field(default_factory=list)
    rationale: str = Field(min_length=1, max_length=800)
