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


#: The longest pause a held caption bridges; a longer one is a new beat.
HOLD_MAX_GAP_S = 2.0


def build_caption_track(
    transcript: Transcript | list[Transcript],
    timeline: Timeline,
    *,
    style: CaptionStyle | None = None,
    opening_text: str | None = None,
) -> CaptionTrack:
    """Build caption cues, timed against the output rather than the source.

    Words removed by the edit are dropped, and a word straddling a cut is kept
    only for the part that survives. This is what stops captions drifting out of
    sync as cuts accumulate.

    With ``first_cue_full_sentence`` the first cue starts at 0.0 s and holds the
    whole first sentence, up to ``first_cue_max_words``: muted autoplay shows
    the situation from the first frame. ``opening_text`` is a line nobody says
    in the recording -- a child's line from the brief, which must never be
    voiced -- shown on its own from 0.0 s until the speech begins.

    Several transcripts -- one per recording an edit cuts between -- make one
    track: their words are placed on the output timeline, merged in output
    order and numbered once, so a scene from the second recording follows the
    first without a seam in the numbering. With ``hold_through_pauses`` a cue
    stays up until the next one within the same range.
    """
    cfg = style or CaptionStyle()
    transcripts = transcript if isinstance(transcript, list) else [transcript]
    if not transcripts:
        raise ValueError("captions need at least one transcript")
    full_first = cfg.first_cue_full_sentence and not opening_text
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

    placed = []
    for source in transcripts:
        for token in source.tokens:
            if token.type is not TokenType.WORD:
                continue
            pieces = timeline.map_interval(source.source_id, token.start, token.end)
            if pieces:
                # A word cut out of the edit entirely has nothing to caption.
                placed.append((pieces[0], token))
    placed.sort(key=lambda p: p[0][0])

    for (out_start, out_end), token in placed:
        # The opening cue carries the first sentence whole, past the cue limits.
        opening = full_first and not cues

        # A cut between two words always breaks the cue: words either side of a
        # splice did not belong to the same breath.
        # A splice, or a pause long enough to be a new thought, ends the cue.
        gap = out_start - current[-1].end if current else 0.0
        if current and (out_start < current[-1].end - 1e-6 or gap > (1.0 if opening else 0.35)):
            flush()
            opening = full_first and not cues
        if token.speaker != current_speaker and current:
            flush()
            opening = full_first and not cues
        if not current:
            current_speaker = token.speaker

        prospective = " ".join([*(w.text for w in current), token.text])
        over_limit = (
            len(current) >= cfg.first_cue_max_words
            if opening
            else len(current) >= cfg.max_words_per_cue or len(prospective) > cfg.max_chars_per_cue
        )
        if current and over_limit:
            flush()
            current_speaker = token.speaker
            opening = full_first and not cues

        current.append(CaptionWord(text=token.text, start=out_start, end=out_end))

        # A sentence always ends the cue. A clause only ends it once the cue is
        # already substantial, so short asides do not become their own caption.
        stripped = token.text.rstrip("\"')]}")
        last = stripped[-1] if stripped else ""
        ends_sentence = last in SENTENCE_END
        ends_clause = (
            not opening
            and last in CLAUSE_END
            and len(current) >= max(2, cfg.max_words_per_cue // 2)
        )
        if ends_sentence or ends_clause:
            flush()

    flush()
    if full_first and cues:
        cues[0].start = 0.0
    if opening_text and opening_text.strip():
        cues = _with_opening_line(cues, apply_case(" ".join(opening_text.split()), cfg.case), cfg)
    cues = _deoverlap(cues)
    if cfg.hold_through_pauses:
        cues = hold_through_pauses(cues, timeline)
    return CaptionTrack(language=transcripts[0].language, cues=cues)


def hold_through_pauses(cues: list[CaptionCue], timeline: Timeline) -> list[CaptionCue]:
    """Keep each cue up until the next, inside one range and a short pause.

    A scene frame with nothing in it reads as a mistake; a caption that stays
    through a breath does not. A cut to another range, or a pause longer than
    ``HOLD_MAX_GAP_S``, still clears the screen: that is a new beat.
    """

    def slice_of(moment: float) -> int | None:
        for sl in timeline.slices:
            if sl.output_start - 1e-6 <= moment < sl.output_end:
                return sl.index
        return None

    held = [cue.model_copy() for cue in cues]
    for earlier, later in pairwise(held):
        gap = later.start - earlier.end
        if 0 < gap <= HOLD_MAX_GAP_S and slice_of(earlier.start) == slice_of(later.start):
            earlier.end = round(later.start - 0.01, 3)
    return held


def _with_opening_line(cues: list[CaptionCue], text: str, cfg: CaptionStyle) -> list[CaptionCue]:
    """Show an unspoken opening line from 0.0 s until the speech begins.

    When the speech starts too soon for the line to be read, the line is left
    out and the spoken first cue starts at 0.0 s instead; opening QA reports
    which text the viewer actually saw first.
    """
    from social_video.captions.translate import estimated_words

    speech = cues[0].start if cues else cfg.min_cue_duration * 3
    if speech < cfg.min_cue_duration:
        if cues:
            cues[0].start = 0.0
        return cues
    end = round(speech - 0.01, 3)
    line = CaptionCue(index=1, start=0.0, end=end, text=text, words=estimated_words(text, 0.0, end))
    shifted = [cue.model_copy(update={"index": cue.index + 1}) for cue in cues]
    return [line, *shifted]


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
