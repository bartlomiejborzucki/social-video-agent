"""Versioned, executable project video configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from social_video.schemas.base import Artifact
from social_video.schemas.brand import BrandProfile, CaptionBackgroundStyle, CaptionOutlineStyle


class CaptionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case: Literal["as_spoken", "upper", "lower"] = "as_spoken"
    font_weight: Literal["normal", "bold"] = "bold"
    text_color: str = "#FFFFFF"
    background_color: str = "#000000"
    background_style: CaptionBackgroundStyle = CaptionBackgroundStyle.NONE
    corner_radius: int = Field(default=0, ge=0, le=200)
    outline_color: str = "#000000"
    outline_or_shadow: CaptionOutlineStyle = CaptionOutlineStyle.OUTLINE
    max_lines: int = Field(default=2, ge=1, le=4)
    max_words_per_cue: int = Field(default=4, ge=1, le=20)
    position: Literal["bottom", "center", "top", "lower_third", "lower_safe_zone"] = (
        "lower_safe_zone"
    )
    bottom_margin_pct: float = Field(default=12, ge=0, le=45)

    @field_validator("text_color", "background_color", "outline_color")
    @classmethod
    def _colour(cls, value: str) -> str:
        if len(value) != 7 or not value.startswith("#"):
            raise ValueError("must be a #RRGGBB colour")
        try:
            int(value[1:], 16)
        except ValueError as exc:
            raise ValueError("must be a #RRGGBB colour") from exc
        return value.upper()


class ProjectVideoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    brand_name: str = "Project brand"
    language: str | None = None
    content_language: str | None = None
    font: str = "Lato"
    font_file: str | None = None
    font_fallback: list[str] = Field(default_factory=lambda: ["Noto Sans", "DejaVu Sans"])
    brand_colors: list[str] = Field(default_factory=list)
    logo_file: str | None = None
    logo_usage: Literal["none", "optional", "required"] = "none"
    caption_style: CaptionConfig = Field(default_factory=CaptionConfig)
    safe_margins: dict[str, float] = Field(default_factory=dict)
    editing_profile: str = "calm-expert"
    punch_in_intensity: float = Field(default=0.25, ge=0, le=1)
    broll_density: float = Field(default=0, ge=0, le=1)
    music_policy: Literal["none", "optional", "required"] = "none"
    sfx_policy: Literal["none", "optional", "required"] = "none"
    #: Whether this project permits sending a text prompt to a cloud image model
    #: for cover and end-card plates. Media is never uploaded either way.
    image_generation_policy: Literal["none", "optional", "required"] = "none"
    #: Where the finished clip is posted. Drives platform safe-zone checks.
    target_platforms: list[str] = Field(default_factory=list)
    default_aspect_ratio: Literal["9:16", "1:1", "16:9"] = "9:16"
    default_resolution: str = "1080x1920"
    default_fps_policy: Literal["30", "60", "30000/1001", "60000/1001"] = "30"
    delivery_output: str | None = None
    model_budget: Literal["economical", "balanced", "quality"] | None = None
    workflow_mode: Literal["guided", "continuous"] | None = None
    brandbook: str | None = None
    editing_guide: str | None = None
    intro: str | None = None
    outro: str | None = None

    @field_validator("brand_colors")
    @classmethod
    def _colours(cls, values: list[str]) -> list[str]:
        return [CaptionConfig._colour(value) for value in values]

    @field_validator("safe_margins")
    @classmethod
    def _margins(cls, values: dict[str, float]) -> dict[str, float]:
        allowed = {"top", "right", "bottom", "left"}
        if unknown := set(values) - allowed:
            raise ValueError(f"unsupported safe margin(s): {', '.join(sorted(unknown))}")
        if any(value < 0 or value > 45 for value in values.values()):
            raise ValueError("safe margins must be between 0 and 45 percent")
        return values

    @model_validator(mode="after")
    def _resolution_matches_aspect(self) -> ProjectVideoConfig:
        try:
            width_text, height_text = self.default_resolution.lower().split("x", 1)
            width, height = int(width_text), int(height_text)
        except (ValueError, AttributeError) as exc:
            raise ValueError("default_resolution must look like 1080x1920") from exc
        if width <= 0 or height <= 0 or width % 2 or height % 2:
            raise ValueError("default_resolution must contain positive even dimensions")
        expected = {"9:16": 9 / 16, "1:1": 1, "16:9": 16 / 9}[self.default_aspect_ratio]
        if abs(width / height - expected) > 0.01:
            raise ValueError("default_resolution does not match default_aspect_ratio")
        if self.logo_usage == "required" and not self.logo_file:
            raise ValueError("logo_usage=required requires logo_file")
        return self

    @property
    def resolution(self) -> tuple[int, int]:
        width, height = self.default_resolution.lower().split("x", 1)
        return int(width), int(height)

    @property
    def fps(self) -> str:
        if self.default_fps_policy in {"30", "60"}:
            return f"{self.default_fps_policy}/1"
        return self.default_fps_policy


class BrandContract(Artifact):
    """Resolved rendering inputs; no heuristic or unresolved profile name remains."""

    contract_version: int = 1
    project_config_path: str
    project_config_sha256: str
    project_root: str
    brand: BrandProfile
    output_width: int
    output_height: int
    output_fps: str
    delivery_output: str | None = None
    resolved_font_file: str | None = None
    resolved_logo_file: str | None = None
    safe_margins: dict[str, float] = Field(default_factory=dict)
    image_generation_enabled: bool = False
    target_platforms: list[str] = Field(default_factory=list)
    #: Compiled from the project config. `required` means an edit without one is
    #: incomplete; `none` means the renderer refuses to mix one at all.
    music_policy: Literal["none", "optional", "required"] = "none"
    sfx_policy: Literal["none", "optional", "required"] = "none"

    def validate_assets(self) -> None:
        for label, value in (("font", self.resolved_font_file), ("logo", self.resolved_logo_file)):
            if value is not None and not Path(value).is_file():
                raise ValueError(f"configured {label} asset no longer exists: {value}")
