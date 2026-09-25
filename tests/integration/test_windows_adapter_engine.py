"""The adapter in front of the real engine: arguments reach the CLI intact.

The stand-in wsl.exe hands `--exec` over to this repository's own
`social-video-agent`, so `social-video-agent.ps1 doctor` and a Polish path with
spaces, brackets and a dollar sign are handled by the real CLI end to end.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from tests.conftest import make_video, requires_ffmpeg
from tests.unit.test_windows_adapter import HOME, LOCAL_ENGINE, PWSH, Harness

ENGINE = Path(sys.executable).with_name("social-video-agent")

pytestmark = [
    pytest.mark.integration,
    requires_ffmpeg,
    pytest.mark.skipif(PWSH is None or sys.platform == "win32", reason="needs pwsh on POSIX"),
    pytest.mark.skipif(not ENGINE.is_file(), reason="engine entry point not installed"),
]


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    harness = Harness(tmp_path)
    harness.configure(
        distributions={
            "Ubuntu": {
                "home": HOME,
                "engines": [LOCAL_ENGINE],
                "path": ["/usr/bin"],
                "real": {LOCAL_ENGINE: str(ENGINE)},
            }
        }
    )
    return harness


def test_doctor_through_the_adapter_is_the_engines_doctor(harness: Harness) -> None:
    result = harness.run("doctor", "--json")

    report = json.loads(result.stdout)
    names = {check["name"] for check in report["checks"]}
    assert {"runtime mode", "ffmpeg", "python"} <= names
    assert "distribution_not_found" not in result.stderr


def test_a_polish_path_with_spaces_reaches_the_engine_intact(
    harness: Harness, tmp_path: Path
) -> None:
    folder = tmp_path / "Test User" / "Wideo (2026)"
    source = make_video(folder / "Mój film $HOME [ujęcie 2].mp4", duration=1.0)
    assert shutil.which("ffprobe")

    result = harness.run("inspect", str(source), "--json")

    assert result.returncode == 0, result.stderr
    info = json.loads(result.stdout)
    assert Path(info["path"]).name == "Mój film $HOME [ujęcie 2].mp4"
    assert info["duration"] == pytest.approx(1.0, abs=0.1)
