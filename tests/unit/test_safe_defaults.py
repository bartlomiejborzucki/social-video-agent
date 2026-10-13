"""2.3: no edit runs on a style nobody chose, and setup problems say what to do."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from social_video.cli import app
from social_video.doctor import DoctorReport, _check_brand_font
from social_video.project_config import font_install_hint, implicit_defaults


def _project(tmp_path: Path, body: str) -> Path:
    root = tmp_path / "projekt"
    (root / "assets").mkdir(parents=True)
    (root / "assets" / "Lato.ttf").write_bytes(b"fixture-font")
    (root / ".social-video").mkdir()
    (root / ".social-video" / "config.yaml").write_text(
        "schema_version: 1\nfont: Lato\nfont_file: assets/Lato.ttf\n" + body, encoding="utf-8"
    )
    return root


def test_validate_without_a_workspace_writes_nothing(tmp_path: Path) -> None:
    root = _project(tmp_path, "")
    result = CliRunner().invoke(app, ["config", "validate", str(root)])
    assert result.exit_code == 0, result.output
    assert not (root / "edit").exists(), "validation must not create an edit folder"
    assert "pass --workspace" in result.output

    edit = tmp_path / "edycja"
    result = CliRunner().invoke(app, ["config", "validate", str(root), "-w", str(edit)])
    assert result.exit_code == 0, result.output
    assert (edit / "brand-contract.json").is_file()


def test_validate_names_the_style_left_to_defaults(tmp_path: Path) -> None:
    root = _project(tmp_path, "motion_energy: bold\ncaption_style:\n  animation: box\n")
    result = CliRunner().invoke(app, ["config", "validate", str(root), "--json"])
    unset = json.loads(result.output)["defaults_not_in_config"]
    assert "motion_energy" not in unset and "caption_style.animation" not in unset
    assert unset["style_pack"] == "editorial"
    assert unset["caption_style.active_word_highlight"] is False
    assert unset["label_style"] == "chip"

    plain = CliRunner().invoke(app, ["config", "validate", str(root)])
    assert "default style_pack: 'editorial' -- not in the config" in plain.output


def test_init_writes_every_style_decision_down(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["config", "init", str(tmp_path), "--motion-energy", "bold", "--style-pack",
         "bold-social", "--karaoke", "--animation", "box", "--emphasis-words",
         "smutek, długa", "--label-style", "scene_frame"],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    config = tmp_path / ".social-video" / "config.yaml"
    raw = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert (raw["motion_energy"], raw["style_pack"], raw["label_style"]) == (
        "bold", "bold-social", "scene_frame"
    )  # fmt: skip
    style = raw["caption_style"]
    assert style["active_word_highlight"] is True and style["animation"] == "box"
    assert style["emphasis_words"] == ["smutek", "długa"]
    assert implicit_defaults(config) == {}, "nothing left to a default"


def test_init_without_a_terminal_asks_nothing_and_still_writes_it_all(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["config", "init", str(tmp_path), "--defaults"])
    assert result.exit_code == 0, result.output
    assert "(template)" in result.output
    assert implicit_defaults(tmp_path / ".social-video" / "config.yaml") == {}


def test_init_refuses_choices_that_do_not_validate(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app, ["config", "init", str(tmp_path), "--defaults", "--motion-energy", "wild"]
    )
    assert result.exit_code != 0
    assert not (tmp_path / ".social-video" / "config.yaml").exists()


def test_a_missing_brand_font_says_how_to_install_it(tmp_path: Path) -> None:
    root = tmp_path / "projekt"
    (root / ".social-video").mkdir(parents=True)
    (root / ".social-video" / "config.yaml").write_text(
        "schema_version: 1\nfont: Zzyzx Display\n", encoding="utf-8"
    )
    report = DoctorReport()
    _check_brand_font(report, start=root / "sub")
    (check,) = report.checks
    assert not check.ok and not check.required
    assert "sudo apt install fonts-zzyzx-display" in check.remedy
    assert "font_file" in font_install_hint("Lato")
