"""Read a montage brief: a text block or an entry of the monthly package JSON.

The text form is the one the package's Word document prints:

    Nagranie: ...
    Scenariusz (Czas | Ujęcie | Co mówisz | Napis na ekranie):
    - 0-3 s | shot | what is said | on-screen text / second line
    Montaż: ...
    Okładka: TITLE. Mały podpis: „subtitle”

The JSON form (a package file of several reels) carries the same four fields as
`nagranie`, `scenariusz`, `montaz` and `okladka`, where `scenariusz` is the
same table as text or a list of rows.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from social_video.errors import ValidationError
from social_video.schemas.brief import Brief, BriefLabel, BriefRow

SECTIONS = {
    "nagranie": "recording",
    "scenariusz": "scenario",
    "montaż": "montage",
    "montaz": "montage",
    "okładka": "cover",
    "okladka": "cover",
}
_HEADER = re.compile(r"^\s*(?:#+\s*)?(nagranie|scenariusz|monta[żz]|ok[łl]adka)\b[^:\n]*:?\s*(.*)$",
                     re.IGNORECASE)  # fmt: skip
_TIME = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(?:s\s*)?[–—-]\s*(\d+(?:[.,]\d+)?)\s*s?\s*$")  # noqa: RUF001
#: A line said by someone the camera does not show.
_OFF_SCREEN = re.compile(r"zza\s+kadru|poza\s+kadrem|off[- ]?screen", re.IGNORECASE)
_QUOTES = "„”\"“'‚‘’«»"  # noqa: RUF001 - the quotes Polish text uses
_SUBTITLE = re.compile(r"ma[łl]y\s+podpis\s*:\s*(.+)$", re.IGNORECASE | re.DOTALL)
LABEL_SECONDS = 3.0


def parse_brief_text(text: str, *, source: str = "", title: str = "") -> Brief:
    """A brief from the text block the package prints."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        header = _HEADER.match(line)
        if header and header.group(1).casefold() in SECTIONS:
            current = SECTIONS[header.group(1).casefold()]
            sections.setdefault(current, [])
            if header.group(2).strip():
                sections[current].append(header.group(2).strip())
            continue
        if current is not None:
            sections[current].append(line)
    if "scenario" not in sections:
        raise ValidationError("the brief has no Scenariusz section with timed rows")
    rows = [row for row in (_row(line) for line in sections["scenario"]) if row is not None]
    return _derive(
        Brief(
            title=title,
            source=source,
            recording=_joined(sections.get("recording")),
            rows=rows,
            montage=_joined(sections.get("montage")),
        ),
        _joined(sections.get("cover")),
    )


def parse_brief_entry(entry: dict[str, Any], *, source: str = "") -> Brief:
    """A brief from one entry of the monthly package JSON."""
    scenario = entry.get("scenariusz")
    if isinstance(scenario, str):
        rows = [row for row in (_row(line) for line in scenario.splitlines()) if row]
    elif isinstance(scenario, list):
        rows = [row for row in (_row_from_data(item) for item in scenario) if row]
    else:
        raise ValidationError("the package entry has no `scenariusz`")
    return _derive(
        Brief(
            title=_title(entry),
            source=source,
            recording=str(entry.get("nagranie") or "").strip(),
            rows=rows,
            montage=str(entry.get("montaz") or entry.get("montaż") or "").strip(),
        ),
        str(entry.get("okladka") or entry.get("okładka") or "").strip(),
    )


def load_brief(path: Path, *, entry: int | None = None, match: str | None = None) -> Brief:
    """A brief from a text file or a package JSON, choosing one entry if needed."""
    if not path.is_file():
        raise ValidationError(f"no brief at {path}")
    if path.suffix.casefold() == ".docx":
        from social_video.editorial.docx_brief import docx_brief_text

        text, title = docx_brief_text(path, match=match)
        return parse_brief_text(text, source=str(path), title=title)
    text = path.read_text(encoding="utf-8")
    if path.suffix.casefold() != ".json":
        return parse_brief_text(text, source=str(path))
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{path} is not valid JSON: {exc}") from exc
    entries = _entries(data)
    if not entries:
        raise ValidationError(f"{path} holds no brief entries with a `scenariusz`")
    if match:
        key = match.casefold()
        # A title names the reel; the whole text is the fallback, where words
        # from a cover or a scenario can repeat across reels.
        found = [e for e in entries if key in _title(e).casefold()]
        if not found:
            found = [e for e in entries if key in json.dumps(e, ensure_ascii=False).casefold()]
        if len(found) != 1:
            raise ValidationError(
                f"{len(found)} entries match {match!r}; name one with --entry: " + _listing(entries)
            )
        return parse_brief_entry(found[0], source=str(path))
    if entry is not None:
        if not 0 <= entry < len(entries):
            raise ValidationError(
                f"no entry {entry}; the package has {len(entries)}: " + _listing(entries)
            )
        return parse_brief_entry(entries[entry], source=str(path))
    if len(entries) == 1:
        return parse_brief_entry(entries[0], source=str(path))
    raise ValidationError("the package holds several reels; choose one with --entry or --match: "
                          + _listing(entries))  # fmt: skip


def overrides(brief: Brief) -> list[str]:
    """The brief as `user_overrides` lines for edit-plan.json."""
    lines = [f"brief: {brief.source or 'montage brief'} overrides project defaults for this edit"]
    if brief.first_cue_text:
        who = (
            "said off screen, text only unless recorded"
            if brief.first_line_off_screen
            else "spoken"
        )
        lines.append(f"brief: first caption from 0.0 s carries {brief.first_cue_text!r} ({who})")
    for label in brief.labels:
        lines.append(
            f"brief: label {label.text!r} over the shot at {label.start:g}-{label.end:g} s, "
            "top safe zone, not a card"
        )
    if brief.cover_title:
        lines.append(f"brief: cover.jpg only, never in the timeline: {brief.cover_title!r}")
    lines.append("brief: content first; no title card, cover or logo at the start")
    return lines


def opening_line(workspace, transcript) -> str | None:
    """The brief's first line as a text-only caption, when nobody says it.

    Only a line said off screen qualifies, and only when the recording does
    not carry it: a voice is never synthesised, so without it the line is
    shown, not heard. A line the recording does carry is captioned from the
    speech like any other.
    """
    from social_video.schemas.base import load_artifact

    path = workspace.brief
    if not path.is_file():
        return None
    brief = load_artifact(Brief, path)
    if not (brief.first_line_off_screen and brief.first_cue_text):
        return None
    wanted = _keys(brief.first_cue_text)
    # Any recording of the edit may carry it: an off-screen voice is often its own file.
    heard: set[str] = set()
    for source in transcript if isinstance(transcript, list) else [transcript]:
        heard |= _keys(" ".join(token.text for token in source.words[: len(wanted) + 4]))
    if wanted and len(wanted & heard) / len(wanted) >= 0.6:
        return None
    return brief.first_cue_text


def _keys(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.casefold()))


# -- helpers ------------------------------------------------------------------


def _derive(brief: Brief, cover: str) -> Brief:
    if not brief.rows:
        raise ValidationError("the brief's scenario has no timed rows like `0-3 s | shot | ...`")
    title, subtitle = _cover(cover)
    first = brief.rows[0]
    if first.voice_off_screen:
        first_text = first.on_screen[0] if first.on_screen else _spoken(first.said)
    else:
        first_text = _first_sentence(_spoken(first.said)) or (
            first.on_screen[0] if first.on_screen else ""
        )
    labels: list[BriefLabel] = []
    for number, row in enumerate(brief.rows):
        texts = row.on_screen[1:] if number == 0 else row.on_screen
        for text in texts:
            clean = text.strip().strip(_QUOTES).strip()
            if clean and len(clean) <= 48:
                end = min(row.end, row.start + LABEL_SECONDS)
                labels.append(
                    BriefLabel(text=clean, start=row.start, end=max(end, row.start + 1.0))
                )
    return brief.model_copy(
        update={
            "cover_title": title,
            "cover_subtitle": subtitle,
            "first_cue_text": _unquoted(first_text),
            "first_line_off_screen": first.voice_off_screen,
            "labels": labels,
        }
    )


def _row(line: str) -> BriefRow | None:
    cells = [c.strip() for c in line.strip().lstrip("-*•").strip().strip("|").split("|")]
    if len(cells) < 3:
        return None
    timing = _TIME.match(cells[0])
    if not timing:
        return None
    return _make_row(timing, cells[1], cells[2], cells[3] if len(cells) > 3 else "")


def _row_from_data(item: Any) -> BriefRow | None:
    if isinstance(item, list | tuple):
        return _row(" | ".join(str(c) for c in item))
    if not isinstance(item, dict):
        return None
    keys = {k.casefold(): v for k, v in item.items()}

    def pick(*names: str) -> str:
        return next((str(keys[n]) for n in names if keys.get(n)), "")

    timing = _TIME.match(pick("czas", "time"))
    if not timing:
        return None
    return _make_row(
        timing,
        pick("ujecie", "ujęcie", "shot"),
        pick("co_mowisz", "co mówisz", "mowisz", "said", "tekst"),
        pick("napis", "napis_na_ekranie", "napis na ekranie", "on_screen"),
    )


def _make_row(timing: re.Match[str], shot: str, said: str, on_screen: str) -> BriefRow:
    start, end = (float(g.replace(",", ".")) for g in timing.groups())
    return BriefRow(
        start=start,
        end=max(end, start + 0.1),
        shot=shot,
        said=said,
        on_screen=[part.strip() for part in on_screen.split(" / ") if part.strip()],
        voice_off_screen=bool(_OFF_SCREEN.search(said)),
    )


def _spoken(said: str) -> str:
    """The words in quotes, or the text after a speaker label.

    A row that narrates first ("Kawa miała być gotowa… A teraz… słychać:
    „Nie ma mleka!”") is spoken as a whole: the quote is the end of it,
    not the line the reel opens on.
    """
    quoted = re.findall(r"[„\"“](.+?)[”\"]", said)
    before = re.split(r"[„\"“]", said, maxsplit=1)[0]
    if quoted and not re.search(r"\w[.!?…]\s", before):
        return " ".join(q.strip() for q in quoted)
    if quoted:
        return said.strip()
    return said.split(":", 1)[1].strip() if ":" in said else said.strip()


#: Abbreviations a sentence does not end on.
_ABBREVIATIONS = ("np.", "itp.", "itd.", "tzn.", "tj.", "m.in.", "ok.", "e.g.", "i.e.")


def _unquoted(text: str) -> str:
    """A line the brief quotes whole, without the quotes: a caption shows speech.

    Only one pair around the whole line goes; a quote inside it stays.
    """
    text = text.strip()
    if len(text) > 1 and text[0] in _QUOTES and text[-1] in _QUOTES:
        inner = text[1:-1].strip()
        if not any(mark in inner for mark in _QUOTES if mark != "'"):
            return inner
    return text


def _first_sentence(text: str) -> str:
    for match in re.finditer(r"[.!?…](\s|$)", text):
        head = text[: match.start() + 1]
        if not head.casefold().endswith(_ABBREVIATIONS):
            return head.strip()
    return text.strip()


def _cover(text: str) -> tuple[str, str]:
    if not text:
        return "", ""
    subtitle = ""
    found = _SUBTITLE.search(text)
    if found:
        subtitle = found.group(1).strip().rstrip(".").strip(_QUOTES).strip()
        text = text[: found.start()]
    return text.strip().rstrip(".").strip(_QUOTES).strip(), subtitle


def _joined(lines: list[str] | None) -> str:
    return " ".join(line.strip() for line in lines or [] if line.strip())


def _title(entry: dict[str, Any]) -> str:
    for key in ("tytul", "tytuł", "temat", "title", "nazwa"):
        if entry.get(key):
            return str(entry[key]).strip()
    return ""


def _entries(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict) and "scenariusz" in data:
        return [data]
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list) and any(
                isinstance(v, dict) and "scenariusz" in v for v in value
            ):
                return [v for v in value if isinstance(v, dict) and "scenariusz" in v]
        return []
    if isinstance(data, list):
        return [v for v in data if isinstance(v, dict) and "scenariusz" in v]
    return []


def _listing(entries: list[dict[str, Any]]) -> str:
    return "; ".join(
        f"{i}: {_title(e) or str(e.get('okladka', ''))[:40]}" for i, e in enumerate(entries)
    )
