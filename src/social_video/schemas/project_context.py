"""Durable, source-traceable project context for one edit workspace."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from social_video.schemas.base import Artifact


class ContextConfidence(str, Enum):
    EXPLICIT = "explicit"
    STRONGLY_INFERRED = "strongly_inferred"
    WEAK_HINT = "weak_hint"


class ContextSource(Artifact):
    path: str = Field(description="Path relative to target_project_root.")
    source_type: str
    relevance: int = Field(ge=0, le=100)
    confidence: ContextConfidence
    fingerprint: str
    size_bytes: int = Field(ge=0)
    signals: list[str] = Field(default_factory=list)
    extracted_facts: dict[str, Any] = Field(default_factory=dict)
    excerpt: str = Field(default="", max_length=2500)


class ContextSources(Artifact):
    target_project_root: str
    fingerprint: str
    scanned_at: str
    candidates_considered: int = Field(ge=0)
    truncated: bool = False
    sources: list[ContextSource] = Field(default_factory=list)


class ContextClaim(BaseModel):
    """One concise fact with its local evidence and confidence."""

    model_config = ConfigDict(extra="forbid")

    category: str
    key: str
    value: Any
    source: str
    confidence: ContextConfidence


class ProjectContext(Artifact):
    target_project_root: str
    generated_at: str
    source_fingerprint: str
    cache_status: str = "refreshed"
    explicit_config: str | None = None
    applicable_agents_files: list[str] = Field(default_factory=list)
    brand: dict[str, Any] = Field(default_factory=dict)
    voice: dict[str, Any] = Field(default_factory=dict)
    audience: dict[str, Any] = Field(default_factory=dict)
    visual_style: dict[str, Any] = Field(default_factory=dict)
    fonts: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    logos: list[str] = Field(default_factory=list)
    video_guidelines: list[str] = Field(default_factory=list)
    caption_guidelines: dict[str, Any] = Field(default_factory=dict)
    editing_guidelines: dict[str, Any] = Field(default_factory=dict)
    audio_guidelines: dict[str, Any] = Field(default_factory=dict)
    known_assets: list[str] = Field(default_factory=list)
    output_requirements: dict[str, Any] = Field(default_factory=dict)
    claims: list[ContextClaim] = Field(default_factory=list)
    style_sources: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)


class ProjectConfig(BaseModel):
    """Optional explicit ``social-video.yaml`` values; every field is optional."""

    model_config = ConfigDict(extra="forbid")

    brand_name: str | None = None
    schema_version: int | None = None
    language: str | None = None
    content_language: str | None = None
    editing_profile: str | None = None
    model_budget: Literal["economical", "balanced", "quality"] | None = None
    workflow_mode: Literal["guided", "continuous"] | None = None
    caption_style: dict[str, Any] | None = None
    font: str | None = None
    font_file: str | None = None
    font_fallback: list[str] | None = None
    brand_colors: list[str] | None = None
    logo: str | None = None
    logo_file: str | None = None
    logo_usage: str | None = None
    safe_margins: dict[str, float] | None = None
    punch_in_intensity: str | float | None = None
    broll_density: str | float | None = None
    music_policy: str | None = None
    sfx_policy: str | None = None
    default_aspect_ratio: str | None = None
    default_resolution: str | None = None
    default_fps_policy: str | None = None
    intro: str | None = None
    outro: str | None = None
    preferred_output_directory: str | None = None
    delivery_output: str | None = None
    brandbook: str | None = None
    editing_guide: str | None = None
