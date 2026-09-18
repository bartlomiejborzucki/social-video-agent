"""Where the clip is going, and what that placement covers up.

The reserved percentages are deliberately conservative estimates of the feed
UI, not published specifications: every platform moves its overlays without
notice. They are JSON so a user can correct them without touching code, and QA
reports them as warnings rather than pretending they are exact.
"""

from __future__ import annotations

from pydantic import Field

from social_video.schemas.base import Artifact


class PlatformSpec(Artifact):
    """One publishing destination."""

    name: str = Field(min_length=1, max_length=40)
    description: str = ""
    aspect_ratios: list[str] = Field(default_factory=lambda: ["9:16"])

    #: Fraction of the frame the feed UI is expected to cover.
    reserved_bottom_pct: float = Field(default=20.0, ge=0.0, le=45.0)
    reserved_top_pct: float = Field(default=10.0, ge=0.0, le=45.0)
    reserved_right_pct: float = Field(default=15.0, ge=0.0, le=45.0)
    reserved_left_pct: float = Field(default=4.0, ge=0.0, le=45.0)

    min_duration: float = Field(default=3.0, gt=0.0)
    #: Hard platform limit. Exceeding it means the upload is rejected or cut.
    max_duration: float = Field(default=180.0, gt=0.0)
    #: Editorial ceiling, not a technical one.
    recommended_max_duration: float = Field(default=90.0, gt=0.0)

    title_max_chars: int = Field(default=100, ge=10, le=500)
    description_max_chars: int = Field(default=2200, ge=50, le=10000)
    hashtag_max: int = Field(default=30, ge=0, le=100)

    #: How the numbers above were arrived at, so nobody mistakes them for law.
    accuracy_note: str = ""
