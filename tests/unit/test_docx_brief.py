"""The month's posts document as a brief: one reel, tracked changes accepted."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from social_video.cli import app
from social_video.editorial.brief import load_brief
from social_video.errors import ValidationError
from social_video.schemas.base import load_artifact
from social_video.schemas.motion import MotionPlan
from social_video.workspace.layout import Workspace

#: Word writes time spans with an en dash.
DASH = "\u2013"
NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _p(text: str, style: str = "") -> str:
    props = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f'<w:p>{props}<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def _cell(*paragraphs: str) -> str:
    return "<w:tc>" + "".join(paragraphs) + "</w:tc>"


def _row(*cells: str, deleted: bool = False) -> str:
    props = '<w:trPr><w:del w:id="9" w:author="J"/></w:trPr>' if deleted else ""
    return f"<w:tr>{props}{''.join(cells)}</w:tr>"


def _docx(path: Path) -> Path:
    tracked = (
        "<w:p><w:r><w:t>Przecież się </w:t></w:r>"
        '<w:del w:id="1" w:author="J"><w:r><w:delText>zgodziliśmy</w:delText></w:r></w:del>'
        '<w:ins w:id="2" w:author="J"><w:r><w:t>dogadaliśmy</w:t></w:r></w:ins>'
        "<w:r><w:t>! Zgodziłeś!</w:t></w:r></w:p>"
    )
    table = (
        "<w:tbl>"
        + _row(_cell(_p("Czas")), _cell(_p("Ujęcie")), _cell(_p("Co mówisz")), _cell(_p("Napis")))
        + _row(
            _cell(_p(f"0{DASH}4 s")),
            _cell(_p("Pokój")),
            _cell(_p("Dziecko miało posprzątać. A teraz słychać: „Nie chcę!”")),
            _cell(_p("Zgodziło się."), _p("A teraz nie chce.")),
        )
        + _row(_cell(_p(f"4{DASH}10 s")), _cell(_p("Ten sam plac")), _cell(tracked),
               _cell(_p("Częsty odruch")))
        + _row(_cell(_p(f"10{DASH}12 s")), _cell(_p("x")), _cell(_p("Usunięty wiersz.")),
               _cell(_p("Nie ma mnie")), deleted=True)
        + "</w:tbl>"
    )  # fmt: skip
    body = "".join(
        [
            _p("Posty — Październik 2026", "Tytu"),
            _p("02.01 piątek · ROLKA · Czas na kąpiel", "Nagwek1"),
            _p("Scenariusz"),
            "<w:tbl>"
            + _row(_cell(_p("Czas")), _cell(_p("U")), _cell(_p("C")), _cell(_p("N")))
            + _row(_cell(_p(f"0{DASH}3 s")), _cell(_p("a")), _cell(_p("Myj!")), _cell(_p("MYJ")))
            + "</w:tbl>",
            _p("05.01 WTOREK · ROLKA · Przecież się dogadaliśmy!", "Nagwek1"),
            _p("Nagranie"),
            _p("Stały kadr z misiem."),
            _p("Scenariusz"),
            table,
            _p("Montaż"),
            _p("Pierwsza klatka = scena."),
            _p("Okładka"),
            _p("„PRZECIEŻ SIĘ DOGADALIŚMY!”. Mały podpis: „Seria poradników”."),
            _p("Opis Instagram i Facebook"),
            _p("Opis, który nie jest briefem montażu."),
        ]
    )
    xml = f'<?xml version="1.0"?><w:document {NS}><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return path


def test_a_reel_is_read_with_tracked_changes_accepted(tmp_path: Path) -> None:
    brief = load_brief(_docx(tmp_path / "posty-2026-01.docx"), match="dogadaliśmy")
    assert brief.title == "Przecież się dogadaliśmy!"
    assert [row.start for row in brief.rows] == [0.0, 4.0]
    assert brief.rows[1].said == "Przecież się dogadaliśmy! Zgodziłeś!"
    assert brief.rows[0].on_screen == ["Zgodziło się.", "A teraz nie chce."]
    assert "Opis, który" not in brief.montage
    assert brief.cover_title == "PRZECIEŻ SIĘ DOGADALIŚMY!"
    # The first row's second on-screen line names its scene, as in the text form.
    assert [label.text for label in brief.labels] == ["A teraz nie chce.", "Częsty odruch"]


def test_several_reels_need_a_match(tmp_path: Path) -> None:
    path = _docx(tmp_path / "posty.docx")
    with pytest.raises(ValidationError, match=r"choose one with --match: 02\.01"):
        load_brief(path)
    assert load_brief(path, match="kąpiel").rows[0].said == "Myj!"


def test_brief_import_with_labels_from_word(tmp_path: Path) -> None:
    path = _docx(tmp_path / "posty.docx")
    ws = Workspace.at(tmp_path / "edit")
    ws.ensure()
    result = CliRunner().invoke(
        app,
        ["brief", "import", str(path), "-w", str(ws.root), "--match", "dogadaliśmy", "--labels"],
    )
    assert result.exit_code == 0, result.output
    labels = [e.text for e in load_artifact(MotionPlan, ws.motion_plan).elements]
    assert labels == ["A teraz nie chce.", "Częsty odruch"]
