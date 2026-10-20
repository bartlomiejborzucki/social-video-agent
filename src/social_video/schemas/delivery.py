"""Versioned Stage 5 delivery manifest."""

from __future__ import annotations

from pydantic import Field

from social_video.schemas.base import Artifact


class DeliveryItem(Artifact):
    kind: str
    path: str
    size_bytes: int = Field(ge=0)
    format: str
    sha256: str
    qa_status: str
    qa_report: str | None = None
    qa_report_sha256: str | None = None
    #: Set when the delivery had a size limit: the limit, and the video
    #: bitrate of the two-pass encode that met it (None: it already fitted).
    #: A hook variant's name ("napis", "zdanie", "pytanie") and opening line.
    variant: str | None = None
    variant_text: str | None = None
    size_limit_bytes: int | None = None
    video_bitrate_kbps: int | None = None
    av_error_ms: float | None = None


class DeliveryManifest(Artifact):
    delivery_version: int = 1
    workspace: str
    destination: str
    edl_path: str
    edl_sha256_before: str
    edl_sha256_after: str
    items: list[DeliveryItem] = Field(default_factory=list)
    #: The cover, delivered as its own file and set at publication on each
    #: platform; it is never in the timeline.
    cover_path: str | None = None
    #: The hook check of the delivered video: score and the fixes it suggests.
    hook_check: str | None = None
    hook_check_fixes: list[str] = Field(default_factory=list)
    #: Opening QA of the delivered video (`analysis/opening-qa.json`). All
    #: optional, so manifests written before 2.1 still load.
    first_frame_is_content: bool | None = None
    first_frame_note: str | None = None
    first_cue_start_s: float | None = None
    first_cue_text: str | None = None
    leading_silence_s: float | None = None
    cover_in_timeline: bool | None = None
    time_to_first_situation_s: float | None = None
    end_card_only_at_end: bool | None = None
    #: False when a content-first opening rule is broken: the delivery is not
    #: ready, and `opening_issues` says what to fix.
    opening_ready: bool | None = None
    opening_issues: list[str] = Field(default_factory=list)
    #: Short-form practices that measure (`reel-check`): advisory, never
    #: blocking. "passed/total" and what to consider.
    reel_check: str | None = None
    reel_check_warnings: list[str] = Field(default_factory=list)
