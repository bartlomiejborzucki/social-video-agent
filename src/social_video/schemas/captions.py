"""Captions as data.

Captions stay structured until the final render. They are never burned in
early, so restyling, correcting a misheard word, or repositioning does not mean
re-cutting the video.
"""

from __future__ import annotations

from itertools import pairwise

from pydantic import Field, model_validator

from social_video.schemas.base import Artifact


class CaptionWord(Artifact):
    """One word inside a cue, for active-word highlighting."""

    text: str
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)


class CaptionCue(Artifact):
    """One caption, timed against the *output* timeline."""

    index: int = Field(ge=1)
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    text: str
    speaker: str | None = None
    words: list[CaptionWord] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_interval(self) -> CaptionCue:
        if self.end <= self.start:
            raise ValueError(f"cue {self.index} ends at {self.end}, not after {self.start}")
        return self


class CaptionTrack(Artifact):
    """A complete caption track for one deliverable."""

    language: str | None = None
    cues: list[CaptionCue] = Field(default_factory=list)
    #: Set when a human or the agent has corrected ASR output, so a later
    #: re-transcription does not silently discard the corrections.
    corrected: bool = False

    @property
    def duration(self) -> float:
        return max((c.end for c in self.cues), default=0.0)

    def overlapping(self) -> list[tuple[int, int]]:
        """Pairs of cue indices whose intervals overlap. Should be empty."""
        ordered = sorted(self.cues, key=lambda c: c.start)
        bad = []
        for a, b in pairwise(ordered):
            if b.start < a.end:
                bad.append((a.index, b.index))
        return bad
