"""2.3: no edit runs on a style nobody chose, and setup problems say what to do."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from social_video.cli import app


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
