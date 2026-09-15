"""The source manifest: what we were given, and what we observed about it.

Source files are immutable. Nothing in this package ever writes to them.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from social_video.schemas.base import Artifact


class SourceEntry(Artifact):
    """One source file and the facts probed from it."""

    id: str = Field(description="Short stable handle used by the EDL, e.g. 'C0103'.")
    path: str = Field(description="Absolute path to the original file. Never modified.")
    fingerprint: str = Field(description="Content fingerprint; changes when the file changes.")
    size_bytes: int = Field(ge=0)
    duration: float = Field(ge=0.0)

    width: int = Field(ge=0)
    height: int = Field(ge=0)
    rotation: int = Field(default=0, description="Display-matrix rotation in degrees.")
    frame_rate: str = Field(description="Exact rational, e.g. '30000/1001'.")
    pix_fmt: str = ""
    color_transfer: str = ""
    video_codec: str = ""
    audio_tracks: int = Field(default=0, ge=0)

    @property
    def display_size(self) -> tuple[int, int]:
        if self.rotation in (90, 270):
            return self.height, self.width
        return self.width, self.height

    @property
    def is_portrait(self) -> bool:
        w, h = self.display_size
        return h > w

    def resolved_path(self) -> Path:
        return Path(self.path)


class SourceManifest(Artifact):
    """Every source available to a project."""

    sources: list[SourceEntry] = Field(default_factory=list)

    def by_id(self, source_id: str) -> SourceEntry:
        for entry in self.sources:
            if entry.id == source_id:
                return entry
        known = ", ".join(s.id for s in self.sources) or "<none>"
        raise KeyError(f"unknown source id {source_id!r}; manifest has: {known}")

    @property
    def ids(self) -> list[str]:
        return [s.id for s in self.sources]
