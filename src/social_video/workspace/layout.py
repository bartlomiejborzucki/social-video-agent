"""Workspace layout.

Original media is never modified and never moved. Everything we derive lands
under a single ``edit/`` directory beside it, so a project can be inspected,
version-controlled, deleted, or handed to someone else as one unit.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    """Paths within one edit workspace."""

    root: Path

    @classmethod
    def for_source(cls, source: str | Path, *, name: str = "edit") -> Workspace:
        """Workspace beside a source file."""
        p = Path(source).expanduser().resolve()
        base = p.parent if p.is_file() else p
        return cls(root=base / name)

    @classmethod
    def at(cls, path: str | Path) -> Workspace:
        """Workspace at an explicit path.

        Accepts either the workspace directory itself or its parent, so
        ``social-video render .`` and ``social-video render ./edit`` both work.
        """
        p = Path(path).expanduser().resolve()
        if p.name != "edit" and (p / "edit").is_dir():
            p = p / "edit"
        return cls(root=p)

    # -- directories -------------------------------------------------------

    @property
    def cache(self) -> Path:
        return self.root / "cache"

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
    def previews(self) -> Path:
        return self.root / "previews"

    @property
    def qa(self) -> Path:
        return self.root / "qa"

    @property
    def renders(self) -> Path:
        return self.root / "renders"

    @property
    def segments(self) -> Path:
        """Intermediate per-range media. Cached by content, safe to delete."""
        return self.cache / "segments"

    @property
    def final(self) -> Path:
        return self.root / "final"

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
