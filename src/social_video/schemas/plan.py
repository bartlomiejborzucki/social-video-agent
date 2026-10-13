"""The edit plan and clip candidates: editorial intent, kept out of the EDL.

The plan holds semantic decisions ("drop the repeated explanation", "open on
this sentence"). The EDL holds exact timestamps. Keeping them apart means the
reasoning stays reviewable and revisable without re-deriving frame numbers, and
it keeps editorial judgement out of the media execution code.
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from social_video.schemas.base import Artifact
from social_video.schemas.edl import ReframePlan


class PlanAction(str, Enum):
    KEEP = "keep"
    DROP = "drop"
    TIGHTEN = "tighten"
    REORDER = "reorder"
    INSERT_OVERLAY = "insert_overlay"


class PlanItem(Artifact):
    """One editorial decision about one span of source."""

    action: PlanAction
    source: str
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    quote: str = ""
    #: Why. Written for a human reader, not a log.
    reason: str = ""
    beat: str = ""
    order: int | None = Field(default=None, description="Output position when reordering.")
    cut: str | None = Field(
        default=None,
        description="The accepted cut candidate this drop came from. Such a drop is removed "
        "from inside kept spans too, after their edges are snapped to words.",
    )
    #: Sound from another recording under this item's picture: a voice off
    #: camera, recorded separately. ``start``/``end`` are then the picture's
    #: span in ``source``, and the words come from ``audio_source``.
    audio_source: str | None = None
    audio_start: float | None = Field(default=None, ge=0.0)
    audio_end: float | None = Field(default=None, gt=0.0)
    #: A fixed framing for this item, in source pixels as displayed (after any
    #: rotation the file declares). Ranges with one are left alone by `reframe`.
    reframe: ReframePlan | None = None

    @model_validator(mode="after")
    def _check_interval(self) -> PlanItem:
        if self.end <= self.start:
            raise ValueError(f"plan item ends at {self.end}, not after start {self.start}")
        voice = (self.audio_source, self.audio_start, self.audio_end)
        if any(v is not None for v in voice) and any(v is None for v in voice):
            raise ValueError("audio_source, audio_start and audio_end are set together")
        start, end = self.audio_start, self.audio_end
        if start is not None and end is not None and end <= start:
            raise ValueError(f"audio ends at {end}, not after its start {start}")
        return self

    @property
    def sound_source(self) -> str:
        """The recording whose words this item keeps."""
        return self.audio_source or self.source

    @property
    def sound_span(self) -> tuple[float, float]:
        if self.audio_start is not None and self.audio_end is not None:
            return self.audio_start, self.audio_end
        return self.start, self.end


class EditPlan(Artifact):
    """The editorial strategy for one deliverable."""

    goal: str = Field(description="What this edit is for, in one sentence.")
    profile: str = Field(default="talking-head", description="Output profile name.")
    target_duration: float | None = Field(default=None, gt=0.0)
    strategy: str = Field(default="", description="The approach, in a short paragraph.")
    items: list[PlanItem] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    style_sources: list[str] = Field(
        default_factory=list,
        description="Project-context files that influenced editorial choices.",
    )
    user_overrides: list[str] = Field(
        default_factory=list,
        description="Current-request choices that intentionally override project defaults.",
    )

    @property
    def kept(self) -> list[PlanItem]:
        return [i for i in self.items if i.action in (PlanAction.KEEP, PlanAction.TIGHTEN)]


class CandidateScores(Artifact):
    """Editorial heuristics, not measurements.

    These are the agent's judgements on a 0-1 scale. They are recorded so a
    selection can be explained and argued with, not because they are objective.
    """

    hook_quality: float = Field(ge=0.0, le=1.0)
    standalone: float = Field(ge=0.0, le=1.0, description="Comprehensible without context.")
    information_density: float = Field(ge=0.0, le=1.0)
    payoff: float = Field(ge=0.0, le=1.0)
    ending_quality: float = Field(ge=0.0, le=1.0)
    context_dependency: float = Field(
        ge=0.0, le=1.0, description="How much prior context it needs. Lower is better."
    )

    @property
    def overall(self) -> float:
        """Unweighted mean with context dependency inverted.

        Deliberately simple: a weighted formula would imply a precision these
        numbers do not have.
        """
        positives = [
            self.hook_quality,
            self.standalone,
            self.information_density,
            self.payoff,
            self.ending_quality,
            1.0 - self.context_dependency,
        ]
        return sum(positives) / len(positives)


class ClipCandidate(Artifact):
    """A span of a long source that might stand alone as a short."""

    id: str
    source: str
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    topic: str = ""
    transcript: str = ""
    scores: CandidateScores | None = None
    #: Why this span was put forward, and why these boundaries.
    reason: str = ""
    selected: bool = False

    @model_validator(mode="after")
    def _check_interval(self) -> ClipCandidate:
        if self.end <= self.start:
            raise ValueError(f"candidate {self.id!r} ends at {self.end}, not after {self.start}")
        return self

    @property
    def duration(self) -> float:
        return self.end - self.start


class ShortEntry(Artifact):
    """One materialised short: its own workspace, its own EDL."""

    id: str
    workspace: str
    edl: str
    source: str
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    topic: str = ""


class ShortsIndex(Artifact):
    """Everything materialised from one candidate set."""

    parent_workspace: str
    shorts: list[ShortEntry] = Field(default_factory=list)


class CandidateSet(Artifact):
    """All candidates discovered for one source."""

    source: str
    candidates: list[ClipCandidate] = Field(default_factory=list)

    def ranked(self) -> list[ClipCandidate]:
        """Best first. Unscored candidates sort last."""
        return sorted(
            self.candidates,
            key=lambda c: c.scores.overall if c.scores else -1.0,
            reverse=True,
        )


class CutKind(str, Enum):
    FILLER = "filler"
    STUTTER = "stutter"
    FALSE_START = "false_start"
    PAUSE = "pause"


class CutConfidence(str, Enum):
    #: Almost always a stumble: dead air, a doubled word, a restarted phrase.
    HIGH = "high"
    #: Often a stumble, sometimes how the person talks. Listen first.
    MEDIUM = "medium"


class CutCandidate(Artifact):
    """A span the code found by timing and repetition, awaiting the agent's call.

    Nothing here is applied on its own. ``cuts accept`` turns the candidates the
    agent chose into drop items in the edit plan, with this reason attached.
    """

    id: str
    kind: CutKind
    confidence: CutConfidence
    source: str
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    quote: str = ""
    reason: str = ""

    @model_validator(mode="after")
    def _check_interval(self) -> CutCandidate:
        if self.end <= self.start:
            raise ValueError(f"cut {self.id!r} ends at {self.end}, not after {self.start}")
        return self

    @property
    def duration(self) -> float:
        return self.end - self.start


class CutCandidateSet(Artifact):
    """Every cut candidate found in one transcript."""

    source: str
    transcript_fingerprint: str = Field(
        description="Source fingerprint the candidates were found in, so stale ones are refused."
    )
    candidates: list[CutCandidate] = Field(default_factory=list)

    def by_id(self, candidate_id: str) -> CutCandidate:
        for candidate in self.candidates:
            if candidate.id == candidate_id:
                return candidate
        known = ", ".join(c.id for c in self.candidates) or "<none>"
        raise KeyError(f"unknown cut candidate {candidate_id!r}; known: {known}")
