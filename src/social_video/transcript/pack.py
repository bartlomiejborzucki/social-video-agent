"""The packed transcript: what the agent actually reads.

This is the strongest idea in the upstream project and it is kept. The agent
reasons over a compact, phrase-level view rather than megabytes of raw token
JSON; the exact data stays on disk for the tools that need it.

Adapted from browser-use/video-use ``helpers/pack_transcripts.py`` (MIT,
Copyright (c) 2026 Browser Use). The grouping rule -- flush on a long gap or a
speaker change -- is theirs and is preserved. Changed here:

* A phrase is capped in length. Upstream has no cap, so continuous speech with
  no half-second gap collapses into one multi-hundred-word line with a single
  unusable time range.
* Word offsets are emitted for long phrases, so a cut inside a phrase can still
  land on a word boundary. Upstream exposes phrase edges only, which makes its
  own "never cut inside a word" rule impossible to follow from this view.
* Duration is the media duration, not the span between first and last speech.
  Upstream reports the latter, so a clip with a long silent lead-in is described
  as shorter than it is and runtime estimates come out wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from social_video.schemas.transcript import TokenType, Transcript, TranscriptToken

#: Gap at or above which a phrase is flushed.
DEFAULT_SILENCE = 0.5
#: Upper bound on phrase length, so every line stays individually addressable.
DEFAULT_MAX_WORDS = 28


@dataclass
class Phrase:
    start: float
    end: float
    words: list[TranscriptToken] = field(default_factory=list)
    speaker: str | None = None

    @property
    def text(self) -> str:
        return _tidy(" ".join(w.text for w in self.words))

    @property
    def duration(self) -> float:
        return self.end - self.start


def group_phrases(
    transcript: Transcript,
    *,
    silence: float = DEFAULT_SILENCE,
    max_words: int = DEFAULT_MAX_WORDS,
) -> list[Phrase]:
    """Group the token stream into phrases on silences and speaker changes."""
    phrases: list[Phrase] = []
    current: list[TranscriptToken] = []
    speaker: str | None = None

    def flush() -> None:
        nonlocal current, speaker
        if current:
            phrases.append(
                Phrase(
                    start=current[0].start,
                    end=current[-1].end,
                    words=list(current),
                    speaker=speaker,
                )
            )
        current = []

    for token in transcript.tokens:
        if token.type is TokenType.SPACING:
            # An explicit gap. This is why spacing tokens are synthesised for
            # providers that do not emit them: without it, phrasing degrades.
            if token.duration >= silence:
                flush()
            continue

        if current and token.speaker != speaker:
            flush()
        if not current:
            speaker = token.speaker
        current.append(token)

        if len(current) >= max_words:
            flush()

    flush()
    return phrases


def format_time(seconds: float) -> str:
    """Zero-padded seconds, matching the ranges used in the EDL."""
    return f"{seconds:06.2f}"


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}m {rest:04.1f}s"


def pack_transcript(
    transcript: Transcript,
    *,
    silence: float = DEFAULT_SILENCE,
    max_words: int = DEFAULT_MAX_WORDS,
    word_offsets_above: int = 12,
) -> str:
    """Render one transcript as a compact markdown block."""
    phrases = group_phrases(transcript, silence=silence, max_words=max_words)
    speakers = transcript.speakers

    lines: list[str] = []
    header = (
        f"## {transcript.source_id}  "
        f"(duration: {format_duration(transcript.duration)}, {len(phrases)} phrases"
    )
    if speakers:
        header += f", {len(speakers)} speakers"
    if not transcript.has_word_timestamps and transcript.words:
        header += ", WORD TIMINGS UNRELIABLE"
    lines.append(header + ")")
    lines.append("")

    for phrase in phrases:
        tag = f" S{_short_speaker(phrase.speaker)}" if phrase.speaker else ""
        lines.append(
            f"  [{format_time(phrase.start)}-{format_time(phrase.end)}]{tag} {phrase.text}"
        )
        # For a long phrase, give the agent interior word edges so it can cut
        # inside it without guessing.
        if len(phrase.words) > word_offsets_above:
            marks = "  ".join(f"{format_time(w.start)}:{w.text}" for w in phrase.words[::4])
            lines.append(f"       words: {marks}")
    lines.append("")
    return "\n".join(lines)


def pack_transcripts(
    transcripts: list[Transcript],
    *,
    silence: float = DEFAULT_SILENCE,
    max_words: int = DEFAULT_MAX_WORDS,
    output: Path | None = None,
) -> str:
    """Render every transcript in a project into one readable document."""
    lines = [
        "# Packed transcripts",
        "",
        f"Phrase-level, grouped on silences >= {silence:.1f}s or a speaker change.",
        "Use the `[start-end]` ranges to address cuts in the EDL. Times are seconds",
        "into the original source, not into any edit.",
        "",
    ]
    for transcript in transcripts:
        lines.append(pack_transcript(transcript, silence=silence, max_words=max_words))

    document = "\n".join(lines)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        # UTF-8 explicitly: this document contains a `>=` and arbitrary speech in
        # any language.
        output.write_text(document, encoding="utf-8")
    return document


_PUNCT_FIXES = (
    (" ,", ","),
    (" .", "."),
    (" ?", "?"),
    (" !", "!"),
    (" ;", ";"),
    (" :", ":"),
    (" )", ")"),
    ("( ", "("),
    (" …", "…"),
    (" %", "%"),
)


def _tidy(text: str) -> str:
    """Re-join punctuation that tokenisation separated from its word."""
    for bad, good in _PUNCT_FIXES:
        text = text.replace(bad, good)
    return " ".join(text.split())


def _short_speaker(speaker: str | None) -> str:
    """`speaker_0` reads as `0`; anything else is passed through."""
    if not speaker:
        return ""
    return speaker.removeprefix("speaker_").removeprefix("SPEAKER_")
