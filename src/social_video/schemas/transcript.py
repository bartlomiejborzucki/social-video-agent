"""The canonical transcript.

One representation, whatever produced it. Nothing downstream may depend on a
particular provider's JSON.

The token model is deliberately the ElevenLabs Scribe *shape* -- ``word``,
``spacing``, ``audio_event`` -- because that is what the phrase packer and the
timeline view meaningfully branch on, and because it carries information a flat
word list cannot: an explicit, timed gap between words. Providers that do not
emit gaps have them synthesised during normalisation, so a faster-whisper
transcript packs into exactly the same phrases as a Scribe one.

This is the thing the parleyw/video-use fork got wrong: it declared a canonical
schema, then passed ElevenLabs JSON through verbatim while every local backend
emitted only ``word`` tokens, so phrase grouping silently degraded and audio
events vanished.
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from social_video.schemas.base import Artifact


class TokenType(str, Enum):
    WORD = "word"
    #: An explicit gap between words. Duration is what matters, not the text.
    SPACING = "spacing"
    #: A non-speech event such as (laughs) or (applause), when the provider
    #: reports one.
    AUDIO_EVENT = "audio_event"


class TranscriptToken(Artifact):
    """One timed token. Times are seconds from the start of the source."""

    type: TokenType = TokenType.WORD
    text: str
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    speaker: str | None = Field(
        default=None, description="Provider-assigned speaker label, when diarised."
    )
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_interval(self) -> TranscriptToken:
        if self.end < self.start:
            raise ValueError(f"token ends before it starts: {self.start} -> {self.end}")
        return self

    @property
    def duration(self) -> float:
        return self.end - self.start


class TranscriptSegment(Artifact):
    """A provider-level segment (usually an utterance or VAD chunk)."""

    text: str
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    speaker: str | None = None
    tokens: list[TranscriptToken] = Field(default_factory=list)


class Transcript(Artifact):
    """A complete transcript of one audio track of one source."""

    source_id: str = Field(description="Stable id of the source this transcribes.")
    source_fingerprint: str = Field(
        description="Content fingerprint of the source, so staleness is detectable."
    )
    audio_track: int = Field(default=0, ge=0)
    language: str | None = None
    language_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    duration: float = Field(ge=0.0, description="Duration of the source media, not of speech.")

    provider: str = Field(description="Backend that produced this, e.g. 'faster-whisper'.")
    provider_model: str | None = None
    provider_options: dict[str, str] = Field(default_factory=dict)

    segments: list[TranscriptSegment] = Field(default_factory=list)
    tokens: list[TranscriptToken] = Field(
        default_factory=list,
        description="Flat, time-ordered token stream including synthesised spacing.",
    )

    @property
    def words(self) -> list[TranscriptToken]:
        return [t for t in self.tokens if t.type is TokenType.WORD]

    @property
    def has_word_timestamps(self) -> bool:
        """Whether word times are real rather than an even split of a segment.

        Word-boundary cutting is the core premise; a transcript without genuine
        word timings must not be used to place cuts.
        """
        words = self.words
        if len(words) < 2:
            return False
        # Evenly distributed fake timings produce near-identical durations
        # across a whole segment. Real speech does not.
        durations = [w.duration for w in words if w.duration > 0]
        if len(durations) < 2:
            return False
        mean = sum(durations) / len(durations)
        if mean <= 0:
            return False
        variance = sum((d - mean) ** 2 for d in durations) / len(durations)
        return (variance**0.5) / mean > 0.05

    @property
    def speakers(self) -> list[str]:
        return sorted({t.speaker for t in self.tokens if t.speaker} or set())

    def snap_to_word_boundary(self, time: float, *, prefer: str = "nearest") -> float:
        """Move a timestamp to the nearest word edge.

        ``prefer`` is ``"start"`` (round down to a word start, for a cut in),
        ``"end"`` (round up to a word end, for a cut out), or ``"nearest"``.
        Returns the input unchanged when there are no words to snap to.

        Upstream states "never cut inside a word" as a hard rule but provides
        nothing that enforces it, and its packed view exposes only phrase edges,
        so the rule is not merely unenforced but unenforceable from the agent's
        primary reading surface.
        """
        words = self.words
        if not words:
            return time
        if prefer == "start":
            candidates = [w.start for w in words]
        elif prefer == "end":
            candidates = [w.end for w in words]
        else:
            candidates = [w.start for w in words] + [w.end for w in words]
        return min(candidates, key=lambda c: abs(c - time))
