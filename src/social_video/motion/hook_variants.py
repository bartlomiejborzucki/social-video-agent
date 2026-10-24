"""Opening variants that change one thing, recorded so a comparison stays honest.

A set of variants changes the opening along one axis and keeps the rest of the
edit as it is. Two axes are built:

- ``text``: the opening line on screen. A line that is not word for word what
  is said opens as on-screen text (a label, or the hook card under
  ``opening_policy: free``) and the captions keep the transcript; only a line
  that *is* said may become the first caption, with its real word timings.
  The audio must not change, and a hash of it proves it did not.
- ``first_shot``: the first range of the EDL is replaced by another span of
  the footage; ranges two onwards stay identical. When no recorded span can
  open the way the variant needs, it is recorded as a pickup to record, not
  rendered.

Each variant states a hypothesis, the exact changes and what stays shared.
Short previews come first; the chosen one is rendered full length and
`deliver --hook-variants` delivers it. Two organic posts of two variants are
not an A/B test, and the record says so.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import Field

from social_video.editorial.brief import _first_sentence, _spoken
from social_video.errors import ValidationError
from social_video.schemas.base import Artifact, load_artifact
from social_video.schemas.brief import Brief
from social_video.schemas.captions import CaptionCue, CaptionTrack
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import MotionElement, MotionElementType, MotionPlan
from social_video.schemas.transcript import Transcript

#: Said with every comparison of published variants.
COMPARISON_CAVEAT = (
    "Two organic posts of two variants are not an A/B test: the date, the audience and "
    "the distribution differ, so a difference in results is not proof the opening caused it."
)
#: How long an on-screen opening line stays up when the first caption is shorter.
TEXT_MIN_SECONDS = 2.0
TEXT_MAX_SECONDS = 3.5
#: The default preview length.
PREVIEW_SECONDS = 6.0
_SENTENCE_END = (".", "!", "?", "…")


class VariantAxis(str, Enum):
    TEXT = "text"
    FIRST_SHOT = "first_shot"
    #: Planned; not built yet.
    SPOKEN_OPENING = "spoken_opening"
    PACING = "pacing"
    ENDING = "ending"


BUILT_AXES = frozenset({VariantAxis.TEXT, VariantAxis.FIRST_SHOT})


class VariantChange(Artifact):
    element: str
    before: str
    after: str


class VariantBase(Artifact):
    """The edit the variants vary, by hash."""

    edl_sha256: str
    motion_plan_sha256: str | None = None
    captions_sha256: str | None = None


class OpeningVariant(Artifact):
    name: str
    hypothesis: str = ""
    #: ``text``: the opening line.
    text: str = ""
    #: ``first_shot``: ``SOURCE:START-END`` in source seconds.
    first_shot: str | None = None
    #: How a ``text`` line reaches the screen.
    shown_as: Literal["caption", "on_screen_text", "hook_card"] | None = None
    changes: list[VariantChange] = Field(default_factory=list)
    shared: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    #: What to record when no footage can open this way; nothing is rendered.
    needs_pickup: str | None = None
    preview: str = ""
    preview_seconds: float | None = None
    full: str = ""
    #: Hash of the decoded audio of the last render of this variant.
    audio_sha256: str | None = None
    #: The variant's own EDL, motion plan and captions, when they differ from the edit's.
    edl: str | None = None
    motion_plan: str | None = None
    captions: str | None = None


class OpeningVariantSet(Artifact):
    axis: VariantAxis
    base: VariantBase | None = None
    variants: list[OpeningVariant] = Field(default_factory=list)
    chosen: str | None = None
    comparison_caveat: str = COMPARISON_CAVEAT

    def find(self, name: str) -> OpeningVariant | None:
        return next((v for v in self.variants if v.name == name), None)


def load_variant_set(path: Path) -> OpeningVariantSet | None:
    """The recorded set; a 2.6 record of opening lines reads as a ``text`` set."""
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if "axis" in data:
        return load_artifact(OpeningVariantSet, path)
    variants = []
    for old in data.get("variants", []):
        whole = old.get("seconds") is None
        variants.append(
            OpeningVariant(
                name=old["name"],
                text=old.get("text", ""),
                preview="" if whole else old.get("file", ""),
                preview_seconds=old.get("seconds"),
                full=old.get("file", "") if whole else "",
            )
        )
    return OpeningVariantSet(axis=VariantAxis.TEXT, variants=variants)


@dataclass(frozen=True)
class Proposal:
    name: str
    text: str = ""
    first_shot: str | None = None
    pickup: str | None = None


def variant_names(count: int) -> list[str]:
    return [chr(ord("a") + i) if i < 26 else f"v{i + 1}" for i in range(count)]


def variants_from_brief(brief: Brief) -> list[str]:
    """Two opening lines from the brief: its first on-screen text and first spoken sentence."""
    if not brief.rows:
        return []
    first = brief.rows[0]
    found: list[str] = []
    if first.on_screen:
        found.append(first.on_screen[0].strip())
    sentence = _first_sentence(_spoken(first.said)) if first.said else ""
    if sentence:
        found.append(sentence)
    unique: list[str] = []
    for text in found:
        if text and text.casefold() not in {u.casefold() for u in unique}:
            unique.append(text)
    return unique[:2]


def _norm(text: str) -> list[str]:
    return [w for w in (re.sub(r"[^\w]", "", t).casefold() for t in text.split()) if w]


def verbatim_first_caption(track: CaptionTrack, text: str) -> CaptionTrack | None:
    """The track with cue 1 cut down to ``text`` when cue 1 says it word for word.

    The cue keeps its start, so the first caption still opens the video, and
    the kept words keep their own timings. None when ``text`` is not a run of
    cue 1's words: then it is not what is said and must not be a caption.
    """
    if not track.cues:
        return None
    first = track.cues[0]
    wanted = _norm(text)
    if not wanted:
        return None
    if _norm(first.text) == wanted:
        return track
    words = first.words
    if not words:
        return None
    heard = [_norm(w.text) for w in words]
    flat = [(i, token) for i, tokens in enumerate(heard) for token in tokens]
    for offset in range(len(flat) - len(wanted) + 1):
        if [token for _, token in flat[offset : offset + len(wanted)]] == wanted:
            kept = words[flat[offset][0] : flat[offset + len(wanted) - 1][0] + 1]
            cue = CaptionCue(
                index=first.index, start=first.start, end=first.end,
                text=" ".join(w.text for w in kept), speaker=first.speaker, words=kept,
            )  # fmt: skip
            return track.model_copy(update={"cues": [cue, *track.cues[1:]]})
    return None


def with_opening_text(plan: MotionPlan, text: str, *, end: float) -> MotionPlan:
    """The plan with ``text`` as a label over the opening, replacing an earlier one."""
    elements = [
        e
        for e in plan.elements
        if not (e.type is MotionElementType.LABEL and e.reason.startswith("Opening variant"))
    ]
    elements.insert(
        0,
        MotionElement(
            type=MotionElementType.LABEL, start=0.0, end=round(end, 3), text=text,
            reason="Opening variant: the line is on screen only, not said.",
        ),
    )  # fmt: skip
    return MotionPlan.model_validate(plan.model_copy(update={"elements": elements}).model_dump())


def opening_text_end(track: CaptionTrack | None) -> float:
    first_end = track.cues[0].end if track is not None and track.cues else TEXT_MIN_SECONDS
    return min(TEXT_MAX_SECONDS, max(TEXT_MIN_SECONDS, first_end))


def parse_shot(spec: str) -> tuple[str, float, float]:
    """``SOURCE:START-END`` as source id and seconds."""
    match = re.fullmatch(r"(.+):(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)", spec.strip())
    if not match:
        raise ValidationError(f"--first-shot {spec!r}: expected SOURCE:START-END in seconds")
    source, start, end = match.group(1), float(match.group(2)), float(match.group(3))
    if end <= start:
        raise ValidationError(f"--first-shot {spec!r}: the end must come after the start")
    return source, start, end


def first_shot_edl(
    edl: EDL, source: str, start: float, end: float, transcript: Transcript | None, name: str
) -> tuple[EDL, list[str]]:
    """``edl`` opening on ``source`` [start, end] instead of its first range."""
    from social_video.editorial.boundaries import snap_range, text_in

    if not edl.ranges:
        raise ValidationError("the EDL has no ranges to vary")
    warnings: list[str] = []
    quote = ""
    if transcript is not None and transcript.words:
        snapped = snap_range(transcript, start, end, source_duration=transcript.duration or None)
        start, end = round(snapped.start, 3), round(snapped.end, 3)
        quote = text_in(transcript, start, end)
        before = [w for w in transcript.words if w.end <= start + 1e-6]
        mid_sentence = (
            before
            and not before[-1].text.rstrip("\"')]}”").endswith(_SENTENCE_END)
            and start - before[-1].end < 0.6
        )
        if mid_sentence:
            warnings.append(
                f"the new first shot starts mid-sentence (after “{before[-1].text}”): "
                "check the meaning still holds"
            )
    else:
        warnings.append("no transcript for this source: the words of the new opening are unchecked")
    old = edl.ranges[0]
    if source == old.source:
        new = old.model_copy(
            update={"start": start, "end": end, "quote": quote, "reason": "opening variant"}
        )
    else:
        new = EDLRange(
            source=source, start=start, end=end, quote=quote, beat=old.beat,
            reason="opening variant",
        )  # fmt: skip
        warnings.append(
            "the new first shot comes from another source: framing is the default; "
            "check it in the preview"
        )
    for number, rng in enumerate(edl.ranges[1:], start=2):
        if rng.source == source and rng.start < end and start < rng.end:
            warnings.append(f"the new first shot repeats footage used in range {number}")
    variant = edl.model_copy(
        update={"ranges": [new, *edl.ranges[1:]], "name": f"{edl.name}-{name}"}
    )
    return EDL.model_validate(variant.model_dump()), warnings


def shift_plan(plan: MotionPlan, *, old_first: float, new_first: float) -> MotionPlan:
    """The plan with everything after the first range moved by the change in its length.

    What sat inside the old first range is clamped to the new one.
    """
    delta = new_first - old_first

    def move(item, end_field: str = "end"):
        data = item.model_dump()
        start = data["start"]
        if start >= old_first - 1e-6:
            data["start"] = round(start + delta, 4)
            data[end_field] = round(data[end_field] + delta, 4)
        else:
            data[end_field] = round(min(data[end_field], new_first), 4)
            if data[end_field] - start < 0.1:
                return None
        return type(item).model_validate(data)

    elements = [m for m in (move(e) for e in plan.elements) if m is not None]
    punch_ins = [m for m in (move(p) for p in plan.punch_ins) if m is not None]
    shakes = [m for m in (move(s) for s in plan.shakes) if m is not None]
    transitions = []
    for t in plan.transitions:
        at = t.at + delta if t.at >= old_first - 1e-6 else t.at
        transitions.append(t.model_copy(update={"at": round(at, 4)}))
    shifted = plan.model_copy(
        update={
            "elements": elements,
            "punch_ins": punch_ins,
            "shakes": shakes,
            "transitions": transitions,
        }
    )
    return MotionPlan.model_validate(shifted.model_dump())


def audio_sha256(video: Path) -> str | None:
    """Hash of the decoded first audio stream; None when there is none."""
    from social_video.ffmpeg.run import find_binary

    done = subprocess.run(
        [find_binary("ffmpeg"), "-v", "error", "-nostdin", "-i", str(video), "-map", "0:a:0",
         "-f", "s16le", "-ac", "2", "-ar", "48000", "-"],
        check=False, capture_output=True, timeout=600,
    )  # fmt: skip
    if done.returncode != 0 or not done.stdout:
        return None
    return hashlib.sha256(done.stdout).hexdigest()


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
