"""Workspace layout.

Original media is never modified and never moved. Everything we derive lands
under a single ``edit/`` directory beside it, so a project can be inspected,
version-controlled, deleted, or handed to someone else as one unit.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from social_video.paths import app_home, is_wsl_mount_path, normalize_user_path


@dataclass(frozen=True)
class Workspace:
    """Paths within one edit workspace."""

    root: Path

    @classmethod
    def for_source(cls, source: str | Path, *, name: str = "edit") -> Workspace:
        """Choose a fast workspace without ever modifying the source.

        A Windows-drive source under ``/mnt/<drive>`` gets a workspace in the
        WSL cache. This keeps high-I/O intermediate files off mounted NTFS.
        """
        p = normalize_user_path(source, must_exist=True)
        if is_wsl_mount_path(p):
            safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", p.stem).strip("-.") or "media"
            digest = hashlib.sha256(str(p).encode("utf-8")).hexdigest()[:12]
            return cls(root=app_home() / "workspaces" / f"{safe_stem}-{digest}" / name)
        base = p.parent if p.is_file() else p
        return cls(root=base / name)

    @classmethod
    def at(cls, path: str | Path) -> Workspace:
        """Workspace at an explicit path.

        Accepts either the workspace directory itself or its parent, so
        ``social-video-agent render .`` and ``social-video-agent render ./edit`` both work.
        """
        p = normalize_user_path(path)
        if p.name != "edit" and (p / "edit").is_dir():
            p = p / "edit"
        return cls(root=p)

    # -- directories -------------------------------------------------------

    @property
    def heavy_root(self) -> Path:
        """High-I/O data stays in Linux even for an explicit /mnt workspace."""
        if is_wsl_mount_path(self.root):
            digest = hashlib.sha256(str(self.root).encode("utf-8")).hexdigest()[:12]
            return app_home() / "workspaces" / f"external-{digest}" / "edit"
        return self.root

    @property
    def cache(self) -> Path:
        return self.heavy_root / "cache"

    @property
    def transcripts(self) -> Path:
        return self.root / "transcripts"

    @property
    def analysis(self) -> Path:
        return self.root / "analysis"

    @property
    def candidates(self) -> Path:
        return self.root / "candidates"

    @property
    def captions(self) -> Path:
        return self.root / "captions"

    @property
    def assets(self) -> Path:
        return self.root / "assets"

    @property
    def context(self) -> Path:
        return self.root / "context"

    @property
    def previews(self) -> Path:
        return self.heavy_root / "previews"

    @property
    def qa(self) -> Path:
        return self.heavy_root / "qa"

    @property
    def renders(self) -> Path:
        return self.heavy_root / "renders"

    @property
    def segments(self) -> Path:
        """Intermediate per-range media. Cached by content, safe to delete."""
        return self.cache / "segments"

    @property
    def final(self) -> Path:
        return self.heavy_root / "final"

    # -- files -------------------------------------------------------------

    @property
    def project_notes(self) -> Path:
        """Durable, human-readable project memory."""
        return self.root / "project.md"

    @property
    def source_manifest(self) -> Path:
        return self.root / "source-manifest.json"

    @property
    def edit_plan(self) -> Path:
        return self.root / "edit-plan.json"

    @property
    def edl(self) -> Path:
        return self.root / "edl.json"

    @property
    def motion_plan(self) -> Path:
        return self.root / "motion-plan.json"

    @property
    def editorial_qa(self) -> Path:
        return self.root / "qa-editorial.json"

    @property
    def workflow_state(self) -> Path:
        return self.root / "workflow-state.json"

    @property
    def project_context(self) -> Path:
        return self.context / "project-context.json"

    @property
    def project_context_summary(self) -> Path:
        return self.context / "project-context.md"

    @property
    def context_sources(self) -> Path:
        return self.context / "context-sources.json"

    @property
    def technical_qa(self) -> Path:
        return self.qa / "qa-technical.json"

    @property
    def delivery_manifest(self) -> Path:
        return self.root / "delivery-manifest.json"

    @property
    def packed_transcript(self) -> Path:
        return self.root / "takes-packed.md"

    @property
    def state(self) -> Path:
        """Stage completion state, so an interrupted run can resume."""
        return self.cache / "state.json"

    def transcript_for(self, source_id: str, audio_track: int = 0) -> Path:
        suffix = "" if audio_track == 0 else f".track{audio_track}"
        return self.transcripts / f"{source_id}{suffix}.json"

    # -- creation ----------------------------------------------------------

    def ensure(self) -> Workspace:
        """Create the directory skeleton. Idempotent."""
        for directory in (
            self.root,
            self.cache,
            self.transcripts,
            self.analysis,
            self.candidates,
            self.captions,
            self.assets,
            self.context,
            self.previews,
            self.qa,
            self.renders,
            self.segments,
            self.final,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return self

    @property
    def exists(self) -> bool:
        return self.root.is_dir()
