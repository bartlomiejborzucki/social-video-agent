"""Intentional motion design rendered by Remotion after the technical edit."""

from __future__ import annotations

from enum import Enum
from itertools import pairwise
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    #: A call to action, above the caption area or in the top safe zone.
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
    #: A short text naming the scene ("Spróbuj tak"), never a card of its own
    #: and never drawn like a caption. It must fit the frame's title tab, which
    #: is measured against the frame's width at render time. The contract's
    #: ``label_style`` draws it as a chip in the top safe zone or as the title
    #: of a frame around the scene's captions.
    LABEL = "label"
    #: An emoji or a small project image reacting to one word, 0.6-1.5 s,
    #: in the safe zone and off the face, captions and scene frame.
    STICKER = "sticker"


class EndCardLayout(str, Enum):
    """How an end card shares the frame with its image."""

    #: Text over the image, which fills the frame and is dimmed.
    OVERLAY = "overlay"
    #: The image whole in the upper part (a book cover), the text below it.
    IMAGE_TOP = "image_top"


class StickerAnimation(str, Enum):
    POP = "pop"
    SHAKE = "shake"
    PULSE = "pulse"
    DROP = "drop"


#: Stickers allowed in one reel, by `motion_energy`.
STICKER_LIMIT = {"calm": 0, "lively": 1, "bold": 2}
#: A sticker never shares frame 0 with the opening.
STICKER_EARLIEST = 0.3


class ElementPosition(str, Enum):
    """Where an element that may move sits on the frame."""

    #: In the top safe zone, clear of the captions and usually of the face.
    TOP = "top"
    #: Centred vertically: the 1.0 placement of lists and steps.
    CENTER = "center"
    #: Just above the caption band: the 1.0 placement of a call to action.
    ABOVE_CAPTIONS = "above_captions"


#: The positions each movable type accepts, its default first.
POSITIONS: dict[MotionElementType, tuple[ElementPosition, ...]] = {
    MotionElementType.CTA: (ElementPosition.ABOVE_CAPTIONS, ElementPosition.TOP),
    MotionElementType.LIST: (ElementPosition.CENTER, ElementPosition.TOP),
    MotionElementType.STEPS: (ElementPosition.CENTER, ElementPosition.TOP),
}


#: Types whose points may each enter on the word that names them.
ITEM_ANCHORED = frozenset({MotionElementType.LIST, MotionElementType.STEPS})


class WordAnchor(BaseModel):
    """One spoken word: its text and which time it is said (1 = the first)."""

    model_config = ConfigDict(extra="forbid")

    word: str = Field(min_length=1, max_length=60)
    occurrence: int = Field(default=1, ge=1)


#: Types drawn without words of their own.
TEXTLESS = frozenset(
    {MotionElementType.PROGRESS, MotionElementType.LOGO_REVEAL, MotionElementType.STICKER}
)
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
    #: Placement of a ``cta`` (above_captions or top) or a ``list``/``steps``
    #: (center or top). Empty means the type's 1.0 placement.
    position: ElementPosition | None = None
    #: An end card after the last word: the edit's timeline is extended by
    #: the card's length (end - start), held in silence, instead of the card
    #: covering the last spoken seconds. Its start is set to the edit's end.
    hold: bool = False
    #: An end card's composition with its image_asset.
    layout: EndCardLayout = EndCardLayout.OVERLAY
    #: A sticker: one emoji from the contract's `sticker_allowlist`, or a
    #: project image in `image_asset` (PNG, WebP or SVG).
    emoji: str | None = None
    #: Play the emoji's Noto Animated Emoji clip instead of drawing its glyph.
    #: Downloaded once into the cache; CC BY 4.0, credited in the manifest.
    animated_emoji: bool = False
    #: Anchor a sticker to a spoken word: its start becomes the start of that
    #: word's ``occurrence``-th appearance in the captions.
    at_word: str | None = Field(default=None, max_length=60)
    occurrence: int = Field(default=1, ge=1)
    animation: StickerAnimation = StickerAnimation.POP
    #: Height of the sticker, as a percentage of the output height.
    size_pct: float = Field(default=12.0, ge=3.0, le=30.0)
    #: Centre of the sticker, as fractions of the output width and height.
    x_pct: float = Field(default=0.78, ge=0.0, le=1.0)
    y_pct: float = Field(default=0.3, ge=0.0, le=1.0)
    #: A list's or steps' points, each entering on the word that names it: one
    #: entry per item, a word (its first occurrence) or ``{word, occurrence}``.
    item_at_words: list[WordAnchor] | None = None
    #: When each item enters, on the output timeline. Set from
    #: ``item_at_words`` by `compile` and the render; without either, the
    #: items are revealed evenly, as before.
    item_times: list[float] | None = None

    @field_validator("item_at_words", mode="before")
    @classmethod
    def _anchor_entries(cls, value):
        if isinstance(value, list):
            return [{"word": entry} if isinstance(entry, str) else entry for entry in value]
        return value

    @property
    def placement(self) -> ElementPosition | None:
        """The position this element is drawn at, its default filled in."""
        allowed = POSITIONS.get(self.type)
        if allowed is None:
            return None
        return self.position or allowed[0]

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
        if self.position is not None:
            allowed = POSITIONS.get(self.type, ())
            if self.position not in allowed:
                names = ", ".join(p.value for p in allowed) or "none (it has a fixed place)"
                raise ValueError(f"a {kind} accepts position: {names}")
        if self.type is MotionElementType.LABEL and len(self.text) > 80:
            raise ValueError("a label is a short text over the shot: at most 80 characters")
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
        if self.type is not MotionElementType.END_CARD and (
            self.hold or self.layout is not EndCardLayout.OVERLAY
        ):
            raise ValueError("hold and layout are only used by an end_card")
        if self.type is MotionElementType.STICKER:
            self._check_sticker()
        elif self.emoji is not None or self.at_word is not None or self.animated_emoji:
            raise ValueError("emoji, animated_emoji and at_word are only used by a sticker")
        self._check_item_anchors()
        if self.layout is EndCardLayout.IMAGE_TOP and self.image_asset is None:
            raise ValueError("layout image_top needs an image_asset to put above the text")
        if self.image_asset is not None and self.type is not MotionElementType.STICKER:
            if self.type is not MotionElementType.END_CARD:
                raise ValueError(
                    "image_asset is only supported on an end_card or a sticker; a plate "
                    "behind a hook or callout covers the speaker the edit was made for"
                )
            suffix = Path(self.image_asset).suffix.casefold()
            if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
                raise ValueError("image_asset must be a .png, .jpg, .jpeg or .webp file")
        return self

    def _check_item_anchors(self) -> None:
        if self.item_at_words is None and self.item_times is None:
            return
        kind = self.type.value
        if self.type not in ITEM_ANCHORED:
            names = ", ".join(sorted(t.value for t in ITEM_ANCHORED))
            raise ValueError(f"item_at_words and item_times are used by {names}, not a {kind}")
        given = (("item_at_words", self.item_at_words), ("item_times", self.item_times))
        for name, values in given:
            if values is not None and len(values) != len(self.items):
                raise ValueError(
                    f"a {kind} with {len(self.items)} items needs {len(self.items)} {name}, "
                    f"one per item; got {len(values)}"
                )
        if self.item_times is not None:
            if any(b < a for a, b in pairwise(self.item_times)):
                raise ValueError(f"a {kind}'s items enter in order; item_times go backwards")
            if self.item_times[0] < self.start - 1e-3 or self.item_times[-1] > self.end + 1e-3:
                raise ValueError(
                    f"a {kind}'s items enter while it is on screen, "
                    f"{self.start:.2f}-{self.end:.2f}s"
                )

    def _check_sticker(self) -> None:
        if (self.emoji is None) == (self.image_asset is None):
            raise ValueError("a sticker shows one emoji or one image_asset")
        if self.animated_emoji and self.emoji is None:
            raise ValueError("animated_emoji animates an emoji sticker, not an image")
        if self.image_asset is not None:
            suffix = Path(self.image_asset).suffix.casefold()
            if suffix not in {".png", ".webp", ".svg"}:
                raise ValueError("a sticker image must be a .png, .webp or .svg file")
        length = self.end - self.start
        if not 0.6 - 1e-6 <= length <= 1.5 + 1e-6:
            raise ValueError(f"a sticker stays 0.6-1.5 s on screen, not {length:.2f} s")
        if self.start < STICKER_EARLIEST:
            raise ValueError(
                f"a sticker never shares the opening frame: start at {STICKER_EARLIEST} s or later"
            )
        left, top, right, bottom = self.box
        if left < 0 or top < 0 or right > 1 or bottom > 1:
            raise ValueError("a sticker must lie wholly inside the frame")

    @property
    def box(self) -> tuple[float, float, float, float]:
        """A sticker's (left, top, right, bottom), as fractions of a 9:16 frame."""
        half_h = self.size_pct / 100 / 2
        half_w = half_h * 16 / 9
        return (self.x_pct - half_w, self.y_pct - half_h, self.x_pct + half_w, self.y_pct + half_h)


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
    #: A warm film light leak over the cut, tinted to the brand accent.
    LIGHT_LEAK = "light_leak"


class Shake(Artifact):
    """The picture shaken for a moment, e.g. under "Zgodziłeś!"."""

    start: float = Field(ge=0)
    end: float = Field(gt=0)
    #: Largest displacement, as a percentage of the output width.
    amplitude_pct: float = Field(default=1.2, gt=0.0, le=4.0)
    frequency_hz: float = Field(default=9.0, ge=2.0, le=20.0)
    at_word: str | None = Field(default=None, max_length=60)
    occurrence: int = Field(default=1, ge=1)
    reason: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def _valid(self) -> Shake:
        if not 0.15 <= self.end - self.start <= 2.0:
            raise ValueError("a shake lasts 0.15-2 s; a longer one is a grade (`shake`)")
        return self


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
    #: Moments the whole picture shakes, drawn by both renderers.
    shakes: list[Shake] = Field(default_factory=list)
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
    #: A cut inside one take while the speaker keeps talking: a sharp change of
    #: framing, not a transition that blurs the mouth mid-word.
    JUMP = "jump"
    #: The first range starting where the picture moves, not on a still frame.
    OPENING = "opening"
    #: A strong push-in on the first key word, 1.0-1.5 s in: never frame 0.
    HOOK_PUNCH = "hook_punch"


class RangeStart(Artifact):
    """A new in-point for one EDL range's picture, in source seconds."""

    range_index: int = Field(ge=0)
    video_start: float = Field(ge=0.0)
    reason: str = Field(min_length=1, max_length=300)


class RangeZoom(Artifact):
    """A fixed framing for one EDL range: the picture jumps to it on the cut."""

    range_index: int = Field(ge=0)
    zoom: float = Field(ge=1.0, le=1.2)
    reason: str = Field(min_length=1, max_length=300)


class AccentCandidate(Artifact):
    """A moment the code found worth moving on, with the move it proposes.

    Exactly one of ``element``, ``punch_in``, ``transition`` and ``range_zoom``
    is set. Nothing is applied until the agent accepts the candidate by id; a
    range zoom is applied to the edit plan and the EDL, not the motion plan.
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
    range_zoom: RangeZoom | None = None
    range_start: RangeStart | None = None

    @model_validator(mode="after")
    def _one_move(self) -> AccentCandidate:
        moves = [
            m
            for m in (
                self.element, self.punch_in, self.transition, self.range_zoom, self.range_start
            )
            if m is not None
        ]  # fmt: skip
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
