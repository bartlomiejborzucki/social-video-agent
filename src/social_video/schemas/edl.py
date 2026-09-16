"""The Edit Decision List: renderer-independent, human-readable, validated.

The EDL says exactly what to render. It is deliberately separate from the
edit plan, which says *why*. A given EDL renders identically every time.
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from social_video.schemas.base import Artifact


class ReframeMode(str, Enum):
    """How a range is fitted to an output canvas that differs in aspect."""

    #: Keep the whole frame, pad the remainder. Never crops content.
    FIT = "fit"
    #: Fixed crop window, centred.
    CENTER = "center"
    #: Fixed crop window at an explicit position.
    MANUAL = "manual"
    #: Crop follows detected faces, piecewise-constant with smoothing.
    FACE = "face"
    #: Crop follows the active speaker where one can be identified.
    SPEAKER = "speaker"
    #: Two people stacked vertically.
    SPLIT_STACK = "split_stack"


class CropKeyframe(Artifact):
    """Crop-window position at a point in time, in source pixels."""

    t: float = Field(ge=0.0, description="Seconds from the start of the range.")
    x: int = Field(ge=0)
    y: int = Field(ge=0)


class ReframePlan(Artifact):
    """A resolved, inspectable plan for getting a range onto the canvas.

    Structure adapted from AgriciDaniel/claude-shorts ``compute_reframe.py``
    (MIT): separating "compute the crop plan" from "render the crop plan" keeps
    the framing decision reviewable instead of buried inside a filter string.
    """

    mode: ReframeMode = ReframeMode.FIT
    crop_width: int | None = Field(default=None, gt=0)
    crop_height: int | None = Field(default=None, gt=0)
    keyframes: list[CropKeyframe] = Field(default_factory=list)
    #: Why this framing was chosen, in the agent's own words.
    reason: str = ""

    @model_validator(mode="after")
    def _needs_geometry(self) -> ReframePlan:
        needs = {
            ReframeMode.CENTER,
            ReframeMode.MANUAL,
            ReframeMode.FACE,
            ReframeMode.SPEAKER,
        }
        mode = self.mode.value
        if self.mode in needs and not (self.crop_width and self.crop_height):
            raise ValueError(f"reframe mode {mode!r} requires crop_width and crop_height")
        tracked = {ReframeMode.MANUAL, ReframeMode.FACE, ReframeMode.SPEAKER}
        if self.mode in tracked and not self.keyframes:
            raise ValueError(f"reframe mode {mode!r} requires at least one keyframe")
        return self


class Overlay(Artifact):
    """A visual laid over the timeline (graphic, B-roll, picture-in-picture)."""

    file: str
    start_in_output: float = Field(ge=0.0)
    duration: float = Field(gt=0.0)
    x: str = "0"
    y: str = "0"
    scale_width: int | None = Field(default=None, gt=0)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str = ""

    @property
    def end_in_output(self) -> float:
        return self.start_in_output + self.duration


class EDLRange(Artifact):
    """One cut: a span of one source, placed in output order."""

    source: str = Field(description="Source id, resolved against the SourceManifest.")
    start: float = Field(ge=0.0, description="In-point in the source, seconds.")
    end: float = Field(gt=0.0, description="Out-point in the source, seconds.")
    audio_track: int = Field(
        default=0,
        ge=0,
        description=(
            "Zero-based audio track to render from. Must match the track that "
            "was transcribed, or the captions describe audio nobody can hear."
        ),
    )

    # Editorial metadata. Carried so the EDL stays readable and reviewable;
    # upstream defines `quote` and `reason` in its example and then never reads
    # them anywhere in code.
    beat: str = Field(default="", description="Narrative role, e.g. HOOK, POINT, PAYOFF.")
    quote: str = Field(default="", description="The words this range contains.")
    reason: str = Field(default="", description="Why this range was chosen or trimmed here.")
    speaker: str | None = None

    reframe: ReframePlan | None = None
    zoom: float = Field(default=1.0, ge=1.0, le=2.0, description="Punch-in factor.")
    speed: float = Field(default=1.0, gt=0.0, le=4.0)
    audio_gain_db: float = Field(default=0.0, ge=-30.0, le=30.0)
    grade: str = ""
    transition_in: str = "cut"

    @model_validator(mode="after")
    def _check_interval(self) -> EDLRange:
        if self.end <= self.start:
            raise ValueError(
                f"range on source {self.source!r} ends at {self.end} which is not after "
                f"its start {self.start}"
            )
        return self

    @property
    def duration(self) -> float:
        """Source duration of this range, before any speed change."""
        return self.end - self.start

    @property
    def output_duration(self) -> float:
        """Duration this range occupies in the output."""
        return self.duration / self.speed


class EDL(Artifact):
    """A complete, renderable edit."""

    #: Free-form label so a workspace can hold several deliverables.
    name: str = "main"
    ranges: list[EDLRange] = Field(min_length=1)

    output_width: int = Field(default=1080, gt=0)
    output_height: int = Field(default=1920, gt=0)
    #: Exact rational. Null means "preserve the source rate".
    output_fps: str | None = None

    default_reframe: ReframeMode = ReframeMode.FIT
    grade: str = ""
    overlays: list[Overlay] = Field(default_factory=list)
    captions: str | None = Field(default=None, description="Path to a CaptionTrack artifact.")
    brand_profile: str | None = None
    normalize_audio: bool = True

    @model_validator(mode="after")
    def _check_canvas(self) -> EDL:
        if self.output_width % 2 or self.output_height % 2:
            raise ValueError(
                f"output dimensions must be even for yuv420p, got "
                f"{self.output_width}x{self.output_height}"
            )
        return self

    @property
    def total_duration(self) -> float:
        """Expected output duration. QA asserts the render matches this."""
        return sum(r.output_duration for r in self.ranges)

    def source_ids(self) -> list[str]:
        seen: list[str] = []
        for r in self.ranges:
            if r.source not in seen:
                seen.append(r.source)
        return seen
