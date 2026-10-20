"""Stickers and shakes: a reaction on one word, placed by the words themselves.

A sticker (an emoji or a small project image) and a shake of the picture
both answer a word -- "Zgodziłeś!" -- so they are anchored to it: `at_word`
names the word and `occurrence` which time it is said, and the start is
taken from the caption track, which is on the output timeline. Moving a cut
then moves the reaction with the word instead of leaving it behind.

The rules the brand set are checked here, before anything is drawn: how
many stickers the energy level allows, never in the opening frame, never on
the end card, and only the emoji the project lists. An emoji is drawn only
from Noto Color Emoji, whose SIL Open Font License permits commercial use;
which font and licence drew it is recorded in the render manifest.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from social_video.schemas.captions import CaptionTrack
from social_video.schemas.motion import (
    STICKER_EARLIEST,
    STICKER_LIMIT,
    MotionElementType,
    MotionPlan,
)

EMOJI_FAMILY = "Noto Color Emoji"
EMOJI_LICENSE = "SIL Open Font License 1.1"
EMOJI_SOURCE = "https://github.com/googlefonts/noto-emoji"


@dataclass(frozen=True)
class EmojiFont:
    path: Path
    family: str = EMOJI_FAMILY
    license: str = EMOJI_LICENSE
    source: str = EMOJI_SOURCE

    def evidence(self, emoji: str) -> dict[str, str]:
        return {
            "emoji": emoji,
            "font": self.family,
            "font_file": str(self.path),
            "license": self.license,
            "source": self.source,
        }


def emoji_font() -> EmojiFont | None:
    """The installed Noto Color Emoji, or None. No other emoji font is used."""
    fc_match = shutil.which("fc-match")
    if fc_match is None:
        return None
    proc = subprocess.run(
        [fc_match, "-f", "%{family}\n%{file}", EMOJI_FAMILY],
        capture_output=True,
        text=True,
        check=False,
    )
    family, _, file = proc.stdout.partition("\n")
    path = Path(file.strip())
    if family.split(",")[0].strip() != EMOJI_FAMILY or not path.is_file():
        return None
    return EmojiFont(path)


def word_key(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def word_times(captions: CaptionTrack) -> list[tuple[str, float, float]]:
    """Every captioned word with its output time, in order."""
    found = []
    for cue in captions.cues:
        for word in cue.words:
            found.append((word_key(word.text), word.start, word.end))
    return sorted(found, key=lambda item: item[1])


def anchor_to_words(
    plan: MotionPlan, captions: CaptionTrack | None
) -> tuple[MotionPlan, list[str]]:
    """Move every sticker and shake with `at_word` onto that word. Says what moved.

    The length of each is kept. A word the captions do not hold is an error:
    a reaction to a word nobody says would land on nothing.
    """
    anchored = [e for e in plan.elements if e.type is MotionElementType.STICKER and e.at_word]
    shakes = [s for s in plan.shakes if s.at_word]
    if not anchored and not shakes:
        return plan, []
    if captions is None:
        raise ValueError("stickers and shakes anchored with at_word need the caption track")
    words = word_times(captions)
    notes: list[str] = []

    def find(word: str, occurrence: int) -> float:
        key = word_key(word)
        hits = [start for text, start, _end in words if text == key]
        if len(hits) < occurrence:
            raise ValueError(
                f"at_word {word!r} is said {len(hits)} time(s) in the captions; "
                f"occurrence {occurrence} does not exist"
            )
        return round(hits[occurrence - 1], 3)

    elements = []
    for element in plan.elements:
        if element in anchored:
            assert element.at_word is not None
            start = find(element.at_word, element.occurrence)
            length = element.end - element.start
            if abs(start - element.start) > 1e-3:
                notes.append(f"sticker on {element.at_word!r} placed at {start:.2f}s")
            element = element.model_copy(update={"start": start, "end": round(start + length, 3)})
        elements.append(element)
    moved_shakes = []
    for shake in plan.shakes:
        if shake.at_word:
            start = find(shake.at_word, shake.occurrence)
            length = shake.end - shake.start
            if abs(start - shake.start) > 1e-3:
                notes.append(f"shake on {shake.at_word!r} placed at {start:.2f}s")
            shake = shake.model_copy(update={"start": start, "end": round(start + length, 3)})
        moved_shakes.append(shake)
    updated = plan.model_copy(
        update={"elements": sorted(elements, key=lambda e: e.start), "shakes": moved_shakes}
    )
    return MotionPlan.model_validate(updated.model_dump()), notes


def sticker_problems(plan: MotionPlan, *, energy: str, allowlist: list[str]) -> list[str]:
    """Every brand rule the plan's stickers break, one line each."""
    stickers = [e for e in plan.elements if e.type is MotionElementType.STICKER]
    problems: list[str] = []
    limit = STICKER_LIMIT.get(energy, 0)
    if len(stickers) > limit:
        problems.append(
            f"{len(stickers)} sticker(s); motion_energy {energy} allows {limit} per reel"
        )
    cards = [
        (e.start, e.end)
        for e in plan.elements
        if e.type in (MotionElementType.END_CARD, MotionElementType.HOOK_CARD)
    ]
    allowed = set(allowlist)
    for sticker in stickers:
        where = f"sticker at {sticker.start:.2f}s"
        if sticker.start < STICKER_EARLIEST:
            problems.append(f"{where} is in the opening frame")
        if any(sticker.start < end and start < sticker.end for start, end in cards):
            problems.append(f"{where} overlaps a full-frame card")
        if sticker.emoji is not None and sticker.emoji not in allowed:
            shown = " ".join(allowlist) or "none"
            problems.append(
                f"{where} shows {sticker.emoji!r}, which is not in sticker_allowlist ({shown})"
            )
    return problems
