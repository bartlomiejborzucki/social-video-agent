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


class VisualFillStrategy(str, Enum):
    """Explicit editorial choice for visual time beyond the primary shot."""

    FREEZE = "intentional_hold"
    SECONDARY_VIDEO = "secondary_video"
    END_CARD = "end_card"


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

    # Optional split A/V sources. Existing v1 EDLs keep using source/start/end.
    video_source: str | None = None
    audio_source: str | None = None
    video_start: float | None = Field(default=None, ge=0.0)
    video_end: float | None = Field(default=None, gt=0.0)
    audio_start: float | None = Field(default=None, ge=0.0)
    audio_end: float | None = Field(default=None, gt=0.0)
    freeze_at: float | None = Field(
        default=None,
        ge=0.0,
        description="Source timestamp of the last safe frame; it is held to the range end.",
    )
    freeze_duration: float | None = Field(
        default=None,
        ge=0.0,
        description="Exact output duration of an intentional last-frame hold.",
    )
    max_static_hold: float = Field(
        default=0.75,
        gt=0.0,
        description="Maximum unapproved static hold, in output seconds.",
    )
    intentional_hold: bool = False
    visual_fill_strategy: VisualFillStrategy | None = None
    visual_fill_reason: str = ""
    secondary_video_source: str | None = None
    secondary_video_start: float | None = Field(default=None, ge=0.0)
    secondary_video_end: float | None = Field(default=None, gt=0.0)
    end_card_source: str | None = None
    end_card_start: float | None = Field(default=None, ge=0.0)
    end_card_end: float | None = Field(default=None, gt=0.0)
    hold_last_frame_until: float | None = Field(
        default=None,
        gt=0.0,
        description="Minimum output duration of this range, in seconds.",
    )
    max_visual_source_time: float | None = Field(
        default=None,
        ge=0.0,
        description="Hard privacy boundary; frames after this source time may not appear.",
    )
    technical_reason: str = Field(
        default="", description="Technical justification for split A/V, freeze, or privacy limit."
    )

    @model_validator(mode="after")
    def _check_interval(self) -> EDLRange:
        if self.end <= self.start:
            raise ValueError(
                f"range on source {self.source!r} ends at {self.end} which is not after "
                f"its start {self.start}"
            )
        for kind, start, end in (
            ("video", self.effective_video_start, self.effective_video_end),
            ("audio", self.effective_audio_start, self.effective_audio_end),
        ):
            if end <= start:
                raise ValueError(f"{kind} end {end} is not after its start {start}")
        limit = self.max_visual_source_time
        declared_video_end = self.video_end if self.video_end is not None else self.end
        if self.freeze_at is not None and not (
            self.effective_video_start <= self.freeze_at <= declared_video_end
        ):
            raise ValueError("freeze_at must lie inside the effective video interval")
        if limit is not None and limit < self.effective_video_start:
            raise ValueError("max_visual_source_time must not precede video_start")
        if self.freeze_at is not None and limit is not None and self.freeze_at > limit:
            raise ValueError("freeze_at must not exceed max_visual_source_time")
        gap = self.unfilled_visual_duration
        if gap > 0.001:
            if self.visual_fill_strategy is None:
                raise ValueError(
                    f"audio/timeline outlasts safe moving video by {gap:.3f}s; set an explicit "
                    "visual_fill_strategy"
                )
            self._check_visual_fill(gap)
        elif self.visual_fill_strategy is not None:
            self._check_visual_fill(0.0)
        return self

    def _check_visual_fill(self, required: float) -> None:
        strategy = self.visual_fill_strategy
        reason = self.visual_fill_reason or self.technical_reason or self.reason
        if strategy is VisualFillStrategy.FREEZE:
            if self.freeze_at is None or self.freeze_duration is None:
                raise ValueError("intentional_hold requires freeze_at and freeze_duration")
            if self.freeze_duration + 0.001 < required:
                raise ValueError(
                    f"freeze_duration {self.freeze_duration:.3f}s does not fill the "
                    f"required {required:.3f}s"
                )
            if self.freeze_duration > self.max_static_hold and not self.intentional_hold:
                raise ValueError(
                    f"freeze_duration exceeds max_static_hold={self.max_static_hold:.2f}s; "
                    "a longer hold requires intentional_hold=true and a reason"
                )
            if self.intentional_hold and not reason.strip():
                raise ValueError("intentional_hold=true requires a written reason")
            return
        if self.intentional_hold or self.freeze_duration is not None:
            raise ValueError("intentional_hold and freeze_duration are only valid for a hold")
        if strategy is VisualFillStrategy.SECONDARY_VIDEO:
            source = self.secondary_video_source
            start = self.secondary_video_start
            end = self.secondary_video_end
            label = "secondary video"
        else:
            source = self.end_card_source
            start = self.end_card_start
            end = self.end_card_end
            label = "end card"
        if source is None or start is None or end is None or end <= start:
            raise ValueError(f"{label} strategy requires a source and valid start/end")
        available = (end - start) / self.speed
        if available + 0.001 < required:
            raise ValueError(f"{label} provides {available:.3f}s but {required:.3f}s is required")
        if not reason.strip():
            raise ValueError(f"{label} strategy requires a written reason")

    @property
    def effective_video_source(self) -> str:
        return self.video_source or self.source

    @property
    def effective_audio_source(self) -> str:
        return self.audio_source or self.source

    @property
    def effective_video_start(self) -> float:
        return self.video_start if self.video_start is not None else self.start

    @property
    def effective_video_end(self) -> float:
        end = self.video_end if self.video_end is not None else self.end
        if self.max_visual_source_time is not None:
            end = min(end, self.max_visual_source_time)
        return end

    @property
    def effective_audio_start(self) -> float:
        return self.audio_start if self.audio_start is not None else self.start

    @property
    def effective_audio_end(self) -> float:
        return self.audio_end if self.audio_end is not None else self.end

    @property
    def visual_content_end(self) -> float:
        return min(self.freeze_at or self.effective_video_end, self.effective_video_end)

    @property
    def video_duration(self) -> float:
        return self.effective_video_end - self.effective_video_start

    @property
    def primary_visual_output_duration(self) -> float:
        return (self.visual_content_end - self.effective_video_start) / self.speed

    @property
    def audio_duration(self) -> float:
        return self.effective_audio_end - self.effective_audio_start

    @property
    def duration(self) -> float:
        """Source duration of this range, before any speed change."""
        return self.end - self.start

    @property
    def unfilled_visual_duration(self) -> float:
        target = max(
            self.audio_duration / self.speed,
            self.hold_last_frame_until or 0.0,
        )
        return max(0.0, target - self.primary_visual_output_duration)

    @property
    def declared_visual_fill_duration(self) -> float:
        if self.visual_fill_strategy is VisualFillStrategy.FREEZE:
            return self.freeze_duration or 0.0
        if self.visual_fill_strategy is VisualFillStrategy.SECONDARY_VIDEO:
            if self.secondary_video_start is None or self.secondary_video_end is None:
                return 0.0
            return (self.secondary_video_end - self.secondary_video_start) / self.speed
        if self.visual_fill_strategy is VisualFillStrategy.END_CARD:
            if self.end_card_start is None or self.end_card_end is None:
                return 0.0
            return (self.end_card_end - self.end_card_start) / self.speed
        return 0.0

    @property
    def output_duration(self) -> float:
        """Duration this range occupies in the output."""
        visual = self.primary_visual_output_duration + self.declared_visual_fill_duration
        natural = max(visual, self.audio_duration / self.speed)
        return max(natural, self.hold_last_frame_until or 0.0)


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
    accepted_qa_warnings: list[str] = Field(
        default_factory=list,
        description="Exact QA check names explicitly accepted by the supervising editor.",
    )

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
            for source_id in (
                r.effective_video_source,
                r.effective_audio_source,
                r.secondary_video_source,
                r.end_card_source,
            ):
                if source_id is None:
                    continue
                if source_id not in seen:
                    seen.append(source_id)
        return seen
