"""Intentional motion design rendered by Remotion after the technical edit."""

from __future__ import annotations

from enum import Enum
from itertools import pairwise
from pathlib import Path

from pydantic import Field, model_validator

from social_video.schemas.base import Artifact


class MotionElementType(str, Enum):
    HOOK = "hook"
    LOWER_THIRD = "lower_third"
    CALLOUT = "callout"
    END_CARD = "end_card"
    #: A spoken line set as a pull quote; ``secondary_text`` attributes it.
    QUOTE = "quote"
    #: One figure, counted up when it is a number; ``secondary_text`` labels it.
    STAT = "stat"
    #: Two to five short points revealed one after another; uses ``items``.
    LIST = "list"
    #: A section title for a new part of the argument.
    CHAPTER = "chapter"
    #: A call to action set above the caption area.
    CTA = "cta"
    #: A thin bar showing how far through the video the viewer is. No text.
    PROGRESS = "progress"
    #: The brand logo animated in, from the brand contract. No text.
    LOGO_REVEAL = "logo_reveal"
    #: A designed opening frame: the strongest line, full width, over the
    #: picture, in the first second. It is where a scrolling viewer decides.
    HOOK_CARD = "hook_card"
    #: A bar chart from two to six `items` written "Label: number".
    CHART = "chart"
    #: A before/after comparison: exactly two `items`, "Label: text".
    COMPARE = "compare"
    #: Numbered steps of a process, two to five `items`, revealed in order.
    STEPS = "steps"


#: Types drawn without words of their own.
TEXTLESS = frozenset({MotionElementType.PROGRESS, MotionElementType.LOGO_REVEAL})
#: Types built from `items` rather than from `text` alone.
ITEMISED = frozenset(
    {
        MotionElementType.LIST,
        MotionElementType.CHART,
        MotionElementType.COMPARE,
        MotionElementType.STEPS,
    }
)


class MotionElement(Artifact):
    type: MotionElementType
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(default="", max_length=180)
    secondary_text: str | None = Field(default=None, max_length=180)
    #: The points of a ``list``, in the order they appear.
    items: list[str] = Field(default_factory=list, max_length=6)
    reason: str = Field(min_length=1, max_length=300)
    #: Optional background image for an end card. A local PNG/JPEG/WebP, either a
    #: project asset or a plate recorded in visuals.json. Text is never part of
    #: it: the words above are drawn by the compositor from the brand contract.
    image_asset: str | None = None
    #: How much the plate is darkened so the end-card text stays readable.
    image_dim_pct: float = Field(default=45.0, ge=0.0, le=90.0)

    def _check_items(self) -> None:
        kind = self.type.value
        items = [item.strip() for item in self.items]
        limits = {
            MotionElementType.LIST: (2, 5),
            MotionElementType.STEPS: (2, 5),
            MotionElementType.CHART: (2, 6),
            MotionElementType.COMPARE: (2, 2),
        }
        low, high = limits[self.type]
        if not low <= len(items) <= high or any(not item or len(item) > 60 for item in items):
            count = f"{low}" if low == high else f"{low} to {high}"
            raise ValueError(f"a {kind} needs {count} items of at most 60 characters")
        if self.type is MotionElementType.CHART and not all(chart_value(item) for item in items):
            raise ValueError('every chart item reads "Label: number", e.g. "2024: 38"')
        if self.type is MotionElementType.COMPARE and not all(":" in item for item in items):
            raise ValueError('both compare items read "Label: text", e.g. "Before: 3 h"')

    @model_validator(mode="after")
    def _valid_interval(self) -> MotionElement:
        if self.end <= self.start:
            raise ValueError("motion element end must be after start")
        kind = self.type.value
        if self.type in TEXTLESS:
            if self.text or self.items:
                raise ValueError(f"a {kind} carries no text")
        elif self.type in ITEMISED:
            self._check_items()
        elif not self.text.strip():
            raise ValueError(f"a {kind} needs text")
        elif self.items:
            raise ValueError(
                f"items are only used by lists, charts, comparisons and steps, not a {kind}"
            )
        if self.type is MotionElementType.HOOK_CARD:
            if self.start > 0.5:
                raise ValueError(
                    "a hook_card opens the video: it must start within the first 0.5 s"
                )
            if len(self.text) > 90:
                raise ValueError(
                    "a hook_card is one line a viewer reads at a glance: at most 90 characters"
                )
        if self.type is MotionElementType.STAT and len(self.text) > 12:
            raise ValueError("a stat is one figure of at most 12 characters, e.g. '73%' or '3x'")
        if self.image_asset is not None:
            if self.type is not MotionElementType.END_CARD:
                raise ValueError(
                    "image_asset is only supported on an end_card; a plate behind a hook "
                    "or callout covers the speaker the edit was made for"
                )
            suffix = Path(self.image_asset).suffix.casefold()
            if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
                raise ValueError("image_asset must be a .png, .jpg, .jpeg or .webp file")
        return self


def chart_value(item: str) -> tuple[str, float] | None:
    """``"2024: 38,5%"`` as ``("2024", 38.5)``, or ``None`` when it is not one."""
    import re

    label, _, value = item.rpartition(":")
    match = re.search(r"-?\d+(?:[.,]\d+)?", value)
    if not label.strip() or match is None:
        return None
    return label.strip(), float(match.group().replace(",", "."))


class TransitionStyle(str, Enum):
    #: A quick push through the cut.
    ZOOM = "zoom"
    #: A whip sideways with motion blur.
    SLIDE = "slide"
    #: A brief wash of the brand's accent colour.
    FLASH = "flash"


class Transition(Artifact):
    """An effect across one cut, centred on the cut's output time."""

    at: float = Field(ge=0, description="Output time of the cut.")
    style: TransitionStyle = TransitionStyle.ZOOM
    duration: float = Field(default=0.4, ge=0.2, le=0.8)
    reason: str = Field(min_length=1, max_length=300)


class PunchIn(Artifact):
    """A timed push in on the picture, marking one editorial moment.

    The picture eases in, holds, and eases back out; captions and graphics stay
    where they are. ``focus_x``/``focus_y`` place the point that stays still,
    as fractions of the frame -- the default sits on a face in the upper half.
    """

    start: float = Field(ge=0)
    end: float = Field(gt=0)
    scale: float = Field(gt=1.0, le=1.5)
    focus_x: float = Field(default=0.5, ge=0.0, le=1.0)
    focus_y: float = Field(default=0.4, ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def _valid_interval(self) -> PunchIn:
        if self.end - self.start < 0.4:
            raise ValueError("a punch-in needs at least 0.4 s to ease in and out")
        return self


class MotionPlan(Artifact):
    """A restrained, reviewable visual layer; never a bag of random effects."""

    style: str = "editorial_clean"
    accent_color: str = Field(default="#FFD400", pattern=r"^#[0-9A-Fa-f]{6}$")
    text_color: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    background_color: str = Field(default="#101114", pattern=r"^#[0-9A-Fa-f]{6}$")
    font_family: str = Field(default="Inter", min_length=1, max_length=120)
    font_path: str | None = None
    elements: list[MotionElement] = Field(default_factory=list)
    punch_ins: list[PunchIn] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    rationale: str = Field(min_length=1, max_length=800)

    @model_validator(mode="after")
    def _punch_ins_do_not_overlap(self) -> MotionPlan:
        ordered = sorted(self.punch_ins, key=lambda p: p.start)
        for first, second in pairwise(ordered):
            if second.start < first.end:
                raise ValueError(
                    f"punch-ins at {first.start:.2f}s and {second.start:.2f}s overlap; "
                    "one push at a time"
                )
        return self

    def transition_problems(self, *, per_minute: float, duration: float) -> list[str]:
        """Where this plan uses more transitions than the energy level allows."""
        if not self.transitions:
            return []
        allowed = int(per_minute * max(duration, 1.0) / 60.0 + 1e-9)
        if len(self.transitions) > allowed:
            return [
                f"{len(self.transitions)} transitions in {duration:.0f} s; the project's "
                f"motion_energy allows {allowed} ({per_minute:g} per minute)"
            ]
        return []

    def punch_in_problems(self, *, limit: float, intensity: float) -> list[str]:
        """Where this plan exceeds the brand's movement contract."""
        if self.punch_ins and intensity <= 0:
            return [
                "the project sets punch_in_intensity: 0, which allows no movement, "
                f"but the motion plan has {len(self.punch_ins)} punch-in(s)"
            ]
        return [
            f"punch-in at {p.start:.2f}s scales to {p.scale:g}, above the brand limit {limit:g}"
            for p in self.punch_ins
            if p.scale > limit + 1e-9
        ]


class AccentKind(str, Enum):
    HOOK = "hook"
    STAT = "stat"
    CONTRAST = "contrast"
    QUESTION = "question"
    PUNCHLINE = "punchline"
    STEPS = "steps"
    TRANSITION = "transition"


class AccentCandidate(Artifact):
    """A moment the code found worth moving on, with the move it proposes.

    Exactly one of ``element``, ``punch_in`` and ``transition`` is set. Nothing
    is applied until the agent accepts the candidate by id.
    """

    id: str
    kind: AccentKind
    confidence: str = Field(pattern=r"^(high|medium)$")
    at: float = Field(ge=0, description="Output time.")
    quote: str = ""
    reason: str = Field(min_length=1)
    element: MotionElement | None = None
    punch_in: PunchIn | None = None
    transition: Transition | None = None

    @model_validator(mode="after")
    def _one_move(self) -> AccentCandidate:
        moves = [m for m in (self.element, self.punch_in, self.transition) if m is not None]
        if len(moves) != 1:
            raise ValueError("an accent proposes exactly one move")
        return self


class AccentCandidateSet(Artifact):
    """Every accent `motion suggest` found in one edit."""

    edl: str
    energy: str
    on_beat: bool = False
    candidates: list[AccentCandidate] = Field(default_factory=list)

    def by_id(self, candidate_id: str) -> AccentCandidate:
        for candidate in self.candidates:
            if candidate.id == candidate_id:
                return candidate
        known = ", ".join(c.id for c in self.candidates) or "<none>"
        raise KeyError(f"unknown accent {candidate_id!r}; known: {known}")
