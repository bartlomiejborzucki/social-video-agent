"""Lay captions out so the full text is drawn, or fail -- never truncate.

The Remotion compositor used to clamp captions with ``-webkit-line-clamp`` and
``overflow: hidden``. That pair is a UI affordance for shortening a label: it
hides what does not fit and appends an ellipsis. At 5% of a 1920-pixel frame a
96-pixel caption is wider than a 9:16 frame for any ordinary Polish phrase, so
``nikomu, udowadniając na siłę`` lost its last words and gained a ``...`` the
speaker never said. A subtitle is a transcript. Shortening one silently is a
correctness bug, not a layout preference.

Layout is therefore decided here rather than by the browser:

* it is measurable in a unit test, with no headless Chrome involved;
* the compositor is handed explicit lines and needs no wrapping, clamping or
  ellipsis rule of its own;
* QA can compare the measured geometry against the contract.

What happens when a cue does not fit, in order:

1. wrap it at word boundaries across the contracted ``max_lines``;
2. shrink that one cue's font, down to :data:`SHRINK_FLOOR` of the contracted
   size, which keeps it recognisably the same caption;
3. raise. Nothing is ever removed from the text.

Splitting a long cue into several cues happens earlier and elsewhere:
:mod:`social_video.captions.chunk` breaks on word and clause boundaries using
the contract's ``max_words_per_cue`` and ``max_chars_per_cue``. By the time a
cue reaches this module the sentence has already been divided editorially; all
that is left is fitting it into the box.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from social_video.errors import ValidationError
from social_video.schemas.brand import CaptionStyle
from social_video.schemas.captions import CaptionCue, CaptionWord

#: Horizontal padding inside the caption background box, in pixels. Shipped to
#: the compositor with the layout so the measured box is the drawn box.
BOX_PADDING_X = 25
#: Top and bottom padding inside the background box, in pixels.
BOX_PADDING_TOP = 14
BOX_PADDING_BOTTOM = 17
#: Line height as a multiple of the font size, matching the compositor.
LINE_HEIGHT = 1.12
#: A cue may shrink to this fraction of the contracted size, no further. Below
#: it the caption stops looking like the brand asked for and starts looking
#: like an accident.
SHRINK_FLOOR = 0.72
#: Measured width must stay inside this fraction of the box. Chrome's kerning is
#: not bit-identical to FreeType's advance sum, so the last few pixels are not
#: ours to spend.
WIDTH_SAFETY = 0.97
#: Fallback mean glyph advance as a fraction of the em, used only when the real
#: font cannot be measured. Deliberately wide: over-estimating costs a slightly
#: smaller caption, under-estimating costs clipped text.
ESTIMATED_ADVANCE_EM = 0.58
#: Smallest caption anyone would call legible on a phone, in pixels.
MIN_FONT_PX = 8


def necessary_line_width_px(*, chars: int, max_lines: int, font_px: float) -> float:
    """Width the widest line needs when a cue of ``chars`` wraps as evenly as possible.

    Used to sanity-check a contract before any text exists, so this is a
    *necessary* condition rather than a sufficient one: if even an even split
    does not fit, no wrapping of any sentence at that length can. Real text is
    measured against the real font at layout time.
    """
    per_line = math.ceil(chars / max(1, max_lines))
    return per_line * font_px * ESTIMATED_ADVANCE_EM


def contract_fit_error(
    *,
    font_size_pct: float,
    max_chars_per_cue: int,
    max_lines: int,
    boxed: bool,
    width: int,
    height: int,
    horizontal_margin_pct: float,
) -> str | None:
    """Why this caption geometry cannot work at this resolution, or None."""
    font_px = max(MIN_FONT_PX, height * font_size_pct / 100)
    available = width * (1.0 - horizontal_margin_pct / 100.0) - (2 * BOX_PADDING_X if boxed else 0)
    needed = necessary_line_width_px(chars=max_chars_per_cue, max_lines=max_lines, font_px=font_px)
    if needed <= available * WIDTH_SAFETY:
        return None
    return (
        f"caption_style cannot fit its own text: at font_size_pct={font_size_pct} "
        f"({font_px:.0f} px of a {height}px frame) a {max_chars_per_cue}-character cue needs "
        f"about {needed:.0f} px on its widest line across {max_lines} line(s), but only "
        f"{available:.0f} px is available at {width}x{height} with the configured safe "
        f"margins. Captions are never truncated to fit, so this has to be resolved in the "
        f"contract: lower font_size_pct (3.6 is the reference for 9:16), lower "
        f"max_chars_per_cue (24 is the reference), raise max_lines, or reduce the safe margins."
    )


class CaptionOverflowError(ValidationError):
    """A cue cannot be drawn in full, and truncating it is not an option."""


@dataclass(frozen=True)
class CaptionLine:
    """One drawn line: its text, its measured width, and its word timings."""

    text: str
    width_px: float
    words: tuple[CaptionWord, ...] = ()

    def payload(self, *, with_words: bool) -> dict:
        item: dict = {"text": self.text, "width_px": round(self.width_px, 2)}
        if with_words:
            item["words"] = [
                {"text": word.text, "start": word.start, "end": word.end} for word in self.words
            ]
        return item


#: Characters that shorten a sentence when a layout engine adds them. Kept as
#: evidence rather than as a policy: a speaker may genuinely trail off, and an
#: ellipsis the transcript already had must survive.
ELLIPSIS_MARKS = ("\u2026", "...")


@dataclass(frozen=True)
class CueLayout:
    index: int
    font_size_px: int
    lines: tuple[CaptionLine, ...]
    #: The cue text this was laid out from, so the drawn result can be compared
    #: against its own input instead of against the layout's intent.
    source_text: str = ""

    @property
    def text(self) -> str:
        return " ".join(line.text for line in self.lines)

    @property
    def complete(self) -> bool:
        """Whether the drawn lines reproduce the cue, word for word."""
        return self.text.split() == self.source_text.split()

    @property
    def added_ellipsis(self) -> bool:
        drawn, source = self.text.rstrip(), self.source_text.rstrip()
        return any(drawn.endswith(mark) and not source.endswith(mark) for mark in ELLIPSIS_MARKS)

    @property
    def max_line_width_px(self) -> float:
        return max((line.width_px for line in self.lines), default=0.0)


@dataclass(frozen=True)
class CaptionLayout:
    """Every cue's drawn geometry, plus the evidence QA checks."""

    cues: tuple[CueLayout, ...]
    box_width_px: float
    text_width_px: float
    requested_font_size_px: int
    measured: bool
    #: The contract's cue-length limit, so the evidence can name cues that a
    #: split would have shortened.
    max_chars_allowed: int = 0
    padding_x: int = BOX_PADDING_X
    padding_top: int = BOX_PADDING_TOP
    padding_bottom: int = BOX_PADDING_BOTTOM
    line_height: float = LINE_HEIGHT

    @property
    def shrunk_cues(self) -> tuple[int, ...]:
        return tuple(
            cue.index for cue in self.cues if cue.font_size_px < self.requested_font_size_px
        )

    @property
    def truncated_cues(self) -> tuple[int, ...]:
        return tuple(cue.index for cue in self.cues if not cue.complete)

    @property
    def ellipsis_cues(self) -> tuple[int, ...]:
        return tuple(cue.index for cue in self.cues if cue.added_ellipsis)

    @property
    def over_length_cues(self) -> tuple[int, ...]:
        """Cues longer than the contract allows that a word split could fix.

        A single word longer than the limit is not a defect -- nothing can be
        done about ``odpowiedzialność`` except draw it -- so only multi-word
        cues count. Those mean the cue was never split, which is the step that
        is supposed to happen before layout.
        """
        if self.max_chars_allowed <= 0:
            return ()
        return tuple(
            cue.index
            for cue in self.cues
            if len(cue.source_text) > self.max_chars_allowed and len(cue.source_text.split()) > 1
        )

    @property
    def max_line_width_px(self) -> float:
        return max((cue.max_line_width_px for cue in self.cues), default=0.0)

    @property
    def min_font_size_px(self) -> int:
        return min((cue.font_size_px for cue in self.cues), default=self.requested_font_size_px)

    @property
    def max_chars_per_cue(self) -> int:
        return max((len(cue.text) for cue in self.cues), default=0)

    def evidence(self) -> dict[str, float | int | bool | list[int]]:
        """What the renderer reports having drawn, for brand QA."""
        return {
            "text_box_width_px": round(self.text_width_px, 2),
            "max_line_width_px": round(self.max_line_width_px, 2),
            "requested_font_size_px": self.requested_font_size_px,
            "min_font_size_px": self.min_font_size_px,
            "max_chars_per_cue": self.max_chars_per_cue,
            "shrunk_cues": list(self.shrunk_cues),
            # Measured against each cue's own input text, so QA checks evidence
            # rather than trusting this module's intent.
            "truncated_cues": list(self.truncated_cues),
            "ellipsis_cues": list(self.ellipsis_cues),
            "over_length_cues": list(self.over_length_cues),
            "max_chars_allowed": self.max_chars_allowed,
            "font_measured": self.measured,
        }


def font_size_px(style: CaptionStyle, height: int) -> int:
    return max(MIN_FONT_PX, round(height * style.font_size_pct / 100))


def text_box_width_px(
    style: CaptionStyle, width: int, safe_margins: dict[str, float] | None
) -> float:
    """Pixels available for glyphs, after safe margins and box padding."""
    margins = safe_margins or {}
    left = float(margins.get("left", 6.0))
    right = float(margins.get("right", 6.0))
    inner = width * (1.0 - (left + right) / 100.0)
    if style.background_style.value != "none":
        inner -= 2 * BOX_PADDING_X
    return max(1.0, inner)


def layout_captions(
    cues: list[CaptionCue],
    style: CaptionStyle,
    *,
    width: int,
    height: int,
    safe_margins: dict[str, float] | None = None,
    font_file: str | Path | None = None,
) -> CaptionLayout:
    """Wrap, and if necessary shrink, every cue. Raise rather than truncate."""
    requested = font_size_px(style, height)
    text_width = text_box_width_px(style, width, safe_margins)
    budget = text_width * WIDTH_SAFETY
    measurer = _measurer(font_file)
    floor = max(MIN_FONT_PX, int(requested * SHRINK_FLOOR))
    laid_out: list[CueLayout] = []
    for cue in cues:
        lines = None
        size = requested
        for candidate in range(requested, floor - 1, -1):
            lines = _wrap(cue, style, measurer, size_px=candidate, budget=budget)
            if lines is not None:
                size = candidate
                break
        if lines is None:
            raise CaptionOverflowError(_overflow_message(cue, style, requested, floor, text_width))
        laid_out.append(
            CueLayout(
                index=cue.index,
                font_size_px=size,
                lines=tuple(lines),
                source_text=cue.text,
            )
        )
    return CaptionLayout(
        cues=tuple(laid_out),
        box_width_px=text_width
        + (2 * BOX_PADDING_X if style.background_style.value != "none" else 0),
        text_width_px=text_width,
        requested_font_size_px=requested,
        measured=measurer.measured,
        max_chars_allowed=style.max_chars_per_cue,
    )


def _wrap(
    cue: CaptionCue,
    style: CaptionStyle,
    measurer: _Measurer,
    *,
    size_px: int,
    budget: float,
) -> list[CaptionLine] | None:
    """Greedy word wrap. None means it does not fit in ``max_lines``."""
    words = _cue_words(cue)
    lines: list[CaptionLine] = []
    current: list[CaptionWord] = []
    for word in words:
        candidate = [*current, word]
        width = measurer.width(" ".join(item.text for item in candidate), size_px)
        if width <= budget:
            current = candidate
            continue
        if not current:
            # A single word wider than the box: wrapping cannot help, only a
            # smaller size can. Never break a word across lines -- a hyphen
            # nobody spoke is the same defect as an ellipsis nobody spoke.
            return None
        lines.append(_line(current, measurer, size_px))
        current = [word]
    if current:
        lines.append(_line(current, measurer, size_px))
    if not lines or len(lines) > style.max_lines:
        return None
    return lines


def _line(words: list[CaptionWord], measurer: _Measurer, size_px: int) -> CaptionLine:
    text = " ".join(word.text for word in words)
    return CaptionLine(text=text, width_px=measurer.width(text, size_px), words=tuple(words))


def _cue_words(cue: CaptionCue) -> list[CaptionWord]:
    """Prefer word timings; fall back to the cue text split on whitespace.

    The cue's ``text`` is authoritative for what is drawn, because the caption
    case has already been applied to it. Word timings carry the original
    spelling, so they are only used for the highlight, re-cased to match.
    """
    pieces = cue.text.split()
    if cue.words and len(cue.words) == len(pieces):
        return [
            CaptionWord(text=piece, start=word.start, end=word.end)
            for piece, word in zip(pieces, cue.words, strict=True)
        ]
    span = max(cue.end - cue.start, 1e-6) / max(len(pieces), 1)
    return [
        CaptionWord(text=piece, start=cue.start + i * span, end=cue.start + (i + 1) * span)
        for i, piece in enumerate(pieces)
    ]


def _overflow_message(
    cue: CaptionCue,
    style: CaptionStyle,
    requested: int,
    floor: int,
    text_width: float,
) -> str:
    longest = max(cue.text.split(), key=len, default=cue.text)
    return (
        f"caption cue {cue.index} cannot be drawn in full: {cue.text!r} does not fit "
        f"{style.max_lines} line(s) of {text_width:.0f} px even at {floor} px, down from the "
        f"contracted {requested} px ({style.font_size_pct}% of frame height). The longest "
        f"word is {longest!r}. Truncating a subtitle is not an option, so fix the contract: "
        f"lower caption_style.font_size_pct, lower caption_style.max_chars_per_cue so the "
        f"sentence is split into more cues, raise caption_style.max_lines, or widen the "
        f"frame's safe margins."
    )


class _Measurer:
    """Glyph advance in pixels, from the real font when one is available."""

    def __init__(self, font_file: Path | None) -> None:
        self._font_file = font_file
        self.measured = font_file is not None and _loadable(font_file)

    def width(self, text: str, size_px: int) -> float:
        if self.measured and self._font_file is not None:
            face = _face(self._font_file, size_px)
            if face is not None:
                return float(face.getlength(text))
        return len(text) * size_px * ESTIMATED_ADVANCE_EM


def _measurer(font_file: str | Path | None) -> _Measurer:
    path = Path(font_file).expanduser() if font_file else None
    return _Measurer(path if path is not None and path.is_file() else None)


def _loadable(font_file: Path) -> bool:
    return _face(font_file, 32) is not None


@lru_cache(maxsize=64)
def _face(font_file: Path, size_px: int):
    """Cached FreeType face. Returns None when the file cannot be measured."""
    try:
        from PIL import ImageFont

        return ImageFont.truetype(str(font_file), size=max(MIN_FONT_PX, size_px))
    except (OSError, ImportError):
        return None
