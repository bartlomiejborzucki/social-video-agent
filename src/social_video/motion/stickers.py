"""Stickers and shakes: a reaction on one word, placed by the words themselves.

A sticker (an emoji or a small project image) and a shake of the picture
both answer a word -- "Zgodziłeś!" -- so they are anchored to it with
`at_word` (see `motion.anchors`).

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
