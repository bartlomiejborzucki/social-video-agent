"""Graphics placed by the words themselves.

A reaction answers a word ("Zgodziłeś!"), and a list's point enters when it is
said ("kąpiel", "bajka"), so both are anchored to the word: `at_word` (or one
entry of `item_at_words`) names it and `occurrence` which time it is said,
and the time is taken from the caption track, which is on the output
timeline. Moving a cut then moves the graphic with the word instead of
leaving it behind.

A word the captions do not hold is an error: a graphic for a word nobody says
would land on nothing.
"""

from __future__ import annotations

from itertools import pairwise

from social_video.schemas.captions import CaptionTrack
from social_video.schemas.motion import ITEM_ANCHORED, MotionElement, MotionPlan

#: After the last point of a list enters, it stays at least this long.
ITEM_HOLD_S = 1.5


def word_key(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def word_times(captions: CaptionTrack) -> list[tuple[str, float, float]]:
    """Every captioned word with its output time, in order."""
    found = []
    for cue in captions.cues:
        for word in cue.words:
            found.append((word_key(word.text), word.start, word.end))
    return sorted(found, key=lambda item: item[1])


def needs_anchoring(plan: MotionPlan) -> bool:
    return any(e.at_word or e.item_at_words for e in plan.elements) or any(
        s.at_word for s in plan.shakes
    )


def anchor_to_words(
    plan: MotionPlan, captions: CaptionTrack | None
) -> tuple[MotionPlan, list[str]]:
    """Move every graphic anchored to a word onto that word. Says what moved."""
    if not needs_anchoring(plan):
        return plan, []
    if captions is None:
        raise ValueError("graphics anchored to a word (at_word) need the caption track")
    words = word_times(captions)
    notes: list[str] = []

    def find(word: str, occurrence: int) -> float:
        key = word_key(word)
        hits = [start for text, start, _end in words if text == key]
        if len(hits) < occurrence:
            raise ValueError(
                f"at_word {word!r} is said {len(hits)} time(s) in the captions; "
                f"occurrence {occurrence} does not exist"
            )
        return round(hits[occurrence - 1], 3)

    elements = []
    for element in plan.elements:
        if element.item_at_words and element.type in ITEM_ANCHORED:
            element = _anchor_items(element, find, notes)
        elif element.at_word:
            start = find(element.at_word, element.occurrence)
            length = element.end - element.start
            if abs(start - element.start) > 1e-3:
                notes.append(f"{element.type.value} on {element.at_word!r} placed at {start:.2f}s")
            element = element.model_copy(update={"start": start, "end": round(start + length, 3)})
        elements.append(element)
    moved_shakes = []
    for shake in plan.shakes:
        if shake.at_word:
            start = find(shake.at_word, shake.occurrence)
            length = shake.end - shake.start
            if abs(start - shake.start) > 1e-3:
                notes.append(f"shake on {shake.at_word!r} placed at {start:.2f}s")
            shake = shake.model_copy(update={"start": start, "end": round(start + length, 3)})
        moved_shakes.append(shake)
    updated = plan.model_copy(
        update={"elements": sorted(elements, key=lambda e: e.start), "shakes": moved_shakes}
    )
    return MotionPlan.model_validate(updated.model_dump()), notes


def _anchor_items(element: MotionElement, find, notes: list[str]) -> MotionElement:
    """Each point enters on its word; the card follows the words it shows.

    The first time, the card keeps its start unless its first word comes
    earlier; afterwards it moves with its first word, so a recompile that
    shifts the speech shifts the whole card. It stays until the last point
    has been on screen for `ITEM_HOLD_S`.
    """
    assert element.item_at_words is not None
    times = [find(a.word, a.occurrence) for a in element.item_at_words]
    if any(b < a for a, b in pairwise(times)):
        pairs = zip(element.item_at_words, times, strict=True)
        said = ", ".join(f"{a.word!r} at {t:.2f}s" for a, t in pairs)
        raise ValueError(f"a {element.type.value}'s items are said out of order: {said}")
    start, end = element.start, element.end
    if element.item_times:
        shift = times[0] - element.item_times[0]
        start, end = start + shift, end + shift
    start = max(0.0, min(start, times[0]))
    end = max(end, times[-1] + ITEM_HOLD_S)
    kind = element.type.value
    for number, (anchor, at) in enumerate(zip(element.item_at_words, times, strict=True), 1):
        before = element.item_times[number - 1] if element.item_times else None
        if before is None or abs(before - at) > 1e-3:
            notes.append(f"{kind} item {number} on {anchor.word!r} placed at {at:.2f}s")
    if abs(start - element.start) > 1e-3 or abs(end - element.end) > 1e-3:
        notes.append(f"{kind} now on screen {start:.2f}-{end:.2f}s to show its items as said")
    return element.model_copy(
        update={"start": round(start, 3), "end": round(end, 3), "item_times": times}
    )
