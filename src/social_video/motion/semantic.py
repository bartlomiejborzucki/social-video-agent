"""The Polish words that mark a semantic accent, from a data file a project may edit.

`motion suggest` looks for three shapes of speech beyond its counting and
punching: a habit replaced ("zamiast X powiedz Y", "nie mów X", "lepiej: Y")
becomes a `strike`, a quoted line ("mówi: …") a `bubble`, and a sequence
("najpierw… potem… na końcu") a `process`. The words that mark them live in
`motion/data/accents_pl.yaml`; a project replaces any category with
`.social-video/accent-words.yaml` in its own root, as it does the hook words.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

WORDS_FILE = Path(__file__).with_name("data") / "accents_pl.yaml"
PROJECT_WORDS = Path(".social-video") / "accent-words.yaml"
CATEGORIES = (
    "replace_from",
    "replace_with",
    "quote_verbs",
    "sequence_first",
    "sequence_then",
    "sequence_last",
)


@dataclass(frozen=True)
class AccentWords:
    """Each category as phrases of whole, normalised words."""

    replace_from: tuple[tuple[str, ...], ...] = ()
    replace_with: tuple[tuple[str, ...], ...] = ()
    quote_verbs: tuple[tuple[str, ...], ...] = ()
    sequence_first: tuple[tuple[str, ...], ...] = ()
    sequence_then: tuple[tuple[str, ...], ...] = ()
    sequence_last: tuple[tuple[str, ...], ...] = ()


def _phrases(values) -> tuple[tuple[str, ...], ...]:
    from social_video.captions.emphasis import normalise

    found = []
    for value in values or []:
        words = tuple(w for w in (normalise(part) for part in str(value).split()) if w)
        if words:
            found.append(words)
    # The longest phrase first, so "a potem" wins over "potem".
    return tuple(sorted(found, key=len, reverse=True))


def _read(path: Path) -> dict[str, list[str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping of categories to word lists")
    if unknown := set(data) - set(CATEGORIES):
        raise ValueError(f"{path}: unknown categories {', '.join(sorted(unknown))}")
    return data


def load_accent_words(project_root: Path | None = None) -> AccentWords:
    """The general lists, with every category the project defines replaced."""
    data = _read(WORDS_FILE)
    if project_root is not None and (project_root / PROJECT_WORDS).is_file():
        data |= _read(project_root / PROJECT_WORDS)
    return AccentWords(**{name: _phrases(data.get(name)) for name in CATEGORIES})
