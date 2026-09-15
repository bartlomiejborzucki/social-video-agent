"""Turn provider output into the canonical transcript.

The one job that matters here: every provider must end up producing the same
token stream shape, including the ``spacing`` tokens that carry inter-word
gaps. Phrase packing groups on those gaps, so a provider that omits them
produces visibly worse phrasing for the agent to read.
"""

from __future__ import annotations

from itertools import pairwise

from social_video.schemas.transcript import (
    TokenType,
    Transcript,
    TranscriptSegment,
    TranscriptToken,
)

#: Gaps shorter than this are not worth a token; they are within the noise of
#: any aligner and would double the token count for nothing.
MIN_SPACING = 0.01


def synthesize_spacing(words: list[TranscriptToken]) -> list[TranscriptToken]:
    """Interleave ``spacing`` tokens into a word stream.

    Providers other than ElevenLabs report words only. Rather than teaching
    every downstream consumer two shapes, we materialise the gaps here.
    """
    if not words:
        return []
    ordered = sorted(words, key=lambda w: (w.start, w.end))
    out: list[TranscriptToken] = [ordered[0]]
    for previous, current in pairwise(ordered):
        gap = current.start - previous.end
        if gap >= MIN_SPACING:
            out.append(
                TranscriptToken(
                    type=TokenType.SPACING,
                    text=" ",
                    start=previous.end,
                    end=current.start,
                    # A gap belongs to whoever was speaking before it; that is
                    # what makes speaker-change detection work at phrase level.
                    speaker=previous.speaker,
                )
            )
        out.append(current)
    return out


def build_transcript(
    *,
    source_id: str,
    source_fingerprint: str,
    duration: float,
    provider: str,
    segments: list[TranscriptSegment],
    language: str | None = None,
    language_confidence: float | None = None,
    provider_model: str | None = None,
    provider_options: dict[str, str] | None = None,
    audio_track: int = 0,
) -> Transcript:
    """Assemble a canonical transcript from per-segment provider output."""
    words: list[TranscriptToken] = []
    for segment in segments:
        words.extend(t for t in segment.tokens if t.type is TokenType.WORD)
        # Audio events, where a provider reports them, sit in the stream too.
        words.extend(t for t in segment.tokens if t.type is TokenType.AUDIO_EVENT)

    tokens = synthesize_spacing(words)

    return Transcript(
        source_id=source_id,
        source_fingerprint=source_fingerprint,
        audio_track=audio_track,
        language=language,
        language_confidence=language_confidence,
        duration=duration,
        provider=provider,
        provider_model=provider_model,
        provider_options=provider_options or {},
        segments=segments,
        tokens=tokens,
    )


def clean_word_text(text: str) -> str:
    """Trim provider whitespace without touching the word itself.

    Notably does *not* strip punctuation or change case: punctuation is what
    makes sentence boundaries findable, and casing is the caption style's
    decision, made at render time.
    """
    return text.strip()
