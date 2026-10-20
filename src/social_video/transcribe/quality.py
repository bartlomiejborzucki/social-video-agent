"""Whether a transcript is fit to cut on, and which model to try when it is not.

A transcript can come back complete and still be wrong. Speech over a music
bed makes the smaller Whisper models emit note symbols, replacement characters
and "[Music]" annotations; quiet passages make them loop one phrase; an
English-only (``.en``) model silently translates any other language into
English. None of that fails the run, so it is measured here and reported with
a concrete next step instead of surfacing later as captions that drift or say
something nobody said.

The assessment only warns. Whether to re-transcribe is the user's call: a
larger model costs minutes on a CPU, and a recording that is mostly music may
be exactly what was intended.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from social_video.schemas.transcript import Transcript, TranscriptToken

#: The models worth stepping up through, smallest first. `large-v3-turbo`
#: trades accuracy for speed, so it is not a step up from `medium`.
MODEL_LADDER = ("tiny", "base", "small", "medium", "large-v3")

#: Share of word tokens that are music notes, replacement characters, sound
#: annotations or bare punctuation above which the model is losing the voice.
JUNK_RATIO_LIMIT = 0.2
#: Word confidence below which a token counts as a guess.
LOW_CONFIDENCE = 0.4
#: Share of guessed words above which the transcript should not place cuts.
LOW_CONFIDENCE_RATIO_LIMIT = 0.25
#: A phrase of up to this many words repeated back to back ...
LOOP_MAX_PHRASE = 4
#: ... at least this many times is a decoding loop, not emphasis.
LOOP_MIN_REPEATS = 4
#: Detected-language confidence below which the language should be named.
LANGUAGE_CONFIDENCE_LIMIT = 0.5

#: A word longer than this is usually a false start and a pause glued on.
LONG_WORD = 1.2
#: Silence this long inside one word means the word is not one word.
INNER_SILENCE = 0.3
#: Context kept either side of a suspect word in the suggested --refine span.
REFINE_CONTEXT = 0.5

_JUNK_CHARS = ("♪", "♫", "♬", "�")
_ANNOTATION = re.compile(r"^[\[(*].*[\])*]$")
_HAS_WORD_CHAR = re.compile(r"\w")


@dataclass(frozen=True)
class SuspectWord:
    """A word whose timing the sound contradicts: worth re-transcribing."""

    text: str
    start: float
    end: float
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class TranscriptQuality:
    words: int
    junk_ratio: float
    low_confidence_ratio: float | None
    #: Start time of each decoding loop found.
    loops: tuple[float, ...]
    model: str | None
    language: str | None
    language_confidence: float | None
    warnings: tuple[str, ...] = field(default_factory=tuple)
    #: The model to re-transcribe with, when a larger or multilingual one would help.
    suggested_model: str | None = None
    #: Words stretched over a pause or a false start, and the passages
    #: (start, end) to re-transcribe with `transcribe --refine`.
    suspects: tuple[SuspectWord, ...] = ()
    refine_spans: tuple[tuple[float, float], ...] = ()

    @property
    def ok(self) -> bool:
        return not self.warnings

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "words": self.words,
            "junk_ratio": round(self.junk_ratio, 3),
            "low_confidence_ratio": (
                None if self.low_confidence_ratio is None else round(self.low_confidence_ratio, 3)
            ),
            "loops_at": [round(at, 2) for at in self.loops],
            "model": self.model,
            "language": self.language,
            "language_confidence": self.language_confidence,
            "warnings": list(self.warnings),
            "suggested_model": self.suggested_model,
            "suspect_words": [word.to_dict() for word in self.suspects],
            "refine": [f"{start:.2f}-{end:.2f}" for start, end in self.refine_spans],
        }


def is_junk(text: str) -> bool:
    """A token that carries no speech: a note, a replacement char, an annotation."""
    stripped = text.strip()
    if not stripped:
        return True
    if any(char in stripped for char in _JUNK_CHARS):
        return True
    if _ANNOTATION.match(stripped):
        return True
    return not _HAS_WORD_CHAR.search(stripped)


def find_loops(words: list[TranscriptToken]) -> list[float]:
    """Where the same short phrase repeats back to back often enough to be a loop."""
    texts = [_normal(w.text) for w in words]
    loops: list[float] = []
    index = 0
    while index < len(texts):
        found = 0
        for size in range(1, LOOP_MAX_PHRASE + 1):
            phrase = texts[index : index + size]
            if len(phrase) < size or not any(phrase):
                break
            repeats = 1
            while texts[index + repeats * size : index + (repeats + 1) * size] == phrase:
                repeats += 1
            if repeats >= LOOP_MIN_REPEATS:
                found = size * repeats
                break
        if found:
            loops.append(words[index].start)
            index += found
        else:
            index += 1
    return loops


def suspect_words(
    transcript: Transcript, quiet: list[tuple[float, float]] | None = None
) -> list[SuspectWord]:
    """Words too long to be one word, or with the sound stopping inside them.

    Whisper folds a false start and the pause after it into the next word
    ("zawsze" over 51.4-55.3 s), or slides a run of words by seconds. Both
    leave words that last too long or hold silence; ``quiet`` is the
    recording's measured quiet stretches.
    """
    found: list[SuspectWord] = []
    for word in transcript.words:
        reasons = []
        if word.duration > LONG_WORD:
            reasons.append(f"lasts {word.duration:.1f}s")
        silent = sum(
            max(0.0, min(end, word.end) - max(start, word.start)) for start, end in quiet or []
        )
        if silent >= INNER_SILENCE:
            reasons.append(f"holds {silent:.1f}s of silence")
        if reasons:
            found.append(SuspectWord(word.text, word.start, word.end, " and ".join(reasons)))
    return found


def refine_spans(suspects: list[SuspectWord], duration: float) -> list[tuple[float, float]]:
    """Passages around suspect words, merged where they touch."""
    spans: list[tuple[float, float]] = []
    for word in sorted(suspects, key=lambda w: w.start):
        start = max(0.0, word.start - REFINE_CONTEXT)
        end = min(duration or word.end + REFINE_CONTEXT, word.end + REFINE_CONTEXT)
        if spans and start <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], end))
        else:
            spans.append((start, end))
    return [(round(s, 2), round(e, 2)) for s, e in spans]


def assess_transcript(
    transcript: Transcript,
    *,
    requested_language: str | None = None,
    quiet: list[tuple[float, float]] | None = None,
) -> TranscriptQuality:
    words = transcript.words
    model = transcript.provider_model
    language = transcript.language
    warnings: list[str] = []
    needs_larger = False
    suggested: str | None = None

    junk = sum(1 for w in words if is_junk(w.text))
    junk_ratio = junk / len(words) if words else 0.0
    if words and junk_ratio > JUNK_RATIO_LIMIT:
        needs_larger = True
        warnings.append(
            f"{junk_ratio:.0%} of tokens are music notes, sound annotations or noise, "
            "which usually means music under the voice; word timings will drift"
        )

    scored = [w.confidence for w in words if w.confidence is not None]
    low_ratio = sum(1 for c in scored if c < LOW_CONFIDENCE) / len(scored) if scored else None
    if low_ratio is not None and low_ratio > LOW_CONFIDENCE_RATIO_LIMIT:
        needs_larger = True
        warnings.append(
            f"{low_ratio:.0%} of words were recognised with confidence below "
            f"{LOW_CONFIDENCE:g}; check the captions against the audio before cutting"
        )

    loops = find_loops(words)
    if loops:
        needs_larger = True
        where = ", ".join(f"{at:.1f}s" for at in loops[:3])
        warnings.append(
            f"the model repeated one phrase in a loop at {where}; that text was probably never said"
        )

    english_only = bool(model and model.endswith(".en"))
    wanted = (requested_language or "").strip().casefold()
    if english_only and wanted and wanted != "en":
        suggested = model.removesuffix(".en") if model else None
        warnings.append(
            f"{model} is an English-only model: it translates {wanted} speech into English "
            "instead of transcribing it"
        )

    if (
        not requested_language
        and transcript.language_confidence is not None
        and transcript.language_confidence < LANGUAGE_CONFIDENCE_LIMIT
    ):
        warnings.append(
            f"the language was detected as {language!r} with only "
            f"{transcript.language_confidence:.0%} confidence; pass --language"
        )

    suspects = suspect_words(transcript, quiet)
    spans = refine_spans(suspects, transcript.duration)
    if suspects:
        shown = "; ".join(f"{w.text!r} {w.start:.2f}-{w.end:.2f}s {w.reason}" for w in suspects[:3])
        more = f" (+{len(suspects) - 3} more)" if len(suspects) > 3 else ""
        first = spans[0]
        warnings.append(
            f"{len(suspects)} word(s) look stretched over a pause or a false start: "
            f"{shown}{more}; re-transcribe just those passages, e.g. "
            f"--refine {first[0]:.2f}-{first[1]:.2f} --model large-v3"
        )

    if needs_larger and suggested is None:
        suggested = _next_model(model)
        if suggested is None:
            warnings.append(
                "no larger local model is available; try a cleaner audio track "
                "(--audio-track) or the whisperx backend"
            )

    return TranscriptQuality(
        words=len(words),
        junk_ratio=junk_ratio,
        low_confidence_ratio=low_ratio,
        loops=tuple(loops),
        model=model,
        language=language,
        language_confidence=transcript.language_confidence,
        warnings=tuple(warnings),
        suggested_model=suggested,
        suspects=tuple(suspects),
        refine_spans=tuple(spans),
    )


def _next_model(model: str | None) -> str | None:
    """The next rung up the ladder, keeping an English-only suffix."""
    if not model:
        return None
    english_only = model.endswith(".en")
    base = model.removesuffix(".en")
    if base == "large-v3-turbo":
        return "large-v3"
    if base not in MODEL_LADDER:
        return None
    position = MODEL_LADDER.index(base)
    if position + 1 >= len(MODEL_LADDER):
        return None
    step = MODEL_LADDER[position + 1]
    # There is no large-v3.en; the multilingual model is the only step up.
    return f"{step}.en" if english_only and step != "large-v3" else step


def _normal(text: str) -> str:
    return re.sub(r"[^\w]", "", text.casefold())
