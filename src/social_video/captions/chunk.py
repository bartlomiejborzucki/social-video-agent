"""Turning a transcript into caption cues on the output timeline.

Chunking follows speech, not a fixed word count. Upstream emits exactly two
words per cue, always uppercase, with no way to change either without editing
the renderer -- which its own instructions forbid. Here every parameter comes
from the brand profile, and the default groups on natural phrase boundaries so
captions read the way the sentence is spoken.
"""

from __future__ import annotations

from itertools import pairwise

from social_video.edl.timeline import Timeline
from social_video.schemas.brand import CaptionCase, CaptionStyle
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord
from social_video.schemas.transcript import TokenType, Transcript

#: Punctuation that ends a thought, and is therefore a good place to break.
SENTENCE_END = frozenset(".!?…")
#: Punctuation that marks a natural pause.
CLAUSE_END = frozenset(",;:-–—")  # noqa: RUF001 - en/em dashes are real punctuation here


def apply_case(text: str, case: CaptionCase) -> str:
    """Apply the caption case.

    Note this is locale-independent: Python's ``upper()`` turns Turkish
    dotless-i into the wrong letter and expands German eszett. Since the default
    is to leave speech as spoken, that only bites users who opt in.
    """
    if case is CaptionCase.UPPER:
        return text.upper()
    if case is CaptionCase.LOWER:
        return text.lower()
    return text


def build_caption_track(
    transcript: Transcript,
    timeline: Timeline,
    *,
    style: CaptionStyle | None = None,
) -> CaptionTrack:
    """Build caption cues, timed against the output rather than the source.

    Words removed by the edit are dropped, and a word straddling a cut is kept
    only for the part that survives. This is what stops captions drifting out of
    sync as cuts accumulate.
    """
    cfg = style or CaptionStyle()
    cues: list[CaptionCue] = []
    index = 1

    current: list[CaptionWord] = []
    current_speaker: str | None = None

    def flush() -> None:
        nonlocal current, index, current_speaker
        if not current:
            return
        text = apply_case(" ".join(w.text for w in current).strip(), cfg.case)
        if text:
            start = current[0].start
            end = max(current[-1].end, start + cfg.min_cue_duration)
            cues.append(
                CaptionCue(
                    index=index,
                    start=start,
                    end=end,
                    text=text,
                    speaker=current_speaker,
                    words=list(current),
                )
            )
            index += 1
        current = []

    for token in transcript.tokens:
        if token.type is not TokenType.WORD:
            continue
        pieces = timeline.map_interval(transcript.source_id, token.start, token.end)
        if not pieces:
            # Cut out of the edit entirely; there is nothing to caption.
            continue
        out_start, out_end = pieces[0]

        # A cut between two words always breaks the cue: words either side of a
        # splice did not belong to the same breath.
        # A splice, or a pause long enough to be a new thought, ends the cue.
        if current and (out_start < current[-1].end - 1e-6 or out_start - current[-1].end > 0.35):
            flush()
        if token.speaker != current_speaker and current:
            flush()
        if not current:
            current_speaker = token.speaker

        prospective = " ".join([*(w.text for w in current), token.text])
        if current and (
            len(current) >= cfg.max_words_per_cue or len(prospective) > cfg.max_chars_per_cue
        ):
            flush()
            current_speaker = token.speaker

        current.append(CaptionWord(text=token.text, start=out_start, end=out_end))

        # A sentence always ends the cue. A clause only ends it once the cue is
        # already substantial, so short asides do not become their own caption.
        stripped = token.text.rstrip("\"')]}")
        last = stripped[-1] if stripped else ""
        ends_sentence = last in SENTENCE_END
        ends_clause = last in CLAUSE_END and len(current) >= max(2, cfg.max_words_per_cue // 2)
        if ends_sentence or ends_clause:
            flush()

    flush()
    return CaptionTrack(language=transcript.language, cues=_deoverlap(cues))


def _deoverlap(cues: list[CaptionCue]) -> list[CaptionCue]:
    """Trim any cue that runs into the next one.

    Overlapping cues make libass stack them, which pushes captions out of the
    safe zone and over the platform UI.
    """
    ordered = sorted(cues, key=lambda c: c.start)
    for earlier, later in pairwise(ordered):
        if earlier.end > later.start:
            earlier.end = max(later.start - 0.01, earlier.start + 0.05)
    return [c for c in ordered if c.end > c.start]
