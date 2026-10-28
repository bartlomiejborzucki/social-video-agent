"""Where the label, the call to action and the list sit on the frame.

Remotion draws these and libass draws the scene frame on the FFmpeg route, and
motion QA measures them. All three take their geometry from here, so the two
renderers lay a scene out the same way and QA measures what was drawn rather
than a guess. Every size is a fraction of the output height (``unit`` is one
pixel of a 1920-pixel frame), so a 720x1280 preview is the final, scaled.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import pairwise

from social_video.captions.fit import BOX_PADDING_BOTTOM, BOX_PADDING_TOP, LINE_HEIGHT
from social_video.schemas.brand import CaptionPosition, CaptionStyle
from social_video.schemas.edl import EDL
from social_video.schemas.motion import (
    ElementPosition,
    MotionElement,
    MotionElementType,
    MotionPlan,
)

#: Two labels this close are one scene continuing: the frame stays and the
#: title flips instead of the frame leaving and coming back.
CONTINUATION_S = 0.05
#: How long the title takes to flip over, in seconds.
FLIP_S = 0.5


def unit(height: int) -> float:
    """One pixel of a 1920-pixel-high frame, at this height."""
    return height / 1920.0


@dataclass(frozen=True)
class SceneFrameGeometry:
    """The scene frame in output pixels; the same for every cue of a scene."""

    left: float
    top: float
    width: float
    height: float
    radius: float
    border: float
    #: The title tab, centred on the frame's top edge.
    tab_font_px: float
    tab_pad_x: float
    tab_pad_y: float
    tab_border: float
    tab_dot: float
    tab_top: float
    tab_height: float
    #: Where a framed caption's box is centred, vertically.
    caption_centre: float

    @property
    def bottom(self) -> float:
        return self.top + self.height

    def as_props(self) -> dict[str, float]:
        return {key: round(value, 2) for key, value in asdict(self).items()}


def scene_frame_geometry(
    style: CaptionStyle,
    *,
    width: int,
    height: int,
    safe_margins: dict[str, float] | None = None,
) -> SceneFrameGeometry:
    """A frame around the caption band, sized for ``max_lines`` of captions."""
    u = unit(height)
    margins = safe_margins or {}
    font_px = height * style.font_size_pct / 100.0
    text = style.max_lines * font_px * LINE_HEIGHT + (BOX_PADDING_TOP + BOX_PADDING_BOTTOM) * u
    body = text + 0.06 * height
    inner = width * (1.0 - (margins.get("left", 6.0) + margins.get("right", 6.0)) / 100.0)
    frame_w = min(width * 0.96, max(width * 0.88, inner + 0.04 * width))
    if style.position is CaptionPosition.TOP:
        top = height * style.margin_pct / 100.0 - 0.021 * height
    elif style.position is CaptionPosition.CENTER:
        top = (height - body) / 2
    else:
        top = height - height * style.margin_pct / 100.0 + 0.021 * height - body
    tab_font = 42 * u
    tab_pad_y = 10 * u
    tab_border = 5 * u
    tab_height = tab_font * 1.15 + 2 * tab_pad_y + 2 * tab_border
    return SceneFrameGeometry(
        left=(width - frame_w) / 2,
        top=top,
        width=frame_w,
        height=body,
        radius=34 * u,
        border=5 * u,
        tab_font_px=tab_font,
        tab_pad_x=30 * u,
        tab_pad_y=tab_pad_y,
        tab_border=tab_border,
        tab_dot=16 * u,
        tab_top=top - tab_height / 2,
        tab_height=tab_height,
        caption_centre=top + body / 2 + 14 * u,
    )


#: A title may shrink this far before it has to be shortened instead.
TAB_MIN_SCALE = 0.6
#: The tab's text is bold; the brand font file measured is usually regular.
BOLD_ALLOWANCE = 1.06
#: Share of the frame's width the tab may take.
TAB_WIDTH_SHARE = 0.94


def tab_width(text: str, font_px: float, g: SceneFrameGeometry, measure) -> float:
    """Width of the title tab drawing ``text`` at ``font_px``, padding included."""
    upper = text.upper()
    spacing = font_px * 0.07
    text_w = measure.width(upper, round(font_px)) * BOLD_ALLOWANCE
    text_w += spacing * max(0, len(upper) - 1)
    return text_w + 2 * g.tab_dot + 2 * g.tab_pad_x + 2 * g.tab_border


def tab_font_px(text: str, g: SceneFrameGeometry, font_file=None) -> float:
    """The tab's font size for this title: the frame's own, or smaller to fit.

    The limit is the frame's width, not a number of characters: "Przykład
    reakcji: na hasło przerywam zabawę" has 43 characters and did not fit. A
    title that would have to shrink below TAB_MIN_SCALE is refused with the
    length that fits, since unreadably small type is worse than a shorter title.
    """
    from social_video.captions.fit import text_measurer

    measure = text_measurer(font_file)
    limit = g.width * TAB_WIDTH_SHARE
    size = g.tab_font_px
    if tab_width(text, size, g, measure) <= limit:
        return size
    floor = g.tab_font_px * TAB_MIN_SCALE
    while size > floor and tab_width(text, size, g, measure) > limit:
        size -= 0.5
    if tab_width(text, size, g, measure) > limit:
        per_char = tab_width(text, floor, g, measure) / max(1, len(text))
        fits = int((limit - 2 * g.tab_dot - 2 * g.tab_pad_x) / per_char)
        raise ValueError(
            f"label {text!r} does not fit the scene frame's title tab "
            f"({g.width * TAB_WIDTH_SHARE:.0f}px) even at {TAB_MIN_SCALE:.0%} size; "
            f"shorten it to about {fits} characters"
        )
    return round(size, 1)


def labels(elements: list[MotionElement]) -> list[MotionElement]:
    return sorted((e for e in elements if e.type is MotionElementType.LABEL), key=lambda e: e.start)


def continues(label: MotionElement, elements: list[MotionElement]) -> MotionElement | None:
    """The label this one takes over from without a break, if any."""
    for other in labels(elements):
        if other is not label and abs(other.end - label.start) < CONTINUATION_S:
            return other
    return None


def framing_label(start: float, end: float, elements: list[MotionElement]) -> MotionElement | None:
    """The label whose frame holds a cue: the one its midpoint falls inside."""
    middle = (start + end) / 2
    for label in labels(elements):
        if label.start <= middle < label.end:
            return label
    return None


def element_band(
    element: MotionElement,
    *,
    height: int,
    margins: dict[str, float],
    label_style: str = "chip",
    frame: SceneFrameGeometry | None = None,
) -> tuple[float, float] | None:
    """The vertical extent of a placed element, as fractions of the frame height.

    ``None`` when the element has no fixed place this module knows; motion QA
    then falls back to its table of the 1.0 bands.
    """
    u = unit(height)
    top = margins.get("top", 6.0) / 100.0 * height
    bottom = margins.get("bottom", 6.0) / 100.0 * height
    kind = element.type
    if kind is MotionElementType.LABEL:
        if label_style == "scene_frame" and frame is not None:
            return frame.tab_top / height, frame.bottom / height
        return top / height, (top + (34 * 1.15 + 24) * u) / height
    placement = element.placement
    if kind is MotionElementType.CTA:
        if placement is ElementPosition.TOP:
            start = top + 20 * u
            return start / height, (start + (62 * 1.15 + 36 + 10) * u) / height
        # The 1.0 pill: 46 px type, 20 px padding, its own size at any height.
        low = height - bottom - 0.16 * height
        return (low - (46 * 1.15 + 40)) / height, low / height
    if kind in (MotionElementType.LIST, MotionElementType.STEPS):
        rows = max(1, len(element.items))
        card = rows * (56 * 1.18 + 24) * u + 56 * u
        if placement is ElementPosition.TOP:
            start = top + 10 * u
            return start / height, (start + card) / height
        return None
    if kind is MotionElementType.STRIKE:
        # Two lines of 50 px type at most, with the card's padding.
        card = (2 * 50 * 1.2 + 2 * 26 + 8) * u
        if placement is ElementPosition.TOP:
            start = top + 10 * u
            return start / height, (start + card) / height
        return (height - card) / 2 / height, (height + card) / 2 / height
    return None


#: How far a label edge may move to meet a cut. Further than this, the label
#: was meant to change mid-range and keeps its own time.
PIN_REACH_S = 1.5


def pin_labels(elements: list[MotionElement], edl: EDL) -> tuple[list[MotionElement], list[str]]:
    """Move each label onto the scene it names, in the compiled edit.

    A brief times its labels against the script ("3-9 s"); the edit's scenes
    land elsewhere. A label whose text is a range's ``beat`` spans exactly
    those ranges. Any other label edge moves to the nearest cut within
    ``PIN_REACH_S``. Labels that then meet, or nearly do, are joined, so the
    frame stays and only its title flips. Returns the elements and one line per
    label that moved.
    """
    from social_video.edl.timeline import Timeline

    timeline = Timeline(edl)
    total = timeline.duration
    cuts = [0.0, *(s.output_start for s in timeline.slices[1:]), total]

    def nearest(moment: float) -> float:
        best = min(cuts, key=lambda c: abs(c - moment))
        return best if abs(best - moment) <= PIN_REACH_S else moment

    pinned: dict[int, tuple[float, float, str]] = {}
    for label in labels(elements):
        key = label.text.strip().casefold()
        scene = [s for s in timeline.slices if s.range.beat.strip().casefold() == key]
        if scene:
            start, end = scene[0].output_start, scene[-1].output_end
            why = f"the scene with beat {label.text!r}"
        else:
            start, end = nearest(label.start), nearest(min(label.end, total))
            why = "the nearest cuts"
        end = min(end, total)
        if end - start < 0.5:
            start, end = label.start, min(label.end, total)
            why = "its own time; no scene fits"
        pinned[id(label)] = (round(start, 3), round(end, 3), why)

    ordered = sorted(pinned.items(), key=lambda p: p[1][0])
    for (first, (s1, e1, w1)), (_second, (s2, _e2, _w2)) in pairwise(ordered):
        if abs(s2 - e1) < 0.3 or e1 > s2:
            pinned[first] = (s1, s2, w1)

    result: list[MotionElement] = []
    notes: list[str] = []
    for element in elements:
        if id(element) not in pinned:
            result.append(element)
            continue
        start, end, why = pinned[id(element)]
        if abs(start - element.start) > 1e-3 or abs(end - element.end) > 1e-3:
            notes.append(
                f"label {element.text!r} {element.start:.2f}-{element.end:.2f} s -> "
                f"{start:.2f}-{end:.2f} s ({why})"
            )
        result.append(element.model_copy(update={"start": start, "end": end}))
    return result, notes


def held_end_card(plan: MotionPlan, edl: EDL) -> tuple[EDL, MotionPlan, str | None]:
    """Extend the edit for an end card held after the last word, and place it there.

    The card keeps its length (end - start) and starts where the last range
    ends; the EDL holds that long in silence, so the card never covers the
    last spoken seconds and lasts to the final frame. Returns what moved.
    """
    from social_video.edl.timeline import Timeline

    held = [e for e in plan.elements if e.type is MotionElementType.END_CARD and e.hold]
    if len(held) > 1:
        raise ValueError("only one end_card can be held after the last word")
    if not held:
        if edl.end_hold == 0:
            return edl, plan, None
        return edl.model_copy(update={"end_hold": 0.0}), plan, "end hold removed: no held end_card"
    card = held[0]
    length = round(card.end - card.start, 3)
    content_end = round(Timeline(edl).content_end, 3)
    if abs(edl.end_hold - length) < 1e-3 and abs(card.start - content_end) < 1e-3:
        return edl, plan, None
    moved = card.model_copy(update={"start": content_end, "end": round(content_end + length, 3)})
    elements = [moved if e is card else e for e in plan.elements]
    new_plan = MotionPlan.model_validate(
        plan.model_copy(update={"elements": sorted(elements, key=lambda e: e.start)}).model_dump()
    )
    new_edl = EDL.model_validate(edl.model_copy(update={"end_hold": length}).model_dump())
    return (
        new_edl,
        new_plan,
        (
            f"end_card held {length:.2f}s after the last word, "
            f"{content_end:.2f}-{content_end + length:.2f}s"
        ),
    )
