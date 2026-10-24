"""Read one reel's brief out of the monthly Word document.

The monthly posts document (a .docx) holds every post of the
month, each under a heading ``DD.MM DZIEŃ · ROLKA · Tytuł``: a ``Nagranie``
paragraph, a ``Scenariusz`` table (Czas | Ujęcie | Co mówisz | Napis na
ekranie), ``Montaż``, ``Okładka`` and then the captions for each platform.
This turns the chosen reel into the text form `parse_brief_text` reads.

The document is edited with tracked changes on, so what it says is the text
with deletions removed and insertions kept -- what Word shows once every
change is accepted -- not every run in the XML.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from social_video.errors import ValidationError

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
#: Content Word keeps only to show what was removed or moved away.
_REMOVED = {f"{W}del", f"{W}moveFrom", f"{W}delText"}
_HEADING = re.compile(r"^\s*(\d{1,2}\.\d{1,2})\b[^·]*·\s*([^·]+?)\s*·\s*(.+?)\s*$")
_SECTIONS = {
    "nagranie": "Nagranie",
    "scenariusz": "Scenariusz",
    "montaż": "Montaż",
    "montaz": "Montaż",
    "okładka": "Okładka",
    "okladka": "Okładka",
}


@dataclass
class _Post:
    date: str
    kind: str
    title: str
    blocks: list[tuple[str, object]] = field(default_factory=list)

    @property
    def heading(self) -> str:
        return f"{self.date} · {self.kind} · {self.title}"


def docx_brief_text(path: Path, *, match: str | None = None) -> tuple[str, str]:
    """The chosen reel's brief as text, and its title."""
    posts = [p for p in _posts(path) if p.kind.casefold() == "rolka"]
    if not posts:
        raise ValidationError(f"{path.name} has no reel heading like '05.01 WTOREK · ROLKA · …'")
    if match:
        key = match.casefold()
        found = [p for p in posts if key in p.title.casefold()] or [
            p for p in posts if key in p.heading.casefold()
        ]
    else:
        found = posts if len(posts) == 1 else []
    if len(found) != 1:
        listing = "; ".join(p.heading for p in posts)
        what = (
            f"{len(found)} reels match {match!r}" if match else "the document holds several reels"
        )
        raise ValidationError(f"{what}; choose one with --match: {listing}")
    post = found[0]
    return _as_text(post), post.title


def _posts(path: Path) -> list[_Post]:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ValidationError(f"{path.name} is not a Word document: {exc}") from exc
    body = ElementTree.fromstring(xml).find(f"{W}body")
    posts: list[_Post] = []
    if body is None:
        return posts
    for element in body:
        if element.tag == f"{W}p":
            text = _paragraph(element)
            heading = _HEADING.match(text)
            if heading:
                date, kind, title = heading.groups()
                posts.append(_Post(date, kind, title))
            elif posts and text.strip():
                posts[-1].blocks.append(("p", text.strip()))
        elif element.tag == f"{W}tbl" and posts:
            posts[-1].blocks.append(("table", _table(element)))
    return posts


def _as_text(post: _Post) -> str:
    """The post's brief in the package's text form; captions and the rest left out."""
    lines: list[str] = []
    current: str | None = None
    for kind, block in post.blocks:
        if kind == "table":
            rows = (
                [row for row in block if isinstance(row, list)] if isinstance(block, list) else []
            )
            if current == "Scenariusz" or _is_scenario(rows):
                if current != "Scenariusz":
                    lines.append("Scenariusz:")
                    current = "Scenariusz"
                lines += [_row(cells) for cells in rows[1:] if len(cells) >= 3]
            continue
        text = str(block)
        name = _SECTIONS.get(text.rstrip(":").strip().casefold())
        if name is not None:
            current = name
            lines.append(f"{name}:")
        elif _looks_like_heading(text):
            current = None
        elif current is not None:
            lines.append(text)
    return "\n".join(lines) + "\n"


def _is_scenario(rows: list[list[list[str]]]) -> bool:
    return bool(rows and rows[0] and " ".join(rows[0][0]).strip().casefold().startswith("czas"))


def _row(cells: list[list[str]]) -> str:
    """One scenario row; on-screen lines stay apart (' / '), speech runs on."""

    def joined(parts: list[str], glue: str) -> str:
        lines = [line.strip() for part in parts for line in part.split("\n")]
        return glue.join(line for line in lines if line).replace("|", "/")

    timing = joined(cells[0], " ")
    shot, said = joined(cells[1], " "), joined(cells[2], " ")
    on_screen = joined(cells[3], " / ") if len(cells) > 3 else ""
    return f"- {timing} | {shot} | {said} | {on_screen}"


def _looks_like_heading(text: str) -> bool:
    """A short line without a full stop, e.g. 'Opis Instagram i Facebook'."""
    return len(text) <= 60 and not text.rstrip().endswith((".", "!", "?", "”", '"'))


def _table(table: ElementTree.Element) -> list[list[list[str]]]:
    """Rows of cells, each cell its paragraphs."""
    rows: list[list[list[str]]] = []
    for row in table.iter(f"{W}tr"):
        if _removed_row(row):
            continue
        rows.append(
            [[_paragraph(p) for p in cell.findall(f"{W}p")] for cell in row.findall(f"{W}tc")]
        )
    return rows


def _removed_row(row: ElementTree.Element) -> bool:
    properties = row.find(f"{W}trPr")
    return properties is not None and properties.find(f"{W}del") is not None


def _paragraph(paragraph: ElementTree.Element) -> str:
    """The paragraph's text with tracked deletions dropped, insertions kept."""
    out: list[str] = []

    def walk(node: ElementTree.Element) -> None:
        if node.tag in _REMOVED:
            return
        if node.tag == f"{W}t" and node.text:
            out.append(node.text)
        elif node.tag in (f"{W}br", f"{W}cr"):
            out.append("\n")
        elif node.tag == f"{W}tab":
            out.append(" ")
        for child in node:
            walk(child)

    walk(paragraph)
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in "".join(out).split("\n"))
