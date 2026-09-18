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

    @model_validator(mode="after")
    def _check_interval(self) -> PlanItem:
        if self.end <= self.start:
            raise ValueError(f"plan item ends at {self.end}, not after start {self.start}")
        return self


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
