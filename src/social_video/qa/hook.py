"""Hook check: is the first caption and the first second worth staying for?

A heuristic, not an oracle. It reads the first caption and measures the first
second of the picture: a concrete situation rather than a name, a title or a
book; the viewer addressed, or a tension or question left open; at most eight
words; the first word within 0.3 s; the picture moving in the first second; no
greeting. What counts as a concrete situation depends on the project's niche,
so that list is empty here and filled by the project. Each miss comes with a
concrete fix, in Polish, and nothing is blocked: the result goes to
`analysis/hook-check.json` and the delivery manifest for the editor to weigh.

The general word lists live in `qa/data/hook_pl.yaml`. A project replaces any
of them with `.social-video/hook-words.yaml` in its own root, so niche words
never live in this package.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from itertools import pairwise
from pathlib import Path

import yaml

from social_video.fsutil import atomic_write_text
from social_video.schemas.captions import CaptionTrack

WORDS_FILE = Path(__file__).with_name("data") / "hook_pl.yaml"
#: A project's own lists, relative to its root.
PROJECT_WORDS = Path(".social-video") / "hook-words.yaml"
#: Category names used before 2.7.
_RENAMED = {"child": "situation"}
MAX_WORDS = 8
FIRST_WORD_LIMIT = 0.3
#: Mean change between frames 0 and 1 s, out of 255, below which it is still.
MOVEMENT_LIMIT = 6.0


@dataclass(frozen=True)
class HookFinding:
    name: str
    ok: bool
    detail: str
    fix: str = ""


@dataclass
class HookReport:
    text: str
    findings: list[HookFinding] = field(default_factory=list)

    @property
    def score(self) -> str:
        return f"{sum(f.ok for f in self.findings)}/{len(self.findings)}"

    @property
    def fixes(self) -> list[str]:
        return [f.fix for f in self.findings if not f.ok and f.fix]

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "score": self.score,
            "findings": [asdict(f) for f in self.findings],
            "fixes": self.fixes,
        }


def load_words(path: Path = WORDS_FILE) -> dict[str, list[str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        _RENAMED.get(key, key): [str(v).casefold() for v in values or []]
        for key, values in data.items()
    }


def project_words(project_root: Path | None) -> dict[str, list[str]]:
    """The general lists, with every category the project defines replaced."""
    words = load_words()
    if project_root is not None and (project_root / PROJECT_WORDS).is_file():
        words |= load_words(project_root / PROJECT_WORDS)
    return words


def workspace_words(workspace) -> dict[str, list[str]]:
    """The lists for an edit, from the project its brand contract was compiled in."""
    from social_video.schemas.base import load_artifact
    from social_video.schemas.config import BrandContract

    if not workspace.brand_contract.is_file():
        return load_words()
    contract = load_artifact(BrandContract, workspace.brand_contract)
    return project_words(Path(contract.project_root))


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def matches(text: str, entries: list[str]) -> list[str]:
    """Entries found in the text: phrases by words, short words whole, stems by start."""
    tokens = _tokens(text)
    joined = " " + " ".join(tokens) + " "
    found = []
    for entry in entries:
        parts = _tokens(entry)
        if not parts:
            continue
        if len(parts) > 1:
            if " " + " ".join(parts) + " " in joined:
                found.append(entry)
        elif len(parts[0]) >= 4:
            if any(token.startswith(parts[0]) for token in tokens):
                found.append(entry)
        elif parts[0] in tokens:
            found.append(entry)
    return found


def check_text(
    text: str, *, first_word_at: float | None, words: dict[str, list[str]] | None = None
) -> list[HookFinding]:
    """The checks that read the first caption alone."""
    lists = words or load_words()
    count = len(_tokens(text))
    findings = [
        HookFinding(
            "co najwyżej 8 słów",
            count <= MAX_WORDS,
            f"{count} słów",
            f"skróć pierwszy napis do {MAX_WORDS} słów; resztę zdania zostaw na kolejny",
        )
    ]
    if first_word_at is not None:
        findings.append(
            HookFinding(
                "pierwsze słowo od razu",
                first_word_at <= FIRST_WORD_LIMIT,
                f"pierwsze słowo w {first_word_at:.2f} s",
                f"zacznij pierwszy zakres na mowie: pierwsze słowo do {FIRST_WORD_LIMIT} s",
            )
        )
    if lists.get("situation"):
        situation = matches(text, lists["situation"])
        findings.append(
            HookFinding(
                "konkretna sytuacja",
                bool(situation),
                ", ".join(situation) if situation else "brak konkretnej sytuacji",
                "otwórz na tym, kto co robi (np. „Kawa miała być gotowa… a teraz nie ma mleka”)",
            )
        )
    promo = matches(text, lists.get("promo", []))
    findings.append(
        HookFinding(
            "bez nazwy, tytułu i książki",
            not promo,
            ", ".join(promo) if promo else "nic z autopromocji",
            "przenieś książkę, link i tytuł na koniec rolki albo do opisu",
        )
    )
    address = matches(text, lists.get("address", []))
    tension = matches(text, lists.get("tension", [])) + (["?"] if "?" in text else [])
    findings.append(
        HookFinding(
            "zwrot do widza albo napięcie",
            bool(address or tension),
            ", ".join(address + tension) if address or tension else "ani jednego, ani drugiego",
            "zwróć się do widza („Twój poranek…”) albo zostaw pytanie bez odpowiedzi",
        )
    )
    greeting = matches(text, lists.get("greeting", []))
    findings.append(
        HookFinding(
            "bez powitania",
            not greeting,
            ", ".join(greeting) if greeting else "brak powitania",
            "wytnij powitanie; rolka zaczyna się od sytuacji",
        )
    )
    return findings


def check_title(text: str, *, words: dict[str, list[str]] | None = None) -> list[HookFinding]:
    """The hook title: short, and a question, an order, a number or a conflict."""
    lists = words or load_words()
    count = len(_tokens(text))
    findings = [
        HookFinding(
            "tytuł: co najwyżej 8 słów",
            count <= MAX_WORDS,
            f"{count} słów",
            f"skróć tytuł do {MAX_WORDS} słów; dwa krótkie wiersze czyta się w sekundę",
        )
    ]
    tokens = _tokens(text)
    first_two = " ".join(tokens[:2])
    imperative = [
        e for e in lists.get("imperative", []) if (first_two + " ").startswith(e + " ")
    ]  # fmt: skip
    # Whole words only: "trzy" is a number, "trzymaj" is not.
    numerals = set(lists.get("numbers", []))
    number = [t for t in tokens if t.isdigit() or t in numerals]
    conflict = matches(text, lists.get("conflict", []))
    kinds = (
        (["pytanie"] if "?" in text else [])
        + (["rozkaz: " + imperative[0]] if imperative else [])
        + (["liczba: " + number[0]] if number else [])
        + (["konflikt: " + conflict[0]] if conflict else [])
    )
    findings.append(
        HookFinding(
            "tytuł: pytanie, rozkaz, liczba albo konflikt",
            bool(kinds),
            ", ".join(kinds) if kinds else "żadne z czterech",
            "przepisz tytuł jako pytanie („Kto pierwszy ustąpi?”), polecenie („Nie odkładaj…”), "
            "z liczbą („3 kroki…”) albo z wyborem („A czy B?”)",
        )
    )
    return findings


#: A list announced this early ("3 kroki") is worth showing as one.
LIST_WINDOW_S = 5.0


def announced_list(
    captions: CaptionTrack | None,
    *,
    words: dict[str, list[str]] | None = None,
    shown: bool = False,
) -> HookFinding | None:
    """A list announced in the first seconds ("3 kroki"): suggest one on screen.

    ``shown``: the motion plan already has a list, steps or process, so the
    announced points are on screen and the finding passes.
    """
    if captions is None:
        return None
    lists = words or load_words()
    nouns = lists.get("list_nouns", [])
    numbers = set(lists.get("numbers", []))
    for cue in captions.cues:
        if cue.start > LIST_WINDOW_S:
            break
        tokens = _tokens(cue.text)
        for count, noun in pairwise(tokens):
            is_number = count.isdigit() or count in numbers
            if is_number and any(noun.startswith(stem) for stem in nouns):
                said = f"{count} {noun}"
                return HookFinding(
                    "zapowiedziana lista na ekranie",
                    shown,
                    f"„{said}” w {cue.start:.1f} s" + (", punkty są na ekranie" if shown else ""),
                    "dodaj element `list` z punktami i `item_at_words` (każdy punkt wchodzi na "
                    "swoim słowie); ewentualnie gest liczby palców przy nagraniu",
                )
    return None


def first_second_movement(video: Path) -> float | None:
    """Mean frame change across the first second, out of 255."""
    from social_video.qa.opening import _pixels

    samples = [_pixels(video, at) for at in (0.0, 0.33, 0.66, 1.0)]
    frames = [s for s in samples if s is not None]
    if len(frames) < 2:
        return None
    return max(float(abs(a - b).mean()) for a, b in pairwise(frames))


def check_hook(
    captions: CaptionTrack | None,
    video: Path | None,
    *,
    analysis_dir: Path | None = None,
    words: dict[str, list[str]] | None = None,
    title: str | None = None,
    list_shown: bool = False,
) -> HookReport:
    """The whole hook check; writes `hook-check.json` when given a folder."""
    cue = captions.cues[0] if captions and captions.cues else None
    text = cue.text if cue else ""
    first = None
    if cue is not None:
        first = cue.words[0].start if cue.words else cue.start
    report = HookReport(text=text)
    if cue is None:
        report.findings.append(
            HookFinding("pierwszy napis", False, "brak napisów", "zbuduj napisy przed oceną")
        )
    else:
        report.findings += check_text(text, first_word_at=first, words=words)
    if title:
        report.findings += check_title(title, words=words)
    listed = announced_list(captions, words=words, shown=list_shown)
    if listed is not None:
        report.findings.append(listed)
    if video is not None and video.is_file():
        change = first_second_movement(video)
        if change is not None:
            report.findings.append(
                HookFinding(
                    "ruch w pierwszej sekundzie",
                    change >= MOVEMENT_LIMIT,
                    f"zmiana obrazu {change:.1f}/255",
                    "zacznij od momentu ruchu (motion suggest proponuje in-point) "
                    "albo daj najazd na pierwszym słowie kluczowym w 1,0-1,5 s",
                )
            )
    if analysis_dir is not None:
        atomic_write_text(
            analysis_dir / "hook-check.json",
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
        )
    return report
