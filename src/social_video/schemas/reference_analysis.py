"""What a reference video does on screen and in words, for an editorial read.

Two artifacts. ``ReferenceMaterial`` is written by the code: the stills it
pulled, the timed transcript it kept, the numbers it measured and what that
sample cannot show. ``ReferenceAnalysis`` is written by the agent from that
material: timed observations, hypotheses that cite them, the limits of the
read and the stretches a person should still watch. The pattern it names is
a way of telling a story to reuse with the user's own footage; no wording,
face, voice or graphic of the reference is carried over.
"""

from __future__ import annotations

from enum import Enum
from typing import ClassVar

from pydantic import Field, model_validator

from social_video.schemas.base import Artifact


class FrameReason(str, Enum):
    FIRST = "first"
    #: Sampled densely through the opening seconds.
    OPENING = "opening"
    #: Just after a detected cut.
    CUT = "cut"
    SHOT_MIDDLE = "shot-middle"
    LAST = "last"


class ReferenceFrame(Artifact):
    #: The id observations cite, e.g. ``f003``.
    id: str
    at: float = Field(ge=0.0)
    reason: FrameReason
    path: str


class ReferenceMeasures(Artifact):
    first_cut_seconds: float | None = None
    first_sentence_seconds: float | None = None
    #: The longest pauses as ``[start, end]``, longest first.
    longest_pauses: list[tuple[float, float]] = Field(default_factory=list)
    cut_times: list[float] = Field(default_factory=list)


class ReferenceMaterial(Artifact):
    reference: str
    reference_fingerprint: str
    duration: float = Field(gt=0.0)
    frames: list[ReferenceFrame]
    #: The timed transcript of the reference, when it was transcribed.
    transcript: str | None = None
    measures: ReferenceMeasures
    #: What this sample cannot show. Copied into every analysis built on it.
    limitations: list[str] = Field(min_length=1)


class Evidence(str, Enum):
    FRAME = "frame"
    TRANSCRIPT = "transcript"
    MEASURE = "measure"


class Observation(Artifact):
    """Something visible or audible at a stated moment, not a judgement of it."""

    id: str = Field(min_length=1)
    at: float | None = Field(default=None, ge=0.0)
    frame: str | None = None
    evidence: Evidence
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _anchored(self) -> Observation:
        if self.at is None and self.frame is None:
            raise ValueError(f"observation {self.id} needs a time ('at') or a frame id")
        return self


class Hypothesis(Artifact):
    """Why something might work. Never evidence on its own."""

    text: str = Field(min_length=1)
    based_on: list[str] = Field(min_length=1)


class Section(Artifact):
    observations: list[Observation] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    #: Said instead of observations when the reference has no such part.
    not_found: str | None = None


class ReviewSpan(Artifact):
    """A stretch the stills may misread: a quick gesture, a move, a reveal."""

    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    reason: str = Field(min_length=1)


class ReferenceAnalysis(Artifact):
    reference_fingerprint: str
    #: What stops the viewer in the first seconds.
    opening_attention: Section
    #: What is said aloud and what is only written on screen.
    said_vs_written: Section
    #: The promise the video makes.
    promise: Section
    #: How it develops the topic.
    development: Section
    #: Where the promise is kept.
    payoff: Section
    ending: Section
    #: How to present the user's own material this way, in their own words.
    transferable_pattern: str = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)
    needs_review: list[ReviewSpan] = Field(default_factory=list)
    #: What must not be carried over: wording, faces, voice, graphics.
    not_to_copy: list[str] = Field(default_factory=list)

    SECTIONS: ClassVar[tuple[str, ...]] = (
        "opening_attention",
        "said_vs_written",
        "promise",
        "development",
        "payoff",
        "ending",
    )

    def sections(self) -> list[tuple[str, Section]]:
        return [(name, getattr(self, name)) for name in self.SECTIONS]
