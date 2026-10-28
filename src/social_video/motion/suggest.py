"""Accent candidates: where an edit should move, found from what is said.

The transcript already says where the emphasis is. A number is a figure worth
showing; "ale" or "instead" turns the argument; a question invites a callout; a
short line after a pause is the punchline; "po pierwsze, po drugie" is a list
of steps; the first sentence is the hook. Cuts that jump in the source are
places a transition reads as intentional.

Each finding becomes a candidate with an id, a confidence and the one move it
proposes, sized to the project's energy level and spaced so they do not pile
up. Over a licensed music bed the moves land on its beats. Nothing reaches the
motion plan until the agent accepts it -- the same rule as cut candidates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import pairwise

from social_video.analysis.beats import snap
from social_video.captions.emphasis import normalise
from social_video.edl.timeline import Timeline
from social_video.errors import ValidationError
from social_video.motion.energy import EnergyPreset
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import (
    AccentCandidate,
    AccentCandidateSet,
    AccentKind,
    MotionElement,
    MotionElementType,
    MotionPlan,
    PunchIn,
    RangeStart,
    RangeZoom,
    Transition,
    TransitionStyle,
    WordAnchor,
)
from social_video.schemas.plan import EditPlan, PlanAction, PlanItem
from social_video.schemas.transcript import Transcript

CONTRAST = frozenset(
    {"ale", "jednak", "zamiast", "natomiast", "tymczasem", "but", "however", "instead", "yet"}
)
STEP_MARKERS = {
    ("po", "pierwsze"), ("po", "drugie"), ("po", "trzecie"), ("po", "czwarte"),
    ("first",), ("second",), ("third",), ("firstly",), ("secondly",), ("thirdly",),
}  # fmt: skip
UNITS = {"%": "%", "procent": "%", "procenta": "%", "procent.": "%", "razy": "x", "x": "x",
         "tys": " tys.", "tys.": " tys.", "tysięcy": " tys.", "mln": " mln", "milionów": " mln",
         "percent": "%", "times": "x", "k": "k"}  # fmt: skip
NUMBER = re.compile(r"^\d+(?:[.,]\d+)?%?$")


@dataclass(frozen=True)
class Word:
    text: str
    start: float  # output time
    end: float


def find_accents(
    transcript: Transcript,
    edl: EDL,
    energy: EnergyPreset,
    *,
    beats: list[float] | None = None,
    content_first: bool = False,
    transcripts: dict[str, Transcript] | None = None,
    opening: RangeStart | None = None,
    hook_punch: bool = False,
) -> AccentCandidateSet:
    """Accents found in what is said.

    Under a content-first opening no hook card is proposed: the first caption
    already carries the situation from the first frame, and a card over the
    opening is what a scrolling viewer leaves on.

    ``transcripts`` are the other recordings the EDL takes sound from, so a
    cut can be judged by whether someone is talking across it.
    """
    words = _output_words(transcript, edl)
    duration = edl.total_duration
    sentences = _sentences(words)
    found: list[AccentCandidate] = []
    if not content_first:
        found += _hook(sentences)
    found += _stats(words, duration)
    found += _steps(words, duration)
    found += _questions(sentences, duration)
    found += _punchlines(sentences, energy)
    found += _contrasts(words, energy, duration)
    heard = {transcript.source_id: transcript, **(transcripts or {})}
    found += _transitions(edl, energy, heard)
    if opening is not None:
        found.append(
            _candidate(
                AccentKind.OPENING, "medium", 0.0,
                f"start the first shot where it moves: {opening.reason}",
                range_start=opening,
            )
        )  # fmt: skip
    if hook_punch:
        found += _hook_punch(words, energy)
    kept = _space(found, energy, duration)
    if beats:
        kept = [_on_beat(candidate, beats) for candidate in kept]
    kept.sort(key=lambda c: c.at)
    for number, candidate in enumerate(kept, start=1):
        candidate.id = f"acc-{number:03d}"
    return AccentCandidateSet(
        edl=edl.name, energy=energy.name, on_beat=bool(beats), candidates=kept
    )


def accept_accents(
    plan: MotionPlan | None, found: AccentCandidateSet, ids: list[str]
) -> tuple[MotionPlan, list[str]]:
    """Add the chosen accents to the motion plan. Returns the plan and what was skipped."""
    if not ids:
        raise ValidationError("name at least one accent to accept")
    chosen = []
    for candidate_id in dict.fromkeys(ids):
        try:
            chosen.append(found.by_id(candidate_id))
        except KeyError as exc:
            raise ValidationError(str(exc.args[0])) from exc
    current = plan or MotionPlan(
        rationale="Accents accepted from `motion suggest`, each with the reason it was found."
    )
    elements, punches, transitions = (
        list(current.elements),
        list(current.punch_ins),
        list(current.transitions),
    )
    skipped: list[str] = []
    for candidate in chosen:
        if candidate.element is not None:
            if any(e.model_dump() == candidate.element.model_dump() for e in elements):
                continue
            elements.append(candidate.element)
        elif candidate.punch_in is not None:
            new = candidate.punch_in
            if any(new.start < p.end and p.start < new.end for p in punches):
                skipped.append(f"{candidate.id}: overlaps a punch-in already in the plan")
                continue
            punches.append(new)
        elif candidate.transition is not None:
            if any(abs(t.at - candidate.transition.at) < 0.05 for t in transitions):
                continue
            transitions.append(candidate.transition)
        elif candidate.range_zoom is not None:
            # A jump replaces any transition on its cut.
            transitions = [t for t in transitions if abs(t.at - candidate.at) >= 0.05]
    updated = current.model_copy(
        update={
            "elements": sorted(elements, key=lambda e: e.start),
            "punch_ins": sorted(punches, key=lambda p: p.start),
            "transitions": sorted(transitions, key=lambda t: t.at),
        }
    )
    return MotionPlan.model_validate(updated.model_dump()), skipped


def apply_range_zooms(
    edl: EDL, plan: EditPlan | None, candidates: list[AccentCandidate]
) -> tuple[EDL, EditPlan | None, list[str]]:
    """Put accepted framing jumps on their EDL ranges and on the plan items behind them.

    The plan item is where the zoom lasts: `compile --force` rebuilds the EDL
    from it. An item that compiled into several ranges cannot hold a zoom for
    only one of them, so that case is applied to the EDL alone and said.
    """
    ranges = [r.model_copy() for r in edl.ranges]
    items = [i.model_copy() for i in plan.items] if plan else []
    notes: list[str] = []
    for candidate in candidates:
        move = candidate.range_zoom
        if move is None:
            continue
        if move.range_index >= len(ranges):
            notes.append(f"{candidate.id}: range {move.range_index} is not in this EDL")
            continue
        rng = ranges[move.range_index]
        ranges[move.range_index] = rng.model_copy(update={"zoom": move.zoom})
        owners = [n for n, item in enumerate(items) if _owns(item, rng)]
        if len(owners) != 1:
            notes.append(f"{candidate.id}: zoom {move.zoom:g} set on EDL range {move.range_index}; "
                         "no single plan item holds it, so a recompile drops it")  # fmt: skip
            continue
        shared = [r for r in ranges if _owns(items[owners[0]], r)]
        if len(shared) > 1:
            notes.append(f"{candidate.id}: zoom {move.zoom:g} set on EDL range {move.range_index}; "
                         f"plan item {owners[0]} spans {len(shared)} ranges, split it to keep "
                         "the jump through a recompile")  # fmt: skip
            continue
        items[owners[0]] = items[owners[0]].model_copy(update={"zoom": move.zoom})
        notes.append(f"{candidate.id}: zoom {move.zoom:g} on plan item {owners[0]} and EDL range "
                     f"{move.range_index}")  # fmt: skip
    updated = EDL.model_validate(edl.model_copy(update={"ranges": ranges}).model_dump())
    new_plan = (
        EditPlan.model_validate(plan.model_copy(update={"items": items}).model_dump())
        if plan
        else None
    )
    return updated, new_plan, notes


def apply_range_starts(
    edl: EDL, plan: EditPlan | None, candidates: list[AccentCandidate]
) -> tuple[EDL, EditPlan | None, list[str]]:
    """Start the ranges at their accepted in-points, in the EDL and in the plan."""
    ranges = [r.model_copy() for r in edl.ranges]
    items = [i.model_copy() for i in plan.items] if plan else []
    notes: list[str] = []
    for candidate in candidates:
        move = candidate.range_start
        if move is None or move.range_index >= len(ranges):
            continue
        rng = ranges[move.range_index]
        owners = [n for n, item in enumerate(items) if _owns(item, rng)]
        delta = move.video_start - rng.effective_video_start
        separate = rng.audio_source is not None and rng.audio_source != rng.source
        update = {"start": move.video_start}
        if separate:
            update["end"] = round(rng.end + delta, 4)
        ranges[move.range_index] = rng.model_copy(update=update)
        for owner in owners:
            items[owner] = items[owner].model_copy(update={"start": move.video_start})
        where = f"plan item {owners[0]} and " if len(owners) == 1 else ""
        notes.append(f"{candidate.id}: {where}EDL range {move.range_index} start at "
                     f"{move.video_start:.2f}s ({delta:+.2f}s)")  # fmt: skip
    updated = EDL.model_validate(edl.model_copy(update={"ranges": ranges}).model_dump())
    new_plan = (
        EditPlan.model_validate(plan.model_copy(update={"items": items}).model_dump())
        if plan
        else None
    )
    return updated, new_plan, notes


def _owns(item: PlanItem, rng: EDLRange) -> bool:
    """Whether a kept plan item is where this range came from (edges may have moved)."""
    if item.action not in (PlanAction.KEEP, PlanAction.TIGHTEN) or item.source != rng.source:
        return False
    low, high = item.sound_span
    return (
        item.sound_source == rng.effective_audio_source
        and rng.effective_audio_start >= low - 0.5
        and rng.effective_audio_end <= high + 0.5
    )


# -- finding -----------------------------------------------------------------


def _output_words(transcript: Transcript, edl: EDL) -> list[Word]:
    timeline = Timeline(edl)
    words: list[Word] = []
    for token in transcript.words:
        starts = timeline.map_to_output(transcript.source_id, token.start)
        ends = timeline.map_to_output(transcript.source_id, token.end)
        if starts and ends:
            words.append(Word(token.text, starts[0], max(ends[0], starts[0] + 0.01)))
    return sorted(words, key=lambda w: w.start)


def _sentences(words: list[Word]) -> list[list[Word]]:
    sentences: list[list[Word]] = []
    current: list[Word] = []
    for index, word in enumerate(words):
        if current and word.start - current[-1].end >= 0.6:
            sentences.append(current)
            current = []
        current.append(word)
        if word.text.rstrip().endswith((".", "!", "?", "…")) or index == len(words) - 1:
            sentences.append(current)
            current = []
    return [s for s in sentences if s]


def _text(words: list[Word]) -> str:
    return " ".join(w.text for w in words).strip()


def _candidate(kind: AccentKind, confidence: str, at: float, reason: str, quote: str = "", **move):
    return AccentCandidate(
        id="", kind=kind, confidence=confidence, at=round(at, 3), quote=quote, reason=reason, **move
    )


def _anchor(words: list[Word], index: int) -> WordAnchor:
    """The word at ``index`` as the captions will name it: its text and occurrence."""
    from social_video.motion.anchors import word_key

    key = word_key(words[index].text)
    earlier = sum(1 for word in words[:index] if word_key(word.text) == key)
    return WordAnchor(word=words[index].text.strip(",.;:!?\"'„”()"), occurrence=earlier + 1)


def _hook(sentences: list[list[Word]]) -> list[AccentCandidate]:
    if not sentences:
        return []
    first = sentences[0]
    line = _text(first).rstrip(".…")
    if len(line) > 90:
        line = line.split(",")[0][:90].rstrip()
    end = min(max(first[-1].end, 1.2), 2.2)
    return [
        _candidate(
            AccentKind.HOOK,
            "high",
            0.0,
            "the opening line, set as a designed hook card for the first seconds",
            quote=_text(first),
            element=MotionElement(
                type=MotionElementType.HOOK_CARD, start=0.0, end=end, text=line,
                reason="Opening hook: the first sentence, readable with the sound off.",
            ),
        )
    ]  # fmt: skip


def _stats(words: list[Word], duration: float) -> list[AccentCandidate]:
    found = []
    for index, word in enumerate(words):
        token = word.text.strip(",.;:!?()\"'„”")
        if not NUMBER.match(token):
            continue
        after = [normalise(w.text) for w in words[index + 1 : index + 2]]
        unit = "%" if token.endswith("%") else UNITS.get(after[0], "") if after else ""
        figure = token if token.endswith("%") else token + unit
        is_year = re.fullmatch(r"(19|20)\d\d", token) is not None and not unit
        if is_year or len(figure) > 12:
            continue
        label_words: list[Word] = []
        for follower in words[index + (2 if unit and not token.endswith("%") else 1) :][:5]:
            label_words.append(follower)
            if follower.text.rstrip().endswith((".", "!", "?")):
                break  # the label is this sentence's, never the next one's
        end = min(duration, word.start + 2.2)
        if end - word.start < 1.0:
            continue
        found.append(
            _candidate(
                AccentKind.STAT,
                "high" if unit else "medium",
                word.start,
                f"a figure, {figure}, shown as it is said",
                quote=_text(words[max(0, index - 3) : index + 6]),
                element=MotionElement(
                    type=MotionElementType.STAT, start=round(word.start, 3), end=round(end, 3),
                    text=figure, secondary_text=_text(label_words)[:60] or None,
                    reason=f"The figure {figure} lands harder seen than heard.",
                ),
            )
        )  # fmt: skip
    return found


def _steps(words: list[Word], duration: float) -> list[AccentCandidate]:
    keys = [normalise(w.text) for w in words]
    marks: list[tuple[int, int]] = []
    for index in range(len(words)):
        for marker in STEP_MARKERS:
            if tuple(keys[index : index + len(marker)]) == marker:
                marks.append((index, len(marker)))
    if len(marks) < 2:
        return []
    items = []
    anchors: list[WordAnchor] = []
    for (index, size), following in zip(marks, [*marks[1:], (len(words), 0)], strict=True):
        phrase: list[Word] = []
        for word in words[index + size : min(following[0], index + size + 4)]:
            phrase.append(word)
            if word.text.rstrip().endswith((",", ".", ";", ":", "!", "?")):
                break  # a step ends where the speaker's clause does
        text = _text(phrase).strip(",.;:!?")
        if text:
            items.append(text[:60])
            # Each step enters on the first word that names it.
            anchors.append(_anchor(words, index + size))
    if len(items) < 2:
        return []
    start = words[marks[0][0]].start
    end = min(duration, max(words[marks[-1][0]].end + 2.0, start + 2.5))
    return [
        _candidate(
            AccentKind.STEPS, "medium", start,
            f"an enumerated list of {len(items[:5])} points, shown as numbered steps",
            quote=_text(words[marks[0][0] : marks[-1][0] + 5]),
            element=MotionElement(
                type=MotionElementType.STEPS, start=round(start, 3), end=round(end, 3),
                items=items[:5], item_at_words=anchors[:5],
                reason="The speaker counts the points; the viewer sees each as it is said.",
            ),
        )
    ]  # fmt: skip


def _questions(sentences: list[list[Word]], duration: float) -> list[AccentCandidate]:
    found = []
    for sentence in sentences[1:]:
        text = _text(sentence)
        if not text.endswith("?") or len(text) > 80:
            continue
        start = sentence[0].start
        end = min(duration, max(sentence[-1].end + 0.6, start + 1.5))
        found.append(
            _candidate(
                AccentKind.QUESTION, "medium", start,
                "a question to the viewer, set as a callout while it is asked",
                quote=text,
                element=MotionElement(
                    type=MotionElementType.CALLOUT, start=round(start, 3), end=round(end, 3),
                    text=text, reason="A direct question holds attention when it is also read.",
                ),
            )
        )  # fmt: skip
    return found


def _punchlines(sentences: list[list[Word]], energy: EnergyPreset) -> list[AccentCandidate]:
    found = []
    for previous, sentence in pairwise(sentences):
        pause = sentence[0].start - previous[-1].end
        # A punchline is short and set apart; a normal sentence after a breath
        # is not one.
        if pause < 0.6 or len(sentence) > 5 or _text(sentence).endswith("?"):
            continue  # a question gets its own callout, not a push-in
        start = max(0.0, sentence[0].start - 0.1)
        end = max(sentence[-1].end + 0.3, start + 0.8)
        found.append(
            _candidate(
                AccentKind.PUNCHLINE, "high" if len(sentence) <= 3 else "medium", start,
                f"a short line after a {pause:.1f}s pause: the punchline, pushed in on",
                quote=_text(sentence),
                punch_in=PunchIn(
                    start=round(start, 3), end=round(end, 3), scale=energy.punch_in_max,
                    reason="Punchline after a pause.",
                ),
            )
        )  # fmt: skip
    return found


def _contrasts(words: list[Word], energy: EnergyPreset, duration: float) -> list[AccentCandidate]:
    found = []
    for index, word in enumerate(words):
        if normalise(word.text) not in CONTRAST:
            continue
        start = word.start
        end = min(duration, start + 1.3)
        if end - start < 0.4:
            continue
        scale = round(1 + (energy.punch_in_max - 1) * 0.7, 3)
        found.append(
            _candidate(
                AccentKind.CONTRAST, "medium", start,
                f"'{word.text}' turns the argument; a push-in marks the turn",
                quote=_text(words[max(0, index - 3) : index + 6]),
                punch_in=PunchIn(
                    start=round(start, 3), end=round(end, 3), scale=scale,
                    reason=f"The turn at '{word.text}'.",
                ),
            )
        )  # fmt: skip
    return found


#: Silence at a cut up to this long still counts as talking through it.
TALKING_GAP = 0.3
#: The framing a sharp jump goes to, inside the 1.08-1.12 band that reads as a
#: deliberate second camera without losing the face.
JUMP_ZOOM = 1.1


def talking_across(before: EDLRange, after: EDLRange, transcripts: dict[str, Transcript]) -> bool:
    """Whether speech runs up to the cut and on from it, with no real pause."""
    if before.effective_audio_source != after.effective_audio_source:
        return False
    transcript = transcripts.get(before.effective_audio_source)
    if transcript is None:
        return False
    words = transcript.words
    out_point, in_point = before.effective_audio_end, after.effective_audio_start
    ending = [w for w in words if w.start < out_point and w.end > before.effective_audio_start]
    starting = [w for w in words if w.end > in_point and w.start < after.effective_audio_end]
    if not ending or not starting:
        return False
    return out_point - ending[-1].end <= TALKING_GAP and starting[0].start - in_point <= TALKING_GAP


#: Where the hook's key word may land: after the opening, before the viewer decides.
HOOK_WINDOW = (1.0, 1.5)
HOOK_SCALE = 1.16


def _hook_punch(words: list[Word], energy: EnergyPreset) -> list[AccentCandidate]:
    """A strong push-in on the first key word 1.0-1.5 s in; never on frame 0."""
    low, high = HOOK_WINDOW
    for word in words:
        if low <= word.start <= high and len(normalise(word.text)) >= 5:
            start = round(word.start, 3)
            return [
                _candidate(
                    AccentKind.HOOK_PUNCH, "medium", start,
                    f"a hook punch on '{word.text}', the first key word after the opening",
                    quote=word.text,
                    punch_in=PunchIn(
                        start=start, end=round(start + 1.2, 3),
                        scale=min(HOOK_SCALE, energy.punch_in_max), focus_y=0.4,
                        reason=f"Hook punch on '{word.text}'.",
                    ),
                )
            ]  # fmt: skip
    return []


def _transitions(
    edl: EDL, energy: EnergyPreset, transcripts: dict[str, Transcript] | None = None
) -> list[AccentCandidate]:
    timeline = Timeline(edl)
    styles = [TransitionStyle.ZOOM, TransitionStyle.SLIDE, TransitionStyle.FLASH]
    found = []
    for index, (before, after) in enumerate(
        zip(timeline.slices, timeline.slices[1:], strict=False)
    ):
        jump = after.range.effective_video_start - before.range.visual_content_end
        different = after.range.effective_video_source != before.range.effective_video_source
        if not different and abs(jump) < 1.0:
            continue  # a tight cut inside one take reads better as a plain cut
        if not different and talking_across(before.range, after.range, transcripts or {}):
            # A zoom or blur over a mouth that is still moving reads as audio
            # out of sync. Jump the framing instead, on the cut, fully sharp.
            zoom = JUMP_ZOOM if before.range.zoom < 1.05 else 1.0
            found.append(
                _candidate(
                    AccentKind.JUMP, "high", after.output_start,
                    "a cut inside one take while the speaker keeps talking; a sharp jump "
                    f"in framing to {zoom:g} instead of a transition over the mouth",
                    range_zoom=RangeZoom(
                        range_index=index + 1, zoom=zoom,
                        reason="Sharp framing jump on a mid-speech cut in one take.",
                    ),
                )
            )  # fmt: skip
            continue
        if energy.transitions_per_minute <= 0:
            continue
        found.append(
            _candidate(
                AccentKind.TRANSITION, "medium", after.output_start,
                "a cut that jumps in the source; a transition makes the jump deliberate",
                transition=Transition(
                    at=round(after.output_start, 3), style=styles[index % len(styles)],
                    reason="The cut jumps in time or source.",
                ),
            )
        )  # fmt: skip
    return found


# -- sizing -------------------------------------------------------------------


def _space(
    found: list[AccentCandidate], energy: EnergyPreset, duration: float
) -> list[AccentCandidate]:
    """Keep the best accents, spaced out, within the energy level's budget."""
    minutes = max(duration, 1.0) / 60.0
    budget = max(1, round(energy.accents_per_minute * minutes))
    transition_budget = int(energy.transitions_per_minute * minutes + 1e-9)
    # What the viewer should see first: the hook, then content graphics, then
    # emphasis moves; within a kind, the more certain and the earlier first.
    rank = {
        AccentKind.HOOK: 0,
        AccentKind.STAT: 1,
        AccentKind.STEPS: 2,
        AccentKind.PUNCHLINE: 3,
        AccentKind.QUESTION: 4,
        AccentKind.CONTRAST: 5,
        AccentKind.TRANSITION: 6,
    }
    rank[AccentKind.JUMP] = -1
    rank[AccentKind.OPENING] = -1
    # The hook punch is the opening's one move: ahead of the content graphics.
    rank[AccentKind.HOOK_PUNCH] = 0
    order = sorted(found, key=lambda c: (rank[c.kind], c.confidence != "high", c.at))
    kept: list[AccentCandidate] = []
    transitions = 0
    for candidate in order:
        if (
            candidate.range_zoom is not None
            or candidate.range_start is not None
            or candidate.kind is AccentKind.HOOK_PUNCH
        ):
            # A correction to a cut, or the hook punch asked for by name:
            # never budgeted away.
            kept.append(candidate)
            continue
        if candidate.transition is not None:
            if transitions < transition_budget:
                kept.append(candidate)
                transitions += 1
            continue
        accents = [k for k in kept if k.transition is None]
        if len(accents) >= budget:
            continue
        if any(abs(candidate.at - k.at) < energy.min_accent_gap for k in accents):
            continue
        kept.append(candidate)
    return kept


def _on_beat(candidate: AccentCandidate, beats: list[float]) -> AccentCandidate:
    if candidate.punch_in is not None:
        start = snap(candidate.punch_in.start, beats)
        shift = start - candidate.punch_in.start
        moved = candidate.punch_in.model_copy(
            update={"start": round(start, 3), "end": round(candidate.punch_in.end + shift, 3)}
        )
        return candidate.model_copy(update={"punch_in": moved, "at": round(start, 3)})
    if (
        candidate.transition is not None
        or candidate.range_zoom is not None
        or candidate.range_start is not None
    ):
        # A cut stays where it is; only a punch-in may move to the beat.
        return candidate
    return candidate
