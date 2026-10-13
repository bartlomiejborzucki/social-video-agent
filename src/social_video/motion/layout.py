"""Where the label, the call to action and the list sit on the frame.

Remotion draws these and libass draws the scene frame on the FFmpeg route, and
motion QA measures them. All three take their geometry from here, so the two
renderers lay a scene out the same way and QA measures what was drawn rather
than a guess. Every size is a fraction of the output height (``unit`` is one
pixel of a 1920-pixel frame), so a 720x1280 preview is the final, scaled.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from social_video.captions.fit import BOX_PADDING_BOTTOM, BOX_PADDING_TOP, LINE_HEIGHT
from social_video.schemas.brand import CaptionPosition, CaptionStyle
from social_video.schemas.motion import ElementPosition, MotionElement, MotionElementType

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
    return None

