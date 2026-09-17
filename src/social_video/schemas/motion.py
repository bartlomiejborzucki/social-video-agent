"""Intentional motion design rendered by Remotion after the technical edit."""

from __future__ import annotations

from enum import Enum

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

    @model_validator(mode="after")
    def _valid_interval(self) -> MotionElement:
        if self.end <= self.start:
            raise ValueError("motion element end must be after start")
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
