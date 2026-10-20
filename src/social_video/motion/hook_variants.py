"""Opening-line variants from the brief, rendered side by side for an A/B test.

Under a content-first opening the hook is the first caption, so a variant
changes that caption's words, never adds a card: the on-screen text of the
brief's first row, the first sentence of what is said, and a question made
from it. Each renders as its own file -- optionally only the first seconds,
for a quick look -- and is recorded in `analysis/hook-variants.json`, from
which `deliver --hook-variants` takes the full-length ones under their names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import Field

from social_video.editorial.brief import _first_sentence, _spoken
from social_video.schemas.base import Artifact
from social_video.schemas.brief import Brief
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord
from social_video.schemas.edl import EDL
from social_video.schemas.motion import MotionPlan


class HookVariant(Artifact):
    name: str
    text: str
    file: str = ""
    #: Rendered length in seconds; None means the whole edit.
    seconds: float | None = None


class HookVariantSet(Artifact):
    variants: list[HookVariant] = Field(default_factory=list)


@dataclass(frozen=True)
class Proposal:
    name: str
    text: str


def variants_from_brief(brief: Brief) -> list[Proposal]:
    """Up to three first lines: on-screen text, first spoken sentence, a question."""
    if not brief.rows:
        return []
    first = brief.rows[0]
    found: list[Proposal] = []
    if first.on_screen:
        found.append(Proposal("napis", first.on_screen[0].strip()))
    sentence = _first_sentence(_spoken(first.said)) if first.said else ""
    if sentence:
        found.append(Proposal("zdanie", sentence))
        clause = re.split(r"[,;:–—]", sentence.rstrip(".!?… "), maxsplit=1)[0].strip()  # noqa: RUF001
        if clause:
            found.append(Proposal("pytanie", f"Co zrobisz, gdy {clause[0].lower()}{clause[1:]}?"))
    seen: set[str] = set()
    unique = []
    for proposal in found:
        if proposal.text and proposal.text.casefold() not in seen:
            seen.add(proposal.text.casefold())
            unique.append(proposal)
    return unique[:3]


def with_first_caption(track: CaptionTrack, text: str) -> CaptionTrack:
    """The track with cue 1 saying ``text``, its words spread over the cue's time."""
    if not track.cues:
        return track
    first = track.cues[0]
    words = text.split()
    step = (first.end - first.start) / max(1, len(words))
    timed = [
        CaptionWord(
            text=word,
            start=round(first.start + index * step, 3),
            end=round(first.start + (index + 1) * step, 3),
        )
        for index, word in enumerate(words)
    ]
    cue = CaptionCue(
        index=first.index, start=first.start, end=first.end, text=text,
        speaker=first.speaker, words=timed,
    )  # fmt: skip
    return track.model_copy(update={"cues": [cue, *track.cues[1:]]})


def head_of(edl: EDL, plan: MotionPlan | None, seconds: float) -> tuple[EDL, MotionPlan | None]:
    """Only the first ``seconds`` of the edit and of its motion plan."""
    ranges = []
    left = seconds
    for rng in edl.ranges:
        if left <= 0.05:
            break
        length = rng.output_duration
        if length <= left + 1e-6:
            ranges.append(rng)
            left -= length
            continue
        update: dict = {"end": round(rng.start + left * rng.speed, 4)}
        if rng.audio_source is not None and rng.audio_start is not None:
            update["audio_end"] = round(rng.audio_start + left * rng.voice_speed, 4)
        ranges.append(rng.model_copy(update=update))
        left = 0
    head = EDL.model_validate(
        edl.model_copy(update={"ranges": ranges, "end_hold": 0.0}).model_dump()
    )
    if plan is None:
        return head, None
    total = head.total_duration

    def keep(items, end_field: str = "end"):
        out = []
        for item in items:
            start = getattr(item, "start", None)
            if start is None or start >= total - 0.05:
                continue
            end = min(getattr(item, end_field), total)
            try:
                out.append(type(item).model_validate({**item.model_dump(), end_field: end}))
            except ValueError:
                continue
        return out

    transitions = [t for t in plan.transitions if t.at + t.duration / 2 < total]
    head_plan = plan.model_copy(
        update={
            "elements": keep(plan.elements),
            "punch_ins": keep(plan.punch_ins),
            "shakes": keep(plan.shakes),
            "transitions": transitions,
        }
    )
    return head, MotionPlan.model_validate(head_plan.model_dump())
