"""Correcting the words of a caption track, without touching its timing.

Recognition mishears ("sam." for "już."), and a brief fixes wording. Both are
text changes: the cue keeps its time, and so do the words around the change.
The words list is corrected together with the cue text, because the active-word
highlight and keyword emphasis draw from the words -- a fix to the text alone
would show the old word whenever it is spoken.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from social_video.captions.chunk import apply_case
from social_video.errors import ValidationError
from social_video.schemas.brand import CaptionCase
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord

#: How far from a cue ``--at`` may land and still mean that cue, in seconds.
NEAR_S = 1.0


@dataclass(frozen=True)
class CaptionFix:
    cue: int
    before: str
    after: str


def _bare(text: str) -> str:
    return re.sub(r"[^\w]", "", text.casefold())


def fix_words(
    track: CaptionTrack,
    *,
    at: float,
    old: str,
    new: str,
    case: CaptionCase = CaptionCase.AS_SPOKEN,
) -> tuple[CaptionTrack, CaptionFix]:
    """Replace ``old`` with ``new`` in the cue on screen at ``at``.

    ``old`` may be several words; they are matched in order, exactly first,
    then ignoring case and punctuation. The replacement takes over their time
    span, split evenly when the word count changes.
    """
    wanted = old.split()
    if not wanted:
        raise ValidationError("--from needs the word(s) to replace")
    replacement = new.split()
    cue = _cue_at(track, at)
    words = list(cue.words)
    if words:
        span = _find(words, wanted)
        if span is None:
            shown = " ".join(w.text for w in words)
            raise ValidationError(f"cue {cue.index} ({shown!r}) has no {old!r}")
        first, last = span
        start, end = words[first].start, words[last].end
        step = (end - start) / max(1, len(replacement))
        fixed = [
            CaptionWord(
                text=text, start=round(start + n * step, 3), end=round(start + (n + 1) * step, 3)
            )
            for n, text in enumerate(replacement)
        ]
        words = words[:first] + fixed + words[last + 1 :]
        text = apply_case(" ".join(w.text for w in words), case)
    else:
        if old not in cue.text and apply_case(old, case) not in cue.text:
            raise ValidationError(f"cue {cue.index} ({cue.text!r}) has no {old!r}")
        source = old if old in cue.text else apply_case(old, case)
        text = cue.text.replace(source, apply_case(new, case), 1)
    if not text.strip():
        raise ValidationError("the fix would leave the cue empty; remove the cue instead")
    updated = cue.model_copy(update={"text": text, "words": words})
    cues = [updated if c.index == cue.index else c for c in track.cues]
    return (
        track.model_copy(update={"cues": cues, "corrected": True}),
        CaptionFix(cue=cue.index, before=cue.text, after=text),
    )


def _cue_at(track: CaptionTrack, at: float) -> CaptionCue:
    if not track.cues:
        raise ValidationError("the caption track has no cues")
    inside = [c for c in track.cues if c.start <= at <= c.end]
    if inside:
        return inside[0]
    nearest = min(track.cues, key=lambda c: min(abs(c.start - at), abs(c.end - at)))
    distance = min(abs(nearest.start - at), abs(nearest.end - at))
    if distance > NEAR_S:
        raise ValidationError(
            f"no caption on screen at {at:.2f}s; the nearest, cue {nearest.index}, runs "
            f"{nearest.start:.2f}-{nearest.end:.2f}s"
        )
    return nearest


def _find(words: list[CaptionWord], wanted: list[str]) -> tuple[int, int] | None:
    for compare in (lambda a, b: a == b, lambda a, b: _bare(a) == _bare(b)):
        for first in range(len(words) - len(wanted) + 1):
            window = words[first : first + len(wanted)]
            if all(compare(w.text, t) for w, t in zip(window, wanted, strict=True)):
                return first, first + len(wanted) - 1
    return None
