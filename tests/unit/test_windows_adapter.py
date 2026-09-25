"""The Windows adapter, run by a real PowerShell against a stand-in wsl.exe.

These drive `scripts/windows/social-video-agent.ps1` end to end. The stand-in
(`tests/fixtures/fake_wsl.py`) is installed twice on PATH, as System32 and the
WindowsApps alias are on a real machine, answers `--list` in UTF-16, runs
`--exec` programs from an argv array, and keeps ~/.local/bin off the
non-interactive PATH. It records every call, so the tests can assert on the
argument arrays the adapter produced rather than on its source text.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "scripts" / "windows" / "social-video-agent.ps1"
FAKE = ROOT / "tests" / "fixtures" / "fake_wsl.py"
PWSH = os.environ.get("SOCIAL_VIDEO_TEST_PWSH") or shutil.which("pwsh")

pytestmark = pytest.mark.skipif(
    PWSH is None or sys.platform == "win32",
    reason="needs PowerShell 7 (pwsh) on a POSIX host to run the stand-in wsl.exe",
)

ONE = "  NAME      STATE           VERSION\r\n* Ubuntu    Running         2\r\n"
TWO_NO_DEFAULT = (
    "  NAME              STATE           VERSION\r\n"
    "  Ubuntu-24.04      Running         2\r\n"
    "  Ubuntu-22.04      Stopped         2\r\n"
)
HOME = "/home/bartłomiej"
LOCAL_ENGINE = f"{HOME}/.local/bin/social-video-agent"


class Harness:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.log = tmp_path / "calls.jsonl"
        self.config = tmp_path / "fake-wsl.json"
        self.dirs = []
        # Two wsl.exe on PATH, like C:\Windows\System32 and the WindowsApps alias.
        for name in ("System32", "WindowsApps"):
            directory = tmp_path / name
            directory.mkdir()
            binary = directory / "wsl.exe"
            binary.write_text(
                f"#!{sys.executable}\n" + FAKE.read_text(encoding="utf-8"), encoding="utf-8"
            )
            binary.chmod(0o755)
            self.dirs.append(directory)
        self.configure()

    def configure(self, *, listing: str = ONE, distributions: dict | None = None) -> None:
        distributions = distributions or {
            "Ubuntu": {"home": HOME, "engines": [LOCAL_ENGINE], "path": ["/usr/bin"]}
        }
        self.config.write_text(
            json.dumps({"listing": listing, "log": str(self.log), "distributions": distributions}),
            encoding="utf-8",
        )

    def run(self, *args: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("SOCIAL_VIDEO_") and key != "WSLENV"
        }
        environment["PATH"] = os.pathsep.join([*map(str, self.dirs), environment["PATH"]])
        environment["FAKE_WSL_CONFIG"] = str(self.config)
        environment.update(env or {})
        assert PWSH is not None
        return subprocess.run(
            [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(ADAPTER), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            timeout=120,
            check=False,
        )

    @property
    def calls(self) -> list[dict]:
        if not self.log.is_file():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def engine_output(self, result: subprocess.CompletedProcess[str]) -> dict:
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


def test_several_wsl_exe_on_path_use_one_of_them(harness: Harness) -> None:
    result = harness.run("doctor")

    assert result.returncode == 0, result.stderr
    assert harness.calls, "the adapter never reached wsl.exe"


def test_the_first_argument_goes_to_the_engine_not_to_the_distribution(harness: Harness) -> None:
    output = harness.engine_output(harness.run("doctor"))

    assert output["engine_args"] == ["doctor"]


def test_an_engine_in_local_bin_is_found_without_a_login_shell(harness: Harness) -> None:
    output = harness.engine_output(harness.run("doctor", "--json"))

    assert output["engine_args"] == ["doctor", "--json"]
    final = harness.calls[-1]["argv"]
    assert final == ["--distribution", "Ubuntu", "--exec", LOCAL_ENGINE, "doctor", "--json"]
    for call in harness.calls:
        assert "--" not in call["argv"], "a `--` call runs through the default shell"
        assert "-lc" not in call["argv"] and "-c" not in call["argv"]


def test_the_engine_is_told_the_agent_is_on_windows(harness: Harness) -> None:
    output = harness.engine_output(harness.run("doctor"))

    assert output["env"] == {
        "SOCIAL_VIDEO_AGENT_PLATFORM": "windows",
        "SOCIAL_VIDEO_WSL_DISTRIBUTION": "Ubuntu",
    }
    shared = output["wslenv"].split(":")
    assert "SOCIAL_VIDEO_AGENT_PLATFORM" in shared
    assert "SOCIAL_VIDEO_WSL_DISTRIBUTION" in shared


@pytest.mark.parametrize(
    "path",
    [
        r"C:\Users\Test User\Wideo\Mój film (2026) - finał.mp4",
        r"C:\Users\User\Videos\$HOME and $(whoami) [take 2].mp4",
        r"C:\Users\User\Videos\it's `quoted` & ;done.mp4",
    ],
)
def test_awkward_paths_arrive_as_one_untouched_argument(harness: Harness, path: str) -> None:
    output = harness.engine_output(
        harness.run("workflow", "init", path, "--project-root", r"C:\Users\Test User\projekt")
    )

    assert output["engine_args"] == [
        "workflow",
        "init",
        path,
        "--project-root",
        r"C:\Users\Test User\projekt",
    ]


def _two_distributions(harness: Harness) -> None:
    harness.configure(
        listing=TWO_NO_DEFAULT,
        distributions={
            name: {"home": HOME, "engines": [LOCAL_ENGINE], "path": ["/usr/bin"]}
            for name in ("Ubuntu-24.04", "Ubuntu-22.04")
        },
    )


def test_several_distributions_without_a_default_stop_the_adapter(harness: Harness) -> None:
    _two_distributions(harness)

    result = harness.run("doctor")

    assert result.returncode == 3
    assert "no_distribution" in result.stderr
    assert all("--exec" not in call["argv"] for call in harness.calls)


@pytest.mark.parametrize(
    "selector",
    [
        ["-Distribution", "Ubuntu-22.04"],
        ["-Distribution:Ubuntu-22.04"],
        ["--distribution", "Ubuntu-22.04"],
    ],
)
def test_an_explicit_distribution_is_honoured(harness: Harness, selector: list[str]) -> None:
    _two_distributions(harness)

    output = harness.engine_output(harness.run(*selector, "doctor"))

    assert output["engine_args"] == ["doctor"]
    assert harness.calls[-1]["argv"][:2] == ["--distribution", "Ubuntu-22.04"]


def test_the_environment_can_name_the_distribution(harness: Harness) -> None:
    _two_distributions(harness)

    harness.engine_output(
        harness.run("doctor", env={"SOCIAL_VIDEO_WSL_DISTRIBUTION": "Ubuntu-24.04"})
    )

    assert harness.calls[-1]["argv"][:2] == ["--distribution", "Ubuntu-24.04"]


def test_everything_after_a_double_dash_belongs_to_the_engine(harness: Harness) -> None:
    output = harness.engine_output(harness.run("--", "-Distribution", "x", "-v"))

    assert output["engine_args"] == ["-Distribution", "x", "-v"]


def test_a_missing_engine_is_named_and_nothing_else_is_tried(harness: Harness) -> None:
    harness.configure(distributions={"Ubuntu": {"home": HOME, "engines": [], "path": []}})

    result = harness.run("doctor")

    assert result.returncode == 3
    assert "engine_missing" in result.stderr
    assert LOCAL_ENGINE in result.stderr


def test_an_explicit_engine_path_wins(harness: Harness) -> None:
    custom = "/opt/tools/social video/social-video-agent"
    harness.configure(distributions={"Ubuntu": {"home": HOME, "engines": [custom, LOCAL_ENGINE]}})

    harness.engine_output(harness.run("doctor", env={"SOCIAL_VIDEO_WSL_ENGINE": custom}))

    assert harness.calls[-1]["argv"][:4] == ["--distribution", "Ubuntu", "--exec", custom]
