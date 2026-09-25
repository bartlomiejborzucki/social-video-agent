"""Installing the skill where a native Windows agent can actually read it."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "social-video-agent"


def _installer():
    spec = importlib.util.spec_from_file_location(
        "install_skills", ROOT / "scripts/install_skills.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def installer(monkeypatch: pytest.MonkeyPatch):
    module = _installer()
    return module


@pytest.mark.parametrize(
    ("destination", "copy"),
    [
        ("/mnt/c/Users/bartl/.agents/skills/social-video-agent", True),
        ("/mnt/d/Profile/.agents/skills/social-video-agent", True),
        ("/home/bartl/.agents/skills/social-video-agent", False),
    ],
)
def test_a_windows_drive_seen_from_wsl_gets_a_copy(installer, destination: str, copy: bool) -> None:
    if sys.platform == "win32":
        pytest.skip("on Windows every destination is copied")
    assert installer.needs_copy(Path(destination)) is copy


def _assert_real_copy(destination: Path) -> None:
    assert destination.is_dir() and not destination.is_symlink()
    for source in SKILL.rglob("*"):
        copied = destination / source.relative_to(SKILL)
        assert not copied.is_symlink(), copied
        if source.is_file():
            assert copied.read_bytes() == source.read_bytes()
    assert not list(destination.parent.glob(".*.partial"))


def test_a_1_0_symlink_install_is_replaced_by_real_files(installer, tmp_path: Path) -> None:
    """What 1.0 left on the Windows drive: a Linux symlink into /home."""
    destination = tmp_path / "Windows" / ".agents" / "skills" / "social-video-agent"
    destination.parent.mkdir(parents=True)
    destination.symlink_to(SKILL, target_is_directory=True)

    status = installer.install(SKILL, destination, copy=True)

    assert status.startswith("copied")
    _assert_real_copy(destination)


def test_reinstalling_refreshes_the_copy(installer, tmp_path: Path) -> None:
    destination = tmp_path / "skills" / "social-video-agent"
    installer.install(SKILL, destination, copy=True)
    (destination / "stale.md").write_text("left over from an older release", encoding="utf-8")

    installer.install(SKILL, destination, copy=True)

    assert not (destination / "stale.md").exists()
    _assert_real_copy(destination)


def test_a_folder_that_is_not_a_skill_is_never_deleted(installer, tmp_path: Path) -> None:
    destination = tmp_path / "skills" / "social-video-agent"
    destination.mkdir(parents=True)
    (destination / "notes.txt").write_text("mine", encoding="utf-8")

    with pytest.raises(SystemExit, match="refusing to replace"):
        installer.install(SKILL, destination, copy=True)

    assert (destination / "notes.txt").read_text(encoding="utf-8") == "mine"
    assert not list(destination.parent.glob(".*.partial"))


def test_a_linux_host_still_gets_a_live_link(installer, tmp_path: Path) -> None:
    if sys.platform == "win32":
        pytest.skip("symlinks need developer mode on Windows")
    destination = tmp_path / ".claude" / "skills" / "social-video-agent"

    status = installer.install(SKILL, destination)

    assert status == "linked"
    assert destination.is_symlink() and destination.resolve() == SKILL.resolve()


def test_the_command_line_installs_into_an_explicit_directory(tmp_path: Path) -> None:
    target = tmp_path / "Windows home" / ".agents" / "skills"

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/install_skills.py"), "--dest", str(target), "--copy"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
    )

    assert result.returncode == 0, result.stderr
    _assert_real_copy(target / "social-video-agent")


PWSH = os.environ.get("SOCIAL_VIDEO_TEST_PWSH") or shutil.which("pwsh")


@pytest.mark.skipif(PWSH is None, reason="needs PowerShell 7 (pwsh)")
def test_powershell_reads_the_installed_skill(installer, tmp_path: Path) -> None:
    """A native reader, not Python, opens SKILL.md from the installed copy."""
    destination = tmp_path / "Mój profil" / ".agents" / "skills" / "social-video-agent"
    installer.install(SKILL, destination, copy=True)
    assert PWSH is not None

    result = subprocess.run(
        [
            PWSH,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$item = Get-Item -LiteralPath $env:SKILL_DIR; "
            "if ($item.LinkType) { throw 'still a link' }; "
            "Get-Content -LiteralPath (Join-Path $env:SKILL_DIR 'SKILL.md') -Encoding utf8 "
            "-TotalCount 3",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env={**os.environ, "SKILL_DIR": str(destination)},
    )

    assert result.returncode == 0, result.stderr
    assert "name: social-video-agent" in result.stdout
