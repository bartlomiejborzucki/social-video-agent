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

import re
from itertools import pairwise

from social_video.edl.timeline import Timeline
from social_video.schemas.captions import CaptionTrack
from social_video.schemas.edl import EDL
from social_video.schemas.motion import (
    ITEM_ANCHORED,
    MotionElement,
    MotionElementType,
    MotionPlan,
    SourceAnchor,
)

#: After the last point of a list enters, it stays at least this long.
ITEM_HOLD_S = 1.5


def word_key(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


#: A step number `step_numbers` put in front of a cue's first word ("2. Po").
_STEP_PREFIX = re.compile(r"^\d+\.\s+")


def word_times(captions: CaptionTrack) -> list[tuple[str, float, float]]:
    """Every captioned word with its output time, in order.

    A step number in front of a word is not part of it: "2. Po" is "po".
    """
    found = []
    for cue in captions.cues:
        for word in cue.words:
            text = _STEP_PREFIX.sub("", word.text) if captions.step_numbers else word.text
            found.append((word_key(text), word.start, word.end))
    return sorted(found, key=lambda item: item[1])


def needs_anchoring(plan: MotionPlan) -> bool:
    return (
        any(e.at_word or e.item_at_words or e.replace_at_word for e in plan.elements)
        or any(s.at_word for s in plan.shakes)
        or any(p.at_word for p in plan.punch_ins)
        or any(f.at_word for f in plan.effects)
    )


def place_end_teasers(plan: MotionPlan, duration: float | None) -> tuple[MotionPlan, list[str]]:
    """An end teaser covers the last ``from_end`` seconds of speech. Says what moved.

    ``duration`` is the whole edit; end cards held after the last word are
    taken off it, so the teaser stays over the speaker and the cards follow.
    """
    if duration is None or not any(
        e.type is MotionElementType.END_TEASER and e.from_end is not None for e in plan.elements
    ):
        return plan, []
    # Held end cards come after the last word; the teaser is over the speaker.
    held = sum(
        e.end - e.start for e in plan.elements if e.type is MotionElementType.END_CARD and e.hold
    )
    duration = max(duration - held, 0.0)
    notes: list[str] = []
    elements = []
    for element in plan.elements:
        # A teaser with its own start and end (no from_end) stays where it is.
        if element.type is MotionElementType.END_TEASER and element.from_end is not None:
            length = min(element.from_end, duration)
            start, end = round(max(0.0, duration - length), 3), round(duration, 3)
            if abs(start - element.start) > 1e-3 or abs(end - element.end) > 1e-3:
                notes.append(f"end_teaser placed over the last {length:g}s, {start:.2f}-{end:.2f}s")
                element = element.model_copy(update={"start": start, "end": end})
        elements.append(element)
    if not notes:
        return plan, []
    updated = plan.model_copy(update={"elements": sorted(elements, key=lambda e: e.start)})
    return MotionPlan.model_validate(updated.model_dump()), notes


def anchor_to_sources(plan: MotionPlan, edl: EDL) -> tuple[MotionPlan, list[str]]:
    """Move everything anchored to a moment of a recording onto that moment.

    The plan's own times are on the output timeline and go stale with every
    recompile; a moment named in the recording is mapped through the edit as
    it is now. A moment the edit cut out is an error that names it: the
    graphic would otherwise sit where nothing it refers to is shown.
    """
    anchored = [
        *(e for e in plan.elements if e.at_source),
        *(s for s in plan.shakes if s.at_source),
        *(p for p in plan.punch_ins if p.at_source),
        *(f for f in plan.effects if f.at_source),
    ]
    if not anchored:
        return plan, []
    timeline = Timeline(edl)
    notes: list[str] = []

    def find(anchor: SourceAnchor, what: str) -> float:
        hits = timeline.map_to_output(anchor.source, anchor.time)
        if not hits:
            raise ValueError(
                f"{what}: {anchor.time:g}s of {anchor.source!r} is not in the edit; the cut "
                "removed it, or the source id is not one the EDL uses"
            )
        return round(hits[0], 3)

    def moved(item, what: str):
        if item.at_source is None:
            return item
        start = find(item.at_source, what)
        until = getattr(item, "until_source", None)
        end = find(until, what) if until is not None else round(start + item.end - item.start, 3)
        if end <= start:
            raise ValueError(f"{what}: until_source falls before at_source in the edit")
        if abs(start - item.start) > 1e-3 or abs(end - item.end) > 1e-3:
            notes.append(
                f"{what} placed at {start:.2f}-{end:.2f}s from "
                f"{item.at_source.source} {item.at_source.time:g}s"
            )
        return item.model_copy(update={"start": start, "end": end})

    updated = plan.model_copy(
        update={
            "elements": sorted(
                (moved(e, e.type.value) for e in plan.elements), key=lambda e: e.start
            ),
            "shakes": [moved(s, "shake") for s in plan.shakes],
            "punch_ins": sorted(
                (moved(p, "punch-in") for p in plan.punch_ins), key=lambda p: p.start
            ),
            "effects": sorted(
                (moved(f, f.type.value) for f in plan.effects), key=lambda f: f.start
            ),
        }
    )
    return MotionPlan.model_validate(updated.model_dump()), notes


def anchor_to_words(
    plan: MotionPlan,
    captions: CaptionTrack | None,
    *,
    duration: float | None = None,
    edl: EDL | None = None,
) -> tuple[MotionPlan, list[str]]:
    """Move every graphic anchored to a word onto that word. Says what moved.

    A list or strike that stays on to show its last point is never held past
    ``duration``, the edit's length, when it is given. With ``edl``, what is
    anchored to a moment of a recording (`at_source`) is placed first.
    """
    sourced: list[str] = []
    if edl is not None:
        plan, sourced = anchor_to_sources(plan, edl)
    plan, placed = place_end_teasers(plan, duration)
    placed = [*sourced, *placed]
    if not needs_anchoring(plan):
        return plan, placed
    if captions is None:
        raise ValueError("graphics anchored to a word (at_word) need the caption track")
    words = word_times(captions)
    notes: list[str] = list(placed)

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
            element = _anchor_items(element, find, notes, duration)
        elif element.type is MotionElementType.STRIKE:
            element = _anchor_strike(element, find, notes, duration)
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

    def moved(items, name):
        result = []
        for item in items:
            if item.at_word:
                start = find(item.at_word, item.occurrence)
                length = item.end - item.start
                if abs(start - item.start) > 1e-3:
                    notes.append(f"{name(item)} on {item.at_word!r} placed at {start:.2f}s")
                item = item.model_copy(update={"start": start, "end": round(start + length, 3)})
            result.append(item)
        return result

    updated = plan.model_copy(
        update={
            "elements": sorted(elements, key=lambda e: e.start),
            "shakes": moved_shakes,
            "punch_ins": sorted(
                moved(plan.punch_ins, lambda _p: "punch-in"), key=lambda p: p.start
            ),
            "effects": sorted(moved(plan.effects, lambda f: f.type.value), key=lambda f: f.start),
        }
    )
    return MotionPlan.model_validate(updated.model_dump()), notes


def _anchor_items(
    element: MotionElement, find, notes: list[str], duration: float | None = None
) -> MotionElement:
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
    if duration is not None:
        end = min(end, duration)
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


#: A strike's line is read this long before it is crossed out, by default.
STRIKE_LEAD_S = 1.2
#: After its replacement enters, a strike stays at least this long.
REPLACEMENT_HOLD_S = 1.2


def _anchor_strike(
    element: MotionElement, find, notes: list[str], duration: float | None = None
) -> MotionElement:
    """The stroke lands on `at_word`, the replacement on `replace_at_word`.

    The first time, the strike keeps its start when the word falls inside it
    and otherwise opens `STRIKE_LEAD_S` before the word; afterwards it moves
    with its word. It stays until the replacement has been read.
    """
    start, end = element.start, element.end
    crossed, replaced = element.strike_at, element.replace_at
    if element.at_word:
        word = find(element.at_word, element.occurrence)
        if crossed is not None:
            shift = word - crossed
            start, end = start + shift, end + shift
            if replaced is not None and not element.replace_at_word:
                replaced += shift
        elif not start < word < end:
            length = end - start
            start = max(0.3, word - min(STRIKE_LEAD_S, length / 3))
            end = start + length
        if crossed is None or abs(crossed - word) > 1e-3:
            notes.append(f"strike on {element.at_word!r} crosses out at {word:.2f}s")
        crossed = word
    if element.replace_at_word:
        word = find(element.replace_at_word, element.replace_occurrence)
        if replaced is None or abs(replaced - word) > 1e-3:
            notes.append(f"strike replaced on {element.replace_at_word!r} at {word:.2f}s")
        replaced = word
    floor = (replaced if replaced is not None else (crossed or start) + 0.7) + REPLACEMENT_HOLD_S
    if duration is not None:
        floor = min(floor, duration)
    if end < floor:
        notes.append(f"strike now on screen until {floor:.2f}s to show its replacement")
        end = floor
    return element.model_copy(
        update={
            "start": round(start, 3),
            "end": round(end, 3),
            "strike_at": crossed,
            "replace_at": replaced,
        }
    )
