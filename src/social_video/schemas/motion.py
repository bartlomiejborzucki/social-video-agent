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
    #: A habit crossed out and replaced: the line appears, a stroke in the
    #: accent crosses it out on a word, and ``replacement`` takes its place.
    STRIKE = "strike"
    #: A line someone says, or a message someone sent, as a bubble over the
    #: head: ``variant`` speech or message, entering on its word with a pop.
    BUBBLE = "bubble"
    #: A small flat icon of the thing just named, over the head, 0.6-1.2 s.
    ICON = "icon"
    #: A process as a bar of 2-5 coloured stages, each entering on its word;
    #: a pointer then runs through it, and ``done_text`` closes it with a tick.
    PROCESS = "process"
    #: One key word built letter by letter with small sparks, on its word.
    KINETIC_WORD = "kinetic_word"
    #: A picture or a short clip from the project (a comment, a book page, an
    #: earlier reel) as a card over the speaker, who stays in the shot.
    INSET = "inset"
    #: A Remotion component written for this one reel (motion/custom/<id>.tsx),
    #: drawn inside its zone with the brand tokens and its words' times.
    CUSTOM = "custom"
    #: The reel's title over the speaker in the opening seconds: two short
    #: lines at most, entering word by word from ~0.4 s while the speech and
    #: the captions already run. Not a card: the picture stays live under it.
    HOOK_TITLE = "hook_title"
    #: What comes next ("Part 2 tomorrow"), over the speaker in the last
    #: seconds, styled like the hook title. Not an end card: the face goes on.
    END_TEASER = "end_teaser"
    #: A second shot cut in for 0.5-2.5 s over the whole frame (the book, the
    #: gesture), while the voice of the main recording goes on under it.
    INSERT = "insert"
    #: A large picture from the project's prop library (a book cover, a form,
    #: a screenshot), entering on its word for 2-4 s.
    PROP = "prop"


class EndCardLayout(str, Enum):
    """How an end card shares the frame with its image."""

    #: Text over the image, which fills the frame and is dimmed.
    OVERLAY = "overlay"
    #: The image whole in the upper part (a book cover), the text below it.
    IMAGE_TOP = "image_top"


class TitleStyle(str, Enum):
    """How a hook title or end teaser is drawn."""

    #: Each line on a marker field in the accent colour, with a thin border.
    HIGHLIGHT = "highlight"
    #: The lines in one rounded pill in the brand's second colour.
    PILL = "pill"
    #: Bold text with an outline, no field.
    PLAIN = "plain"


class TitleEntry(str, Enum):
    """How a title's words, or a prop, come in."""

    #: Word by word, over its first 0.4 s.
    TYPEWRITER = "typewriter"
    POP = "pop"
    SLIDE = "slide"


class InsertCut(str, Enum):
    """How an insert comes in and goes out."""

    CUT = "cut"
    #: A whip blur on the way in and out.
    WHOOSH = "whoosh"


class PropStyle(str, Enum):
    """How a prop is framed."""

    #: The picture alone, with a soft shadow.
    OBJECT = "object"
    #: A screenshot: a white frame with rounded corners and a shadow.
    SCREENSHOT = "screenshot"


class Series(BaseModel):
    """Which part of a series this reel is: part 2 of 4."""

    model_config = ConfigDict(extra="forbid")

    part: int = Field(ge=1, le=99)
    total: int | None = Field(default=None, ge=2, le=99)

    @model_validator(mode="after")
    def _part_within_total(self) -> Series:
        if self.total is not None and self.part > self.total:
            raise ValueError(f"part {self.part} of a series of {self.total} does not exist")
        return self

    @property
    def label(self) -> str:
        return f"{self.part}/{self.total}" if self.total else f"{self.part}"


#: A hook title opens on the speech, never on frame 0, and never late.
HOOK_TITLE_EARLIEST = 0.2
HOOK_TITLE_LATEST = 2.0
#: A hook title past this start is reported by the opening checks.
HOOK_TITLE_EXPECTED_BY = 1.0
#: An end teaser covers this many of the last seconds unless the plan says.
END_TEASER_FROM_END = 4.0


class StickerAnimation(str, Enum):
    POP = "pop"
    SHAKE = "shake"
    PULSE = "pulse"
    DROP = "drop"


#: Stickers allowed in one reel, by `motion_energy`.
STICKER_LIMIT = {"calm": 0, "lively": 1, "bold": 2}
#: A sticker never shares frame 0 with the opening.
STICKER_EARLIEST = 0.3
#: Icons allowed in one reel, by `motion_energy`; counted apart from stickers.
ICON_LIMIT = {"calm": 0, "lively": 2, "bold": 4}
#: Words built letter by letter allowed in one reel, by `motion_energy`.
KINETIC_LIMIT = {"calm": 0, "lively": 1, "bold": 1}
#: Where an icon sits unless the plan says: centred over the head, in the top zone.
ICON_PLACE = {"size_pct": 9.0, "x_pct": 0.5, "y_pct": 0.17}
#: An inset card is this wide, as a share of the frame's width, unless the plan says.
INSET_SIZE = {"size_pct": 70.0}
#: A card never takes more of the frame's height than this.
INSET_MAX_HEIGHT = 0.42


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
    MotionElementType.STRIKE: (ElementPosition.TOP, ElementPosition.CENTER),
    MotionElementType.BUBBLE: (ElementPosition.TOP,),
    MotionElementType.PROCESS: (ElementPosition.TOP,),
    MotionElementType.INSET: (ElementPosition.TOP, ElementPosition.CENTER),
    MotionElementType.CUSTOM: (ElementPosition.TOP, ElementPosition.CENTER),
    MotionElementType.HOOK_TITLE: (ElementPosition.TOP, ElementPosition.CENTER),
    MotionElementType.END_TEASER: (ElementPosition.ABOVE_CAPTIONS, ElementPosition.TOP),
    MotionElementType.PROP: (ElementPosition.CENTER, ElementPosition.TOP),
}


#: Types placed on a spoken word with `at_word`: it sets their start, except a
#: strike's, which it sets the moment of crossing out.
AT_WORD_TYPES = frozenset(
    {
        MotionElementType.STICKER,
        MotionElementType.STRIKE,
        MotionElementType.BUBBLE,
        MotionElementType.ICON,
        MotionElementType.KINETIC_WORD,
        MotionElementType.INSET,
        MotionElementType.CUSTOM,
        MotionElementType.INSERT,
        MotionElementType.PROP,
    }
)
#: Graphics that play with the words. A reel on a sensitive subject (death,
#: illness, grief) takes none of them; see `MotionPlan.sensitive_topic`.
PLAYFUL = frozenset(
    {
        MotionElementType.STICKER,
        MotionElementType.STRIKE,
        MotionElementType.BUBBLE,
        MotionElementType.ICON,
        MotionElementType.PROCESS,
        MotionElementType.KINETIC_WORD,
        MotionElementType.INSET,
        MotionElementType.CUSTOM,
    }
)
#: Playful graphics never share the opening frame with the first caption.
PLAYFUL_EARLIEST = 0.3


class BubbleVariant(str, Enum):
    #: Something said: a child's or a parent's line, with a tail.
    SPEECH = "speech"
    #: Something written: a message or a comment, with a notification dot.
    MESSAGE = "message"


class BubbleTail(str, Enum):
    """Where a speech bubble's tail points."""

    #: Down, at the person talking under it.
    SPEAKER = "speaker"
    #: Out of the frame on that side, at someone off camera.
    LEFT = "left"
    RIGHT = "right"


class StrikeMark(str, Enum):
    """What crosses out a strike's line, besides the stroke itself."""

    NONE = "none"
    SCISSORS = "scissors"
    CROSS = "cross"


#: Types whose points may each enter on the word that names them.
ITEM_ANCHORED = frozenset(
    {MotionElementType.LIST, MotionElementType.STEPS, MotionElementType.PROCESS}
)


class WordAnchor(BaseModel):
    """One spoken word: its text and which time it is said (1 = the first)."""

    model_config = ConfigDict(extra="forbid")

    word: str = Field(min_length=1, max_length=60)
    occurrence: int = Field(default=1, ge=1)


#: Types drawn without words of their own.
TEXTLESS = frozenset(
    {
        MotionElementType.PROGRESS,
        MotionElementType.LOGO_REVEAL,
        MotionElementType.STICKER,
        MotionElementType.ICON,
        MotionElementType.INSET,
        MotionElementType.CUSTOM,
        MotionElementType.INSERT,
        MotionElementType.PROP,
    }
)
#: Types placed by a box (``size_pct``, ``x_pct``, ``y_pct``) rather than a band.
BOXED = frozenset({MotionElementType.STICKER, MotionElementType.ICON})
#: Types built from `items` rather than from `text` alone.
ITEMISED = frozenset(
    {
        MotionElementType.LIST,
        MotionElementType.CHART,
        MotionElementType.COMPARE,
        MotionElementType.STEPS,
        MotionElementType.PROCESS,
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
    #: Height of a sticker or icon, as a percentage of the output height (at
    #: most 30); the width of an inset card, as a percentage of its width.
    size_pct: float = Field(default=12.0, ge=3.0, le=90.0)
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
    #: A strike: the line that takes the crossed-out one's place, and the word
    #: it enters on (else shortly after the stroke).
    replacement: str | None = Field(default=None, max_length=40)
    replace_at_word: str | None = Field(default=None, max_length=60)
    replace_occurrence: int = Field(default=1, ge=1)
    #: A strike's moments on the output timeline: crossed out, then replaced.
    #: Set from `at_word` and `replace_at_word`; empty means a third of the
    #: way in, and 0.7 s later.
    strike_at: float | None = Field(default=None, ge=0)
    replace_at: float | None = Field(default=None, ge=0)
    #: What crosses the line out besides the stroke: scissors or a cross.
    strike_mark: StrikeMark = StrikeMark.NONE
    #: A bubble: something said (speech) or written (message), and where a
    #: speech bubble's tail points.
    variant: BubbleVariant | None = None
    tail: BubbleTail | None = None
    #: An icon: its name in the icon set (Tabler Icons, e.g. ``bath``).
    icon: str | None = Field(default=None, max_length=40)
    #: A process: the state it ends in, shown with a tick ("gotowe do snu").
    done_text: str | None = Field(default=None, max_length=24)
    #: An inset: a short clip from the project instead of an image, played
    #: from ``source_start`` to ``source_end`` (seconds in the clip), muted.
    video_asset: str | None = None
    source_start: float | None = Field(default=None, ge=0)
    source_end: float | None = Field(default=None, gt=0)
    #: An inset's rounded corners, in pixels of a 1920-high frame.
    corner_radius: int | None = Field(default=None, ge=0, le=120)
    #: An inset's rights, as for the b-roll library: whose it is and that it
    #: may be shown. A picture with a child's face is never shown.
    rights: str | None = Field(default=None, max_length=200)
    child_face_visible: bool = False
    #: A custom element: the id of its component, ``motion/custom/<id>.tsx`` in
    #: the edit workspace.
    component: str | None = Field(default=None, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    #: A hook title or end teaser: how it is drawn, how its words come in (a
    #: prop's entry too), and the words of ``text`` set in the accent colour.
    title_style: TitleStyle | None = None
    entry: TitleEntry | None = None
    emphasis_words: list[str] = Field(default_factory=list, max_length=8)
    #: An end teaser: how many of the edit's last seconds it covers. Its
    #: start and end are set from it once the edit's length is known.
    from_end: float | None = Field(default=None, ge=1.0, le=6.0)
    #: A hook title or end teaser: the part of a series this reel is, drawn
    #: after ``secondary_text`` ("Part" + " 2/4").
    series: Series | None = None
    #: An insert: how it cuts in and out.
    cut_style: InsertCut | None = None
    #: A prop: its id in the project's prop library, and how it is framed.
    prop: str | None = Field(default=None, pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
    prop_style: PropStyle | None = None

    @model_validator(mode="before")
    @classmethod
    def _icon_place(cls, data):
        # An icon sits over the head unless the plan places it; a sticker
        # keeps the defaults above.
        if isinstance(data, dict) and data.get("type") in ("icon", MotionElementType.ICON):
            data = {**ICON_PLACE, **data}
        if isinstance(data, dict) and data.get("type") in ("inset", MotionElementType.INSET):
            data = {**INSET_SIZE, **data}
        if isinstance(data, dict) and data.get("type") in ("prop", MotionElementType.PROP):
            data = {"size_pct": 45.0, **data}
        teaser = isinstance(data, dict) and data.get("type") in (
            "end_teaser",
            MotionElementType.END_TEASER,
        )
        # Without times of its own a teaser is placed from the end once the
        # edit's length is known; until then it only needs a valid interval
        # of that length. Times the plan gives are kept.
        if teaser and "start" not in data and "end" not in data:
            length = data.get("from_end") or END_TEASER_FROM_END
            data = {**data, "from_end": length, "start": 0.0, "end": length}
        return data

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
            MotionElementType.PROCESS: (2, 5),
        }
        low, high = limits[self.type]
        longest = 12 if self.type is MotionElementType.PROCESS else 60
        if not low <= len(items) <= high or any(not item or len(item) > longest for item in items):
            count = f"{low}" if low == high else f"{low} to {high}"
            raise ValueError(f"a {kind} needs {count} items of at most {longest} characters")
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
        elif self.emoji is not None or self.animated_emoji:
            raise ValueError("emoji and animated_emoji are only used by a sticker")
        if self.at_word is not None and self.type not in AT_WORD_TYPES:
            names = ", ".join(sorted(t.value for t in AT_WORD_TYPES))
            raise ValueError(f"at_word places {names} on a word, not a {kind}")
        if self.type in PLAYFUL and self.start < PLAYFUL_EARLIEST:
            raise ValueError(
                f"a {kind} never shares the opening frame: start at {PLAYFUL_EARLIEST} s or later"
            )
        if self.type is MotionElementType.ICON:
            self._check_icon()
        elif self.icon is not None:
            raise ValueError("icon is only used by an icon")
        if self.type is MotionElementType.PROCESS:
            if len(self.text) > 40:
                raise ValueError("a process's title (text) is at most 40 characters")
            if self.end - self.start < 2.5 - 1e-6:
                raise ValueError("a process needs at least 2.5 s for its stages and pointer")
        elif self.done_text is not None:
            raise ValueError("done_text is only used by a process")
        if self.type is MotionElementType.INSET:
            self._check_inset()
        elif self.type is not MotionElementType.INSERT and (
            self.video_asset is not None
            or self.source_start is not None
            or self.source_end is not None
            or self.corner_radius is not None
            or self.rights is not None
            or self.child_face_visible
        ):
            raise ValueError(
                "video_asset, source_start, source_end, corner_radius, rights and "
                "child_face_visible are only used by an inset or an insert"
            )
        if self.type is MotionElementType.CUSTOM:
            if not self.component:
                raise ValueError("a custom element names its component, motion/custom/<id>.tsx")
            if not 0.6 - 1e-6 <= self.end - self.start <= 8.0 + 1e-6:
                raise ValueError(
                    f"a custom element stays 0.6-8 s on screen, not {self.end - self.start:.2f} s"
                )
        elif self.component is not None:
            raise ValueError("component is only used by a custom element")
        if self.type is MotionElementType.KINETIC_WORD:
            word = self.text.strip()
            if len(word) > 12 or any(ch.isspace() for ch in word):
                raise ValueError("a kinetic_word is one word of at most 12 characters")
            if not 0.8 - 1e-6 <= self.end - self.start <= 2.5 + 1e-6:
                raise ValueError(
                    f"a kinetic_word stays 0.8-2.5 s on screen, not {self.end - self.start:.2f} s"
                )
        if self.type is MotionElementType.BUBBLE:
            self._check_bubble()
        elif self.variant is not None or self.tail is not None:
            raise ValueError("variant and tail are only used by a bubble")
        if self.type is MotionElementType.STRIKE:
            self._check_strike()
        elif (
            self.replacement is not None
            or self.replace_at_word is not None
            or self.strike_at is not None
            or self.replace_at is not None
            or self.strike_mark is not StrikeMark.NONE
        ):
            raise ValueError(
                "replacement, replace_at_word, strike_at, replace_at and strike_mark "
                "are only used by a strike"
            )
        self._check_titles()
        if self.type is MotionElementType.INSERT:
            self._check_insert()
        elif self.cut_style is not None:
            raise ValueError("cut_style is only used by an insert")
        if self.type is MotionElementType.PROP:
            self._check_prop()
        elif self.prop is not None or self.prop_style is not None:
            raise ValueError("prop and prop_style are only used by a prop")
        self._check_item_anchors()
        if self.layout is EndCardLayout.IMAGE_TOP and self.image_asset is None:
            raise ValueError("layout image_top needs an image_asset to put above the text")
        if self.image_asset is not None and self.type not in (
            MotionElementType.STICKER,
            MotionElementType.INSET,
        ):
            if self.type is not MotionElementType.END_CARD:
                raise ValueError(
                    "image_asset is only supported on an end_card, a sticker or an inset; a "
                    "plate behind a hook or callout covers the speaker the edit was made for"
                )
            suffix = Path(self.image_asset).suffix.casefold()
            if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
                raise ValueError("image_asset must be a .png, .jpg, .jpeg or .webp file")
        return self

    def _check_inset(self) -> None:
        if (self.image_asset is None) == (self.video_asset is None):
            raise ValueError("an inset shows one image_asset or one video_asset")
        if self.image_asset is not None:
            if Path(self.image_asset).suffix.casefold() not in {".png", ".jpg", ".jpeg", ".webp"}:
                raise ValueError("an inset image must be a .png, .jpg, .jpeg or .webp file")
            if self.source_start is not None or self.source_end is not None:
                raise ValueError("source_start and source_end trim an inset's video_asset")
        else:
            assert self.video_asset is not None
            if Path(self.video_asset).suffix.casefold() not in {".mp4", ".mov", ".m4v", ".webm"}:
                raise ValueError("an inset clip must be a .mp4, .mov, .m4v or .webm file")
            start = self.source_start or 0.0
            if self.source_end is not None and self.source_end <= start:
                raise ValueError("an inset clip's source_end comes after its source_start")
        if not (self.rights or "").strip():
            raise ValueError(
                "an inset names its rights (whose picture it is and that it may be shown), "
                "as the b-roll library does"
            )
        if self.child_face_visible:
            raise ValueError("an inset with a child's face is never shown")
        if not 30.0 <= self.size_pct <= 90.0:
            raise ValueError("an inset card is 30-90 % of the frame's width (size_pct)")
        length = self.end - self.start
        if not 1.5 - 1e-6 <= length <= 8.0 + 1e-6:
            raise ValueError(f"an inset stays 1.5-8 s on screen, not {length:.2f} s")

    def _check_titles(self) -> None:
        titled = self.type in (MotionElementType.HOOK_TITLE, MotionElementType.END_TEASER)
        if not titled:
            if self.title_style is not None or self.series is not None or self.emphasis_words:
                raise ValueError(
                    "title_style, series and emphasis_words are only used by a hook_title "
                    "or an end_teaser"
                )
            if self.from_end is not None:
                raise ValueError("from_end is only used by an end_teaser")
            if self.entry is not None and self.type is not MotionElementType.PROP:
                raise ValueError("entry is only used by a hook_title, an end_teaser or a prop")
            return
        kind = self.type.value
        words = self.text.split()
        if self.entry is TitleEntry.SLIDE:
            raise ValueError(f"a {kind} comes in typewriter or pop")
        if len(self.secondary_text or "") > 24:
            raise ValueError(f"a {kind}'s subtitle (secondary_text) is at most 24 characters")
        keys = {_key(word) for word in words}
        for word in self.emphasis_words:
            if _key(word) not in keys:
                raise ValueError(f"emphasis word {word!r} is not in the {kind}'s text")
        length = self.end - self.start
        if self.type is MotionElementType.HOOK_TITLE:
            if len(words) > 8 or len(self.text) > 60:
                raise ValueError(
                    "a hook_title is read at a glance: at most 8 words and 60 characters"
                )
            if not HOOK_TITLE_EARLIEST - 1e-6 <= self.start <= HOOK_TITLE_LATEST + 1e-6:
                raise ValueError(
                    f"a hook_title enters on the speech, {HOOK_TITLE_EARLIEST}-"
                    f"{HOOK_TITLE_LATEST:g} s in; frame 0 stays the scene"
                )
            if not 2.0 - 1e-6 <= length <= 4.0 + 1e-6:
                raise ValueError(f"a hook_title stays 2-4 s on screen, not {length:.2f} s")
            if self.from_end is not None:
                raise ValueError("from_end is only used by an end_teaser")
        else:
            if len(words) > 12 or len(self.text) > 70:
                raise ValueError("an end_teaser is at most 12 words and 70 characters")
            if not 1.0 - 1e-6 <= length <= 6.0 + 1e-6:
                raise ValueError(f"an end_teaser stays 1-6 s on screen, not {length:.2f} s")

    def _check_insert(self) -> None:
        if self.video_asset is None:
            raise ValueError("an insert cuts in one video_asset, a second shot of the same scene")
        if self.image_asset is not None:
            raise ValueError("an insert is a clip; a still goes in an inset or a prop")
        if Path(self.video_asset).suffix.casefold() not in {".mp4", ".mov", ".m4v", ".webm"}:
            raise ValueError("an insert clip must be a .mp4, .mov, .m4v or .webm file")
        start = self.source_start or 0.0
        if self.source_end is not None and self.source_end <= start:
            raise ValueError("an insert clip's source_end comes after its source_start")
        if not (self.rights or "").strip():
            raise ValueError(
                "an insert names its rights (whose picture it is and that it may be shown)"
            )
        if self.child_face_visible:
            raise ValueError("an insert with a child's face is never shown")
        if self.corner_radius is not None:
            raise ValueError("an insert fills the frame; corner_radius belongs to an inset")
        length = self.end - self.start
        if not 0.5 - 1e-6 <= length <= 2.5 + 1e-6:
            raise ValueError(f"an insert is cut in for 0.5-2.5 s, not {length:.2f} s")
        if self.start < 1.0:
            raise ValueError("an insert never replaces the opening: start at 1.0 s or later")

    def _check_prop(self) -> None:
        if not self.prop:
            raise ValueError("a prop names its id in the project's prop library (props.yaml)")
        if self.image_asset is not None or self.video_asset is not None:
            raise ValueError("a prop's picture comes from the prop library, not image_asset")
        if not 20.0 <= self.size_pct <= 70.0:
            raise ValueError("a prop is 20-70 % of the frame's width (size_pct)")
        length = self.end - self.start
        if not 1.5 - 1e-6 <= length <= 4.5 + 1e-6:
            raise ValueError(f"a prop stays 1.5-4.5 s on screen, not {length:.2f} s")

    def _check_icon(self) -> None:
        self._check_size()
        if not self.icon or self.image_asset is not None:
            raise ValueError("an icon names one icon of the set, e.g. icon: bath")
        length = self.end - self.start
        if not 0.6 - 1e-6 <= length <= 1.2 + 1e-6:
            raise ValueError(f"an icon pops in for 0.6-1.2 s, not {length:.2f} s")
        if self.animation is not StickerAnimation.POP:
            raise ValueError("an icon pops in; animation is pop")
        left, top, right, bottom = self.box
        if left < 0 or top < 0 or right > 1 or bottom > 1:
            raise ValueError("an icon must lie wholly inside the frame")

    def _check_bubble(self) -> None:
        if len(self.text) > 60 or len(self.secondary_text or "") > 40:
            raise ValueError(
                "a bubble holds a line of at most 60 characters and a note of at most 40"
            )
        length = self.end - self.start
        if not 1.2 - 1e-6 <= length <= 6.0 + 1e-6:
            raise ValueError(f"a bubble stays 1.2-6 s on screen, not {length:.2f} s")
        if self.tail is not None and self.variant is BubbleVariant.MESSAGE:
            raise ValueError("a message bubble has no tail; only speech points at its speaker")

    @property
    def bubble_variant(self) -> BubbleVariant:
        return self.variant or BubbleVariant.SPEECH

    def _check_strike(self) -> None:
        if len(self.text) > 40 or not (self.replacement or "").strip():
            raise ValueError(
                "a strike crosses out a line of at most 40 characters and puts a "
                "replacement of at most 40 in its place"
            )
        length = self.end - self.start
        if not 1.5 - 1e-6 <= length <= 10.0 + 1e-6:
            raise ValueError(f"a strike stays 1.5-10 s on screen, not {length:.2f} s")
        crossed, replaced = self.strike_moments
        if not self.start < crossed < replaced < self.end:
            raise ValueError(
                f"a strike is crossed out ({crossed:.2f}s) and replaced ({replaced:.2f}s) "
                f"while it is on screen, {self.start:.2f}-{self.end:.2f}s"
            )

    @property
    def strike_moments(self) -> tuple[float, float]:
        """When a strike's line is crossed out, and when its replacement enters."""
        crossed = self.strike_at
        if crossed is None:
            crossed = self.start + min(1.2, (self.end - self.start) / 3)
        replaced = self.replace_at if self.replace_at is not None else crossed + 0.7
        return round(crossed, 3), round(replaced, 3)

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

    def _check_size(self) -> None:
        if self.size_pct > 30:
            raise ValueError(
                f"a {self.type.value} is at most 30 % of the frame's height (size_pct)"
            )

    def _check_sticker(self) -> None:
        self._check_size()
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
        """A sticker's or icon's (left, top, right, bottom), as fractions of a 9:16 frame."""
        half_h = self.size_pct / 100 / 2
        half_w = half_h * 16 / 9
        return (self.x_pct - half_w, self.y_pct - half_h, self.x_pct + half_w, self.y_pct + half_h)


def _key(word: str) -> str:
    return "".join(ch for ch in word.casefold() if ch.isalnum())


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


class EffectType(str, Enum):
    """A change of the whole picture for a moment, on a static camera."""

    #: The picture shrinks into a white-bordered frame over a blurred copy.
    FRAME_IN_FRAME = "frame_in_frame"
    #: The picture inside a phone mock-up ("send this to someone").
    DEVICE_FRAME = "device_frame"
    #: The picture and its mirror image side by side.
    SPLIT_MIRROR = "split_mirror"
    #: Three slices of the picture, the middle one larger.
    TRIPTYCH = "triptych"
    #: A sideways motion blur, as a transition.
    WHIP_BLUR = "whip_blur"
    #: A torn-paper edge sweeping across, with grain.
    TEAR = "tear"
    #: A short black-and-white high-contrast flash.
    BW_FLASH = "bw_flash"
    #: A halftone dot screen over the picture. No cut-out: a translucent layer.
    HALFTONE_BG = "halftone_bg"
    #: Speed lines from the frame edges towards the centre. No cut-out.
    SPEED_LINES = "speed_lines"
    #: The picture tilted 3-5 degrees.
    TILT = "tilt"


#: How long each effect may last, in seconds.
EFFECT_LENGTHS: dict[EffectType, tuple[float, float]] = {
    EffectType.FRAME_IN_FRAME: (0.6, 4.0),
    EffectType.DEVICE_FRAME: (0.6, 4.0),
    EffectType.SPLIT_MIRROR: (0.6, 4.0),
    EffectType.TRIPTYCH: (0.6, 4.0),
    EffectType.WHIP_BLUR: (0.2, 0.5),
    EffectType.TEAR: (0.4, 1.2),
    EffectType.BW_FLASH: (0.2, 0.4),
    EffectType.HALFTONE_BG: (0.6, 4.0),
    EffectType.SPEED_LINES: (0.4, 2.0),
    EffectType.TILT: (0.6, 4.0),
}
#: Effects too loud for a reel on a sensitive subject; `motion qa` says so.
LOUD_EFFECTS = frozenset(
    {
        EffectType.TEAR,
        EffectType.BW_FLASH,
        EffectType.SPEED_LINES,
        EffectType.HALFTONE_BG,
        EffectType.WHIP_BLUR,
        EffectType.DEVICE_FRAME,
    }
)
#: Effects drawn over the picture without separating the person from the
#: background: there is no segmentation, so they are a translucent layer.
UNMASKED_EFFECTS = frozenset({EffectType.HALFTONE_BG, EffectType.SPEED_LINES})
#: No effect in the first second: the opening is the scene and the hook.
EFFECT_EARLIEST = 1.0


class Effect(Artifact):
    """One picture effect, e.g. a frame in frame on the turn of the argument."""

    type: EffectType
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    at_word: str | None = Field(default=None, max_length=60)
    occurrence: int = Field(default=1, ge=1)
    #: A tilt's angle in degrees; negative tilts left.
    tilt_deg: float | None = Field(default=None, ge=-5.0, le=5.0)
    reason: str = Field(min_length=1, max_length=300)

    @model_validator(mode="before")
    @classmethod
    def _tilt_default(cls, data):
        if isinstance(data, dict) and data.get("type") in ("tilt", EffectType.TILT):
            data = {"tilt_deg": 4.0, **data}
        return data

    @model_validator(mode="after")
    def _valid(self) -> Effect:
        low, high = EFFECT_LENGTHS[self.type]
        length = self.end - self.start
        if not low - 1e-6 <= length <= high + 1e-6:
            raise ValueError(f"a {self.type.value} lasts {low:g}-{high:g} s, not {length:.2f} s")
        if self.start < EFFECT_EARLIEST:
            raise ValueError(
                f"a {self.type.value} never touches the opening: start at "
                f"{EFFECT_EARLIEST:g} s or later"
            )
        if self.type is EffectType.TILT:
            if self.tilt_deg is None or abs(self.tilt_deg) < 2.0:
                raise ValueError("a tilt is 2-5 degrees either way; less reads as a mistake")
        elif self.tilt_deg is not None:
            raise ValueError("tilt_deg is only used by a tilt")
        return self


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
    #: Anchor the push to a spoken word, as a shake is: its start becomes the
    #: start of that word's ``occurrence``-th appearance in the captions.
    at_word: str | None = Field(default=None, max_length=60)
    occurrence: int = Field(default=1, ge=1)
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
    #: Picture effects (frame in frame, tear, flash...), drawn by Remotion.
    effects: list[Effect] = Field(default_factory=list)
    #: The reel is about death, illness or grief: no playful graphic
    #: (stickers, strikes and the other word graphics) may appear in it.
    sensitive_topic: bool = False
    rationale: str = Field(min_length=1, max_length=800)

    @model_validator(mode="after")
    def _restraint_on_a_sensitive_topic(self) -> MotionPlan:
        if self.sensitive_topic:
            playful = sorted({e.type.value for e in self.elements if e.type in PLAYFUL})
            if playful:
                raise ValueError(
                    "a reel on a sensitive topic takes no playful graphics; remove "
                    + ", ".join(playful)
                )
        return self

    @model_validator(mode="after")
    def _one_title_each(self) -> MotionPlan:
        for kind in (MotionElementType.HOOK_TITLE, MotionElementType.END_TEASER):
            count = sum(1 for e in self.elements if e.type is kind)
            if count > 1:
                raise ValueError(f"a reel has one {kind.value}; this plan has {count}")
        return self

    @model_validator(mode="after")
    def _effects_one_at_a_time(self) -> MotionPlan:
        ordered = sorted(self.effects, key=lambda e: e.start)
        for first, second in pairwise(ordered):
            if second.start < first.end - 1e-6:
                raise ValueError(
                    f"effects at {first.start:.2f}s and {second.start:.2f}s overlap; "
                    "one effect at a time"
                )
        titles = [e for e in self.elements if e.type is MotionElementType.HOOK_TITLE]
        for effect in ordered:
            for title in titles:
                if effect.start < title.end and title.start < effect.end:
                    raise ValueError(
                        f"the {effect.type.value} at {effect.start:.2f}s runs under the "
                        "hook_title; the title is read on a still picture"
                    )
        return self

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
    #: "Zamiast X powiedz Y": the habit crossed out and replaced (a strike).
    REPLACEMENT = "replacement"
    #: A line someone said, quoted: a speech bubble on it.
    QUOTE = "quote"
    #: "Najpierw..., potem..., na końcu...": a process bar of the stages.
    SEQUENCE = "sequence"
    #: A word the project's icon dictionary lists: its icon over the head.
    ICON = "icon"
    #: A sentence boundary where the picture may change (`motion_effects: auto`).
    EFFECT = "effect"
    #: A word of the project's `punch_in_words`: a push in on it.
    WORD_PUNCH = "word_punch"
    #: A word a prop in the project's library answers to.
    PROP = "prop"


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
    effect: Effect | None = None

    @model_validator(mode="after")
    def _one_move(self) -> AccentCandidate:
        moves = [
            m
            for m in (
                self.element, self.punch_in, self.transition, self.range_zoom, self.range_start,
                self.effect,
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
