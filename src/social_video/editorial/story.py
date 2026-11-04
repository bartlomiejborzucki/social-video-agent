"""Text stories: a sentence per shot, read rather than heard.

Some reels have no speech at all: second-person narration in short sentences
("You are at the bus stop." / "It is 7:30.") over a quick run of shots, one
sentence per shot, a cut every second or so, and a question at the end. The
sentences come from the brief, written by a person; the shots from the
project's recordings, each named once. Nothing is transcribed, because there
is nothing to hear -- a speech model run on a silent shot invents words -- and
the shots' own sound is muted under a music bed the project chooses.

A story is written one line per shot::

    "You are at the bus stop." -> stop.mp4
    "It is 7:30." -> clock.mp4 @ 2.0
    "And the bus is late again?" -> road.mp4 @ 0.5 1.4s

``@ 2.0`` starts the shot 2.0 s into its clip; a trailing ``1.4s`` holds it
1.4 s instead of the story's ``cut_every``. ``→`` works as well as ``->``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from social_video.errors import ValidationError
from social_video.schemas.brand import CaptionPosition, CaptionStyle
from social_video.schemas.captions import CaptionCue, CaptionTrack
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.plan import EditPlan, PlanAction, PlanItem
from social_video.schemas.source import SourceManifest

#: Shots are held this long by default; a story is read at a cut a second.
CUT_EVERY = (1.0, 1.5)
DEFAULT_CUT_EVERY = 1.25
#: A sentence of a text story fits a glance.
MAX_SENTENCE = 120

_LINE = re.compile(
    r"""^\s*[„"“']?(?P<text>.+?)[”"“']?\s*(?:->|→)\s*(?P<clip>\S+)"""
    r"""(?:\s*@\s*(?P<at>\d+(?:[.,]\d+)?))?(?:\s+(?P<hold>\d+(?:[.,]\d+)?)\s*s)?\s*$"""
)


@dataclass(frozen=True)
class StoryLine:
    text: str
    clip: str
    at: float = 0.0
    hold: float | None = None


def parse_story(text: str) -> list[StoryLine]:
    """Every story line in ``text``; other lines (headings, notes) are skipped."""
    lines = []
    for raw in text.splitlines():
        match = _LINE.match(raw)
        if match is None:
            continue
        sentence = " ".join(match["text"].split())
        if not sentence or len(sentence) > MAX_SENTENCE:
            raise ValidationError(
                f"a story sentence is 1-{MAX_SENTENCE} characters; got {len(sentence)}: {raw!r}"
            )
        lines.append(
            StoryLine(
                text=sentence,
                clip=match["clip"],
                at=float((match["at"] or "0").replace(",", ".")),
                hold=float(match["hold"].replace(",", ".")) if match["hold"] else None,
            )
        )
    if not lines:
        raise ValidationError(
            'no story lines found; write one per shot: "Sentence." -> clip.mp4 [@ 2.0] [1.4s]'
        )
    return lines


def story_plan(
    lines: list[StoryLine],
    sources: SourceManifest,
    *,
    cut_every: float = DEFAULT_CUT_EVERY,
    goal: str = "A text story: one sentence per shot.",
) -> EditPlan:
    """An edit plan holding each shot for its sentence, in the story's order."""
    if not CUT_EVERY[0] <= cut_every <= CUT_EVERY[1]:
        raise ValidationError(
            f"cut_every is {CUT_EVERY[0]:g}-{CUT_EVERY[1]:g} s; a text story is read at a cut "
            "a second or so"
        )
    items = []
    for order, line in enumerate(lines):
        entry = _source(line.clip, sources)
        hold = line.hold or cut_every
        end = line.at + hold
        if end > entry.duration + 1e-3:
            raise ValidationError(
                f"{line.clip}: the shot {line.at:g}-{end:g}s runs past the clip's "
                f"{entry.duration:.2f}s"
            )
        items.append(
            PlanItem(
                action=PlanAction.KEEP,
                source=entry.id,
                start=round(line.at, 3),
                end=round(end, 3),
                order=order,
                story_text=line.text,
                reason=f"story sentence {order + 1}",
            )
        )
    return EditPlan(goal=goal, items=items, mode="text_story", strategy="text story")


def _source(clip: str, sources: SourceManifest):
    for entry in sources.sources:
        if clip in (entry.id, Path(entry.path).name, Path(entry.path).stem):
            return entry
    known = ", ".join(Path(e.path).name for e in sources.sources) or "<none>"
    raise ValidationError(f"story clip {clip!r} is not a source of this edit; known: {known}")


def compile_story(plan: EditPlan, *, width: int, height: int, name: str = "main") -> EDL:
    """One muted range per shot, in order; no speech to snap to, so no snapping."""
    kept = sorted(
        enumerate(plan.kept), key=lambda p: (p[1].order if p[1].order is not None else p[0], p[0])
    )
    ranges = [
        EDLRange(
            source=item.source,
            start=item.start,
            end=item.end,
            quote=item.story_text or "",
            reason=item.reason or "story shot",
            beat=item.beat,
            zoom=item.zoom,
            speed=item.speed,
            grade=item.grade,
            muted=True,
        )
        for _n, item in kept
    ]
    if not ranges:
        raise ValidationError("the story keeps no shots")
    return EDL(name=name, ranges=ranges, output_width=width, output_height=height)


def story_track(edl: EDL, style: CaptionStyle, *, language: str | None = None) -> CaptionTrack:
    """Each shot's sentence on screen for exactly that shot, from its first frame."""
    from social_video.captions.chunk import apply_case
    from social_video.captions.translate import estimated_words
    from social_video.edl.timeline import Timeline

    cues = []
    for number, piece in enumerate(Timeline(edl).slices, start=1):
        text = apply_case(edl.ranges[piece.index].quote, style.case)
        start, end = round(piece.output_start, 3), round(piece.output_end, 3)
        cues.append(
            CaptionCue(
                index=number, start=start, end=end, text=text,
                words=estimated_words(text, start, end),
            )
        )  # fmt: skip
    return CaptionTrack(language=language, cues=cues, word_timing="estimated", origin="story")


def story_style(captions: CaptionStyle, *, font_size_pct: float, position: str) -> CaptionStyle:
    """The captions' look for a story: larger, centred, the whole sentence at once."""
    return captions.model_copy(
        update={
            "font_size_pct": font_size_pct,
            "position": CaptionPosition(position),
            "highlight_active_word": False,
            "upcoming_word_opacity": 1.0,
            "animation": "none",
            "emphasis_mark": "none",
            "max_lines": 3,
            "max_words_per_cue": 20,
            "max_chars_per_cue": MAX_SENTENCE,
            "first_cue_full_sentence": False,
            "hold_through_pauses": False,
            "step_numbers": False,
            "mode": "karaoke",
        }
    )


def contract_story_style(contract) -> CaptionStyle:
    """The style a text story's captions are drawn with under this contract.

    Rendering and brand QA both use it, so a story is checked against what
    it is meant to look like, not against the speech captions' settings.
    """
    return story_style(
        contract.brand.captions,
        font_size_pct=contract.story_caption.font_size_pct,
        position=contract.story_caption.position,
    )
