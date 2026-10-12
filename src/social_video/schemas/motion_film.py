"""Claude Motion films: what the CLI asked for, and what came back.

A Claude session writes a Motion film from a spec this CLI produces; the user
exports it as an MP4 from the film's page; the CLI imports that file, cuts it
into one segment per scene and places each as a full-frame overlay. The
exported file cannot be reproduced from the workspace, so every imported
segment carries its hashes, its probe facts and the brand facts it was made
under, and brand QA checks the render against those.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from social_video.schemas.base import Artifact
from social_video.schemas.motion import MotionElement, MotionElementType
from social_video.schemas.visuals import CapabilityState

#: Graphics a film can stand in for. An exported film is opaque and full
#: frame, so a graphic that sits over the speaker cannot come from one.
FILM_TYPES = frozenset(
    {
        MotionElementType.HOOK_CARD,
        MotionElementType.CHAPTER,
        MotionElementType.CTA,
        MotionElementType.END_CARD,
        MotionElementType.QUOTE,
    }
)
#: Frame rates a Motion film can be exported at.
FILM_FPS = (24, 30, 60)
#: Motion refuses a scene shorter than this.
MIN_SCENE_SECONDS = 1.0
#: Motion refuses a film longer than this.
MAX_FILM_SECONDS = 300.0
#: Letters the player's ten built-in faces carry: Latin-1. Anything beyond
#: (ł, ő, ş, Greek, Cyrillic) needs a Google family that has it.
WESTERN_EUROPEAN = frozenset(chr(c) for c in range(0x20, 0x100))

SCENE_ID = r"^[a-z][a-z0-9-]{0,31}$"
FILM_ID = r"^[a-z][a-z0-9-]{0,47}$"


class FilmScene(Artifact):
    """One scene of the film: one graphic of the motion plan, full frame."""

    id: str = Field(pattern=SCENE_ID)
    name: str = Field(min_length=1, max_length=48)
    element_type: MotionElementType
    #: Where the segment lands in the edit's output, in seconds.
    start_in_output: float = Field(ge=0.0)
    duration: float = Field(ge=MIN_SCENE_SECONDS)
    text: str = ""
    secondary_text: str | None = None
    items: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)


class FilmPalette(Artifact):
    """The brand's colours in Motion's four roles."""

    ground: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    main: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    second: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    accent: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")

    def colours(self) -> list[str]:
        return [self.ground, self.main, self.second, self.accent]


class FilmSpec(Artifact):
    """Everything a Claude session needs to write the film, and nothing else.

    It carries text, timing, colours, a font name and pixel geometry. It never
    carries the recording; it names the logo and font file only when the
    project allows brand files to be uploaded.
    """

    film_id: str = Field(pattern=FILM_ID)
    title: str = Field(min_length=1, max_length=120)
    edl: str
    brand_contract_sha256: str | None = None
    width: int = Field(gt=0, le=4096)
    height: int = Field(gt=0, le=4096)
    fps: Literal[24, 30, 60]
    #: The EDL's own rate, when the film is exported at a different one and
    #: the import conforms it.
    conform_to_fps: str | None = None
    palette: FilmPalette
    #: The contract's font family, to be named in the film's font slots.
    font_family: str = ""
    #: Letters in the scenes' text that the player's built-in faces lack.
    #: When present, the film must name a Google family that has them.
    extended_letters: str = ""
    scenes: list[FilmScene] = Field(min_length=1)
    #: Pixels from each edge kept clear of graphics, from the contract.
    safe_margins_px: dict[str, int] = Field(default_factory=dict)
    #: Pixels each target platform's interface draws over, per edge.
    reserved_zones_px: dict[str, dict[str, int]] = Field(default_factory=dict)
    #: Why brand files may go up, or "none": then the film carries no logo and
    #: names the font by family only.
    brand_upload: Literal["none", "project_config", "explicit_flag"] = "none"
    logo_file: str | None = None
    font_file: str | None = None
    #: What the agent saw in its own tool list when the spec was written.
    #: Session-scoped: re-check on resume.
    claude_motion: CapabilityState = CapabilityState.UNKNOWN_TO_CLI
    created_at: str

    @model_validator(mode="after")
    def _check(self) -> FilmSpec:
        ids = [scene.id for scene in self.scenes]
        if len(set(ids)) != len(ids):
            raise ValueError(f"scene ids must be unique, got {ids}")
        if self.duration > MAX_FILM_SECONDS:
            raise ValueError(
                f"a Motion film is at most {MAX_FILM_SECONDS:.0f} s; this one is "
                f"{self.duration:.1f} s"
            )
        if self.brand_upload == "none" and (self.logo_file or self.font_file):
            raise ValueError("brand files are named only when their upload is permitted")
        return self

    @property
    def duration(self) -> float:
        return sum(scene.duration for scene in self.scenes)

    def offset(self, scene_id: str) -> float:
        """Where a scene starts inside the exported film: scenes play back to back."""
        at = 0.0
        for scene in self.scenes:
            if scene.id == scene_id:
                return at
            at += scene.duration
        raise KeyError(f"no scene {scene_id!r} in film {self.film_id!r}")

    def digest(self) -> str:
        """A hash of what the film is asked to show, independent of when."""
        body = self.model_dump(mode="json", exclude={"created_at", "claude_motion"})
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


class FilmSegment(Artifact):
    """One scene cut out of the user's export and placed on the timeline."""

    film_id: str = Field(pattern=FILM_ID)
    scene_id: str = Field(pattern=SCENE_ID)
    element_type: MotionElementType
    spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    #: The file the user exported, as handed over. Never modified.
    source_path: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    #: The segment cut from it, in the workspace. The artifact of record.
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: str
    duration: float = Field(gt=0)
    start_in_output: float = Field(ge=0)
    offset_in_film: float = Field(ge=0)
    exported_by: Literal["user"] = "user"
    imported_at: str
    #: The font family the session reports the film was set in.
    font_used: str = Field(min_length=1)
    #: The contract's font when the film was specified, to compare against.
    font_expected: str = ""
    brand_contract_sha256: str | None = None
    brand_upload: Literal["none", "project_config", "explicit_flag"] = "none"
    #: The motion-plan graphic this segment stands in for, kept so that
    #: removing the segment puts it back.
    replaced_element: MotionElement | None = None
    #: None until brand QA has looked at it.
    qa_accepted: bool | None = None


class FilmRecord(Artifact):
    """A spec written for a Claude session, and where it is."""

    film_id: str = Field(pattern=FILM_ID)
    spec_path: str
    spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenes: list[str]
    written_at: str


class FilmRegistry(Artifact):
    """Every film specified and every segment imported for this edit."""

    films: list[FilmRecord] = Field(default_factory=list)
    segments: list[FilmSegment] = Field(default_factory=list)

    def film(self, film_id: str) -> FilmRecord:
        for record in self.films:
            if record.film_id == film_id:
                return record
        known = ", ".join(r.film_id for r in self.films) or "<none>"
        raise KeyError(f"no Motion film {film_id!r} in this workspace; known: {known}")

    def pending(self) -> list[tuple[str, str]]:
        """Scenes specified and not yet imported, as (film, scene)."""
        done = {(s.film_id, s.scene_id) for s in self.segments}
        return [
            (record.film_id, scene)
            for record in self.films
            for scene in record.scenes
            if (record.film_id, scene) not in done
        ]
