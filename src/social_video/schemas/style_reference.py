"""The measured rhythm of a reference video the user wants their edit to feel like.

Only numbers are kept: shot lengths, cut rate, how much of the running time is
speech, how fast it is spoken and how soon the first thought lands. No frame,
word or sound of the reference reaches the edit. The recommendation maps those
numbers onto settings this project already has, and the agent proposes them;
it does not write project config.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from social_video.schemas.base import Artifact


class ShotRhythm(Artifact):
    count: int = Field(ge=1)
    cuts_per_minute: float = Field(ge=0.0)
    median_seconds: float = Field(ge=0.0)
    p25_seconds: float = Field(ge=0.0)
    p75_seconds: float = Field(ge=0.0)
    #: When the first cut lands; None for a single continuous shot.
    first_cut_seconds: float | None = Field(default=None, ge=0.0)


class SpeechRhythm(Artifact):
    #: Share of the running time that is not silence.
    sound_ratio: float = Field(ge=0.0, le=1.0)
    pauses_per_minute: float = Field(ge=0.0)
    longest_pause_seconds: float = Field(ge=0.0)
    #: Filled only when the reference was transcribed.
    words_per_minute: float | None = Field(default=None, ge=0.0)
    #: End of the first sentence: how long the reference takes to say its hook.
    first_sentence_seconds: float | None = Field(default=None, ge=0.0)


class StyleRecommendation(Artifact):
    motion_energy: Literal["calm", "lively", "bold"]
    #: Aim for shots (or jump-cut spans) around this length.
    target_shot_seconds: float = Field(gt=0.0)
    #: Land the hook within this many seconds.
    hook_within_seconds: float = Field(gt=0.0)
    #: Why, in terms the agent can repeat to the user.
    reasons: list[str] = Field(default_factory=list)


class StyleReference(Artifact):
    reference: str = Field(description="Path of the reference as analysed.")
    reference_fingerprint: str
    duration: float = Field(gt=0.0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0.0)
    aspect_ratio: str
    shots: ShotRhythm
    speech: SpeechRhythm | None = None
    recommendation: StyleRecommendation
    #: Frames of the reference, one per shot, for the agent to judge the look.
    #: Kept in the workspace for review only; never rendered into the edit.
    contact_sheet: str | None = None
