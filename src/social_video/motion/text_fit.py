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
from itertools import pairwise
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
    balanced: bool = False,
) -> FittedText:
    """The largest size at most ``base_px`` at which every word fits whole.

    Never returns a split word. Below ``min_px`` it raises: a card the size
    of a footnote is a design problem to solve, not to shrink into.

    ``balanced`` evens the lines out at the size found, in as many lines as
    the text needed anyway: a heading does not end on one stranded word.
    """
    measure = text_measurer(font_file)
    paragraphs = [p.split() for p in text.split("\n")]
    size = base_px
    while size >= min_px:
        lines = _wrap(paragraphs, measure, size, max_width)
        if lines is not None and (max_lines is None or len(lines) <= max_lines):
            if balanced:
                lines = _balance(paragraphs, measure, size, max_width, lines)
            return FittedText(size, lines, measure.measured)
        size -= 1
    longest = max((w for p in paragraphs for w in p), key=len, default="")
    raise ValueError(
        f"{text!r} does not fit {max_width:.0f}px at {min_px}px or larger"
        + (f" in {max_lines} line(s)" if max_lines else "")
        + f"; shorten it (longest unbreakable piece: {longest!r})"
    )


def fit_in_few_lines(
    text: str,
    *,
    max_width: float,
    base_px: int,
    floor_px: int,
    min_px: int,
    font_file: str | Path | None,
    max_lines: int,
) -> FittedText:
    """Like `fit_text`, but a line fewer is worth a somewhat smaller size.

    `fit_text` keeps the largest size and wraps to get it, which breaks a
    name in two for the sake of a few pixels. Here the text is tried in one
    line, then two, and so on, shrinking no further than ``floor_px`` for
    each; only the last allowed line count may go down to ``min_px``.
    """
    for allowed in range(1, max_lines + 1):
        try:
            return fit_text(
                text, max_width=max_width, base_px=base_px,
                min_px=min_px if allowed == max_lines else min(base_px, floor_px),
                font_file=font_file, max_lines=allowed, balanced=True,
            )  # fmt: skip
        except ValueError:
            if allowed == max_lines:
                raise
    raise AssertionError("unreachable: max_lines is at least 1")


def _balance(
    paragraphs: list[list[str]], measure, size: int, max_width: float, lines: list[str]
) -> list[str]:
    """The same number of lines, as even in width as the words allow.

    Each paragraph keeps the line count the plain wrap gave it; the breaks
    move to where the lines' widths differ least (the smallest sum of their
    squares), so the last line is not one stranded word.
    """
    balanced: list[str] = []
    for words in paragraphs:
        wrapped = _wrap([words], measure, size, max_width)
        count = len(wrapped) if wrapped is not None else 1
        if count < 2 or len(words) <= count:
            balanced.extend(wrapped or [" ".join(words)])
            continue
        balanced.extend(_even_lines(words, count, measure, size, max_width))
    return balanced if len(balanced) == len(lines) else lines


def _even_lines(words: list[str], count: int, measure, size: int, max_width: float) -> list[str]:
    total = len(words)
    widths = {
        (start, end): measure.width(" ".join(words[start:end]), size)
        for start in range(total)
        for end in range(start + 1, total + 1)
    }
    # best[lines][end]: the lowest cost of setting words[:end] in that many lines.
    unset = (float("inf"), 0)
    best = [[unset] * (total + 1) for _ in range(count + 1)]
    best[0][0] = (0.0, 0)
    for line in range(1, count + 1):
        for end in range(line, total + 1):
            for start in range(line - 1, end):
                width = widths[start, end]
                cost = best[line - 1][start][0] + width * width
                if width <= max_width and cost < best[line][end][0]:
                    best[line][end] = (cost, start)
    breaks = [total]
    for line in range(count, 0, -1):
        breaks.append(best[line][breaks[-1]][1])
    breaks.reverse()
    return [" ".join(words[a:b]) for a, b in pairwise(breaks)]


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
