"""Fitting a card's words to the frame without ever breaking an address.

The compositor draws lines it is given; it does not wrap. Wrapping in the
browser broke ``przyklad-marki.example/strona-z-zapisami`` after the hyphen, so
a viewer saw half a link. Here a link, an e-mail address or any single word is
never split: the font shrinks until the longest of them fits the width, and
lines break only between words. ``\\n`` in the text starts a new line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from social_video.captions.fit import text_measurer

#: A link or an address: scheme, www., a domain with a path, or an e-mail.
_ADDRESS = re.compile(
    r"^(?:https?://|www\.)\S+$|^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$|^[\w-]+(?:\.[\w-]+)+(?:/\S*)?$",
    re.IGNORECASE,
)


def is_address(token: str) -> bool:
    """A URL, domain or e-mail address: drawn whole on one line, always."""
    return bool(_ADDRESS.match(token.strip(".,;:!?()\"'")))


@dataclass(frozen=True)
class FittedText:
    font_px: int
    lines: list[str]
    measured: bool

    def payload(self) -> dict:
        return {"font_px": self.font_px, "lines": self.lines}


def fit_text(
    text: str,
    *,
    max_width: float,
    base_px: int,
    min_px: int,
    font_file: str | Path | None,
    max_lines: int | None = None,
) -> FittedText:
    """The largest size at most ``base_px`` at which every word fits whole.

    Never returns a split word. Below ``min_px`` it raises: a card the size
    of a footnote is a design problem to solve, not to shrink into.
    """
    measure = text_measurer(font_file)
    paragraphs = [p.split() for p in text.split("\n")]
    size = base_px
    while size >= min_px:
        lines = _wrap(paragraphs, measure, size, max_width)
        if lines is not None and (max_lines is None or len(lines) <= max_lines):
            return FittedText(size, lines, measure.measured)
        size -= 1
    longest = max((w for p in paragraphs for w in p), key=len, default="")
    raise ValueError(
        f"{text!r} does not fit {max_width:.0f}px at {min_px}px or larger"
        + (f" in {max_lines} line(s)" if max_lines else "")
        + f"; shorten it (longest unbreakable piece: {longest!r})"
    )


def _wrap(paragraphs: list[list[str]], measure, size: int, max_width: float) -> list[str] | None:
    lines: list[str] = []
    for words in paragraphs:
        current = ""
        for word in words:
            if measure.width(word, size) > max_width:
                return None
            candidate = f"{current} {word}" if current else word
            if current and measure.width(candidate, size) > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
    return lines
