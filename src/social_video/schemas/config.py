"""Versioned, executable project video configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from social_video.schemas.base import Artifact
from social_video.schemas.brand import BrandProfile, CaptionBackgroundStyle, CaptionOutlineStyle


class CaptionConfig(BaseModel):
    """Caption presentation, in units that survive a change of resolution.

    The defaults are the reference values for a 9:16 short: a caption that is
    small enough for an ordinary Polish phrase to fit two lines at 1080x1920,
    cued short enough that the sentence breaks on words rather than on the
    frame edge, and clear of the platform UI at the bottom.
    """

    model_config = ConfigDict(extra="forbid")

    case: Literal["as_spoken", "upper", "lower"] = "as_spoken"
    font_weight: Literal["normal", "bold"] = "bold"
    text_color: str = "#FFFFFF"
    background_color: str = "#000000"
    background_style: CaptionBackgroundStyle = CaptionBackgroundStyle.NONE
    corner_radius: int = Field(default=24, ge=0, le=200)
    outline_color: str = "#000000"
    #: `none` by default: an outline on top of a background box thickens every
    #: glyph and costs the line width that long words need.
    outline_or_shadow: CaptionOutlineStyle = CaptionOutlineStyle.NONE
    #: Percentage of output height, so the size means the same at 720p and
    #: 1080p. 3.6% of a 1920-pixel frame is ~69 px, which fits roughly 13
    #: Polish characters per line inside a 9:16 safe area. The old renderer
    #: default of 5% is ~96 px, which does not, and used to be clamped away.
    font_size_pct: float = Field(default=3.6, ge=1.5, le=12.0)
    max_lines: int = Field(default=2, ge=1, le=4)
    max_words_per_cue: int = Field(default=4, ge=1, le=20)
    #: Hard limit on cue length. This is what splits a long sentence into
    #: several cues at word and clause boundaries, before any layout happens.
    max_chars_per_cue: int = Field(default=24, ge=8, le=60)
    position: Literal["bottom", "center", "top", "lower_third", "lower_safe_zone"] = (
        "lower_safe_zone"
    )
    bottom_margin_pct: float = Field(default=22, ge=0, le=45)
    #: Colour the word being spoken, exactly while it is spoken. Needs word
    #: timings in the caption track, which local transcription provides.
    active_word_highlight: bool = False
    highlight_color: str = "#FFD400"
    #: Brand words drawn in `emphasis_color` wherever they are spoken, matched
    #: case-insensitively and ignoring punctuation. Inflected forms are
    #: listed separately: `Studio` does not also match `Studia`.
    emphasis_words: list[str] = Field(default_factory=list, max_length=100)
    emphasis_color: str = "#FFD400"

    @field_validator("emphasis_words")
    @classmethod
    def _emphasis_words(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            word = value.strip()
            if not word or any(ch.isspace() for ch in word):
                raise ValueError(
                    f"emphasis_words entries are single words; got {value!r}. "
                    "List each word of a phrase separately."
                )
            if word not in cleaned:
                cleaned.append(word)
        return cleaned

    @field_validator(
        "text_color", "background_color", "outline_color", "highlight_color", "emphasis_color"
    )
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
    #: Voice cleanup. `measured` is the default: the render measures this
    #: recording and applies only the repairs the measurement justifies, each
    #: with a ceiling that keeps the result the same voice. `none` leaves the
    #: audio exactly as recorded; `required` fails an edit it cannot measure.
    #: Every render reports what it changed and how to turn it off.
    audio_cleanup_policy: Literal["none", "measured", "required"] = "measured"
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
    #: Where the agent runs relative to the editing engine. `auto` detects it
    #: from the real platform, not from a terminal preference, and is the
    #: default so nothing changes for an agent already running inside WSL.
    runtime_mode: Literal[
        "auto", "wsl-native", "windows-agent-wsl-runtime", "linux-native", "macos-native"
    ] = "auto"
    #: Names the WSL distribution to delegate into, for a machine with more
    #: than one. Ignored outside the hybrid mode.
    wsl_distribution: str | None = None
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
        self._reject_unfittable_captions(width, height)
        return self

    def _reject_unfittable_captions(self, width: int, height: int) -> None:
        """Refuse a caption geometry whose own text cannot be drawn.

        This is where the old defect became unrenderable rather than merely
        ugly: a config that asks for more text than the frame can hold used to
        validate and then lose its last words to the compositor's line clamp.
        """
        from social_video.captions.fit import contract_fit_error

        style = self.caption_style
        error = contract_fit_error(
            font_size_pct=style.font_size_pct,
            max_chars_per_cue=style.max_chars_per_cue,
            max_lines=style.max_lines,
            boxed=style.background_style.value != "none",
            width=width,
            height=height,
            horizontal_margin_pct=(
                self.safe_margins.get("left", 6.0) + self.safe_margins.get("right", 6.0)
            ),
        )
        if error:
            raise ValueError(error)

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
    #: Compiled from the project config. `measured` cleans only what this
    #: recording measures as broken; `none` renders the audio as recorded.
    audio_cleanup_policy: Literal["none", "measured", "required"] = "measured"

    def validate_assets(self) -> None:
        for label, value in (("font", self.resolved_font_file), ("logo", self.resolved_logo_file)):
            if value is not None and not Path(value).is_file():
                raise ValueError(f"configured {label} asset no longer exists: {value}")
