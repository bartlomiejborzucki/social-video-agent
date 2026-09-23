"""Brand keywords drawn in their own colour wherever they are spoken.

Matching is on the word itself: case-folded, with punctuation stripped from
its edges, so ``Studio,`` and ``STUDIO`` both match ``studio``. It is exact after
that. Inflected forms are separate words -- a Polish project that wants
``Studia`` emphasised as well as ``Studio`` lists both -- because guessing at
stems would colour words nobody chose.
"""

from __future__ import annotations

import unicodedata


def normalise(word: str) -> str:
    """The comparable form of one spoken or configured word."""
    start, end = 0, len(word)
    while start < end and unicodedata.category(word[start]).startswith("P"):
        start += 1
    while end > start and unicodedata.category(word[end - 1]).startswith("P"):
        end -= 1
    return word[start:end].casefold()


def emphasis_keys(words: list[str]) -> frozenset[str]:
    return frozenset(key for key in (normalise(word) for word in words) if key)


def is_emphasised(word: str, keys: frozenset[str]) -> bool:
    return bool(keys) and normalise(word) in keys
