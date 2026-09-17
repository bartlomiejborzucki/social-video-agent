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


class DeliveryManifest(Artifact):
    delivery_version: int = 1
    workspace: str
    destination: str
    edl_path: str
    edl_sha256_before: str
    edl_sha256_after: str
    items: list[DeliveryItem] = Field(default_factory=list)
