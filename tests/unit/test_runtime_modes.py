"""Two machines, one job each: the agent's and the engine's.

Windows and WSL cannot be installed inside a test, and a test that shelled out
to the real `wsl.exe` would only pass on one laptop. So every outside fact --
the platform, whether wsl.exe exists, what it printed, whether the engine ran --
arrives through `Probes`, and these tests supply it.
"""

from __future__ import annotations

import subprocess

import pytest

from social_video.runtime import (
    DISTRIBUTION_ENV,
    MODE_ENV,
    Distribution,
    Probes,
    Problem,
    RuntimeMode,
    detect_runtime,
    parse_distributions,
)

#: What `wsl --list --verbose` prints. The header is localised, so it is never
#: matched by name.
ONE_WSL2 = """  NAME      STATE           VERSION
* Ubuntu    Running         2
"""
WSL1_ONLY = """  NAME      STATE           VERSION
* Legacy    Stopped         1
"""
TWO_WSL2_NO_DEFAULT = """  NAME              STATE           VERSION
  Ubuntu-24.04      Running         2
  Ubuntu-22.04      Stopped         2
"""
MIXED = """  NAME              STATE           VERSION
* Ubuntu-24.04      Running         2
  Legacy            Stopped         1
"""
LOCAL_ENGINE = "/home/user/.local/bin/social-video-agent"
POLISH_HEADER = """  NAZWA     STAN            WERSJA
* Ubuntu    Uruchomiono     2
"""


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["wsl.exe"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _windows(
    *,
    listing: str = ONE_WSL2,
    wsl: bool = True,
    engine: subprocess.CompletedProcess[str] | None = None,
    engine_installed: bool = True,
) -> Probes:
    """A Windows agent, with whatever WSL story the test needs."""
    calls: list[list[str]] = []

    def run(argv):
        calls.append(list(argv))
        if "--list" in argv:
            return (
                _completed(listing)
                if listing is not None
                else _completed(returncode=1, stderr="boom")
            )
        program = argv[argv.index("--exec") + 1]
        if program == "/usr/bin/printenv":
            return _completed("/home/user\n")
        if program == "/usr/bin/test":
            found = engine_installed and argv[-1] == LOCAL_ENGINE
            return _completed(returncode=0 if found else 1)
        return engine or _completed("0.5.0\n")

    probes = Probes(
        platform="win32",
        inside_wsl=lambda: False,
        which=lambda name: (
            "C:\\Windows\\System32\\wsl.exe" if (wsl and name.endswith("wsl.exe")) else None
        ),
        run=run,
    )
    probes.calls = calls  # type: ignore[attr-defined]
    return probes


# --- existing modes keep working --------------------------------------------


def test_an_agent_inside_wsl_is_unchanged() -> None:
    status = detect_runtime(env={}, probes=Probes(platform="linux", inside_wsl=lambda: True))

    assert status.mode is RuntimeMode.WSL_NATIVE
    assert status.usable
    assert status.distribution is None, "there is no boundary to cross"
    assert not status.explicit


def test_plain_linux_and_macos_are_unchanged() -> None:
    linux = detect_runtime(env={}, probes=Probes(platform="linux", inside_wsl=lambda: False))
    mac = detect_runtime(env={}, probes=Probes(platform="darwin", inside_wsl=lambda: False))

    assert linux.mode is RuntimeMode.LINUX_NATIVE and linux.usable
    assert mac.mode is RuntimeMode.MACOS_NATIVE and mac.usable


# --- the hybrid mode ---------------------------------------------------------


def test_a_windows_agent_delegates_into_wsl2() -> None:
    probes = _windows()

    status = detect_runtime(env={}, probes=probes)

    assert status.mode is RuntimeMode.WINDOWS_AGENT_WSL_RUNTIME
    assert status.usable
    assert status.distribution == Distribution(name="Ubuntu", version=2, default=True)
    assert status.engine_version == "0.5.0"
    assert status.to_dict()["engine_platform"] == "wsl"
    # The engine is found and asked for its version with `wsl --exec`, as argv:
    # no shell, so no login PATH is needed and nothing is parsed as syntax.
    engine_call = probes.calls[-1]
    assert engine_call == [
        "C:\\Windows\\System32\\wsl.exe",
        "--distribution",
        "Ubuntu",
        "--exec",
        LOCAL_ENGINE,
        "version",
    ]
    assert all("--" not in call for call in probes.calls)


def test_the_mode_can_be_pinned_explicitly() -> None:
    pinned = detect_runtime(
        env={MODE_ENV: "wsl-native"}, probes=Probes(platform="linux", inside_wsl=lambda: False)
    )

    assert pinned.mode is RuntimeMode.WSL_NATIVE
    assert pinned.explicit

    from_config = detect_runtime(
        env={},
        configured_mode="wsl-native",
        probes=Probes(platform="linux", inside_wsl=lambda: False),
    )
    assert from_config.mode is RuntimeMode.WSL_NATIVE and from_config.explicit


def test_an_unknown_mode_is_refused_by_name() -> None:
    status = detect_runtime(env={MODE_ENV: "windows-native"}, probes=_windows())

    assert Problem.UNSUPPORTED_PLATFORM in status.problems
    assert "is not a runtime mode" in status.detail


def test_the_terminal_preference_is_never_consulted() -> None:
    """A GUI's shell setting says nothing about where the agent runs."""
    noisy = {"WSLENV": "1", "TERM_PROGRAM": "vscode", "SHELL": "/bin/bash"}

    status = detect_runtime(
        env=noisy, probes=Probes(platform="win32", inside_wsl=lambda: False, which=lambda _: None)
    )

    assert status.mode is RuntimeMode.WINDOWS_AGENT_WSL_RUNTIME
    assert Problem.WSL_MISSING in status.problems


# --- choosing the distribution ----------------------------------------------


def test_an_explicit_distribution_is_honoured() -> None:
    status = detect_runtime(
        env={DISTRIBUTION_ENV: "Ubuntu-22.04"}, probes=_windows(listing=TWO_WSL2_NO_DEFAULT)
    )

    assert status.distribution is not None and status.distribution.name == "Ubuntu-22.04"


def test_a_missing_named_distribution_says_what_exists() -> None:
    status = detect_runtime(
        env={}, configured_distribution="Fedora", probes=_windows(listing=TWO_WSL2_NO_DEFAULT)
    )

    assert Problem.DISTRIBUTION_NOT_FOUND in status.problems
    assert "Ubuntu-24.04" in status.detail


def test_ambiguity_is_never_resolved_by_guessing() -> None:
    status = detect_runtime(env={}, probes=_windows(listing=TWO_WSL2_NO_DEFAULT))

    assert Problem.NO_DISTRIBUTION in status.problems
    assert "none is the default" in status.detail
    assert DISTRIBUTION_ENV in status.detail


def test_the_wsl_default_wins_over_a_wsl1_sibling() -> None:
    status = detect_runtime(env={}, probes=_windows(listing=MIXED))

    assert status.distribution is not None and status.distribution.name == "Ubuntu-24.04"


# --- each failure is distinguishable ----------------------------------------


def test_no_wsl_at_all() -> None:
    status = detect_runtime(env={}, probes=_windows(wsl=False))

    assert status.problems == (Problem.WSL_MISSING,)
    assert "wsl --install" in status.detail
    assert (
        "Nothing is installed" in status.detail or "nothing is installed" in status.detail.lower()
    )


def test_only_wsl1_is_installed() -> None:
    status = detect_runtime(env={}, probes=_windows(listing=WSL1_ONLY))

    assert status.problems == (Problem.WSL1_ONLY,)
    assert "--set-version" in status.detail


def test_wsl_works_but_the_engine_is_missing() -> None:
    status = detect_runtime(
        env={},
        probes=_windows(engine_installed=False),
    )

    assert status.problems == (Problem.ENGINE_MISSING,)
    assert "./scripts/wsl/bootstrap.sh" in status.detail
    assert "do not install FFmpeg, Node or Python on the Windows side" in status.detail
    # The distribution was found, so that half is not reported as broken.
    assert status.distribution is not None


def test_an_engine_that_crashes_is_not_reported_as_missing() -> None:
    status = detect_runtime(
        env={}, probes=_windows(engine=_completed(returncode=1, stderr="ImportError: pydantic"))
    )

    assert status.problems == (Problem.ENGINE_BROKEN,)


def test_a_broken_wsl_is_not_reported_as_absent() -> None:
    probes = _windows()

    def run(argv):
        if "--list" in argv:
            return _completed(returncode=1, stderr="WslRegisterDistribution failed")
        return _completed("0.5.0")

    probes.run = run
    status = detect_runtime(env={}, probes=probes)

    assert status.problems == (Problem.WSL_BROKEN,)
    assert "WslRegisterDistribution" in status.detail


# --- parsing -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("listing", "expected"),
    [
        (ONE_WSL2, (Distribution("Ubuntu", 2, True),)),
        (POLISH_HEADER, (Distribution("Ubuntu", 2, True),)),
        (
            TWO_WSL2_NO_DEFAULT,
            (Distribution("Ubuntu-24.04", 2, False), Distribution("Ubuntu-22.04", 2, False)),
        ),
    ],
    ids=["one", "localised-header", "two"],
)
def test_the_listing_parser_ignores_the_localised_header(
    listing: str, expected: tuple[Distribution, ...]
) -> None:
    assert parse_distributions(listing) == expected


def test_a_distribution_name_with_a_space_survives_parsing() -> None:
    listing = """  NAME              STATE           VERSION
* My Ubuntu Box     Running         2
"""

    assert parse_distributions(listing) == (Distribution("My Ubuntu Box", 2, True),)


# --- Stage 0 records both machines ------------------------------------------


def test_stage_0_records_the_runtime_and_keeps_session_facts_separate(tmp_path) -> None:
    from social_video.schemas.base import load_artifact
    from social_video.schemas.runtime import RuntimeRecord
    from social_video.schemas.visuals import CapabilityState
    from social_video.schemas.workflow import RemotionLicenseAttestation, Renderer
    from social_video.workflow import create_workflow
    from social_video.workspace.layout import Workspace

    project = tmp_path / "project"
    project.mkdir()
    (project / "input.mp4").write_bytes(b"fixture")
    workspace = Workspace.at(project / "edit")

    create_workflow(
        [project / "input.mp4"],
        workspace,
        project_root=project,
        renderer=Renderer.REMOTION,
        remotion_license_attestation=RemotionLicenseAttestation.FREE_LICENSE_ELIGIBLE,
    )

    record = load_artifact(RuntimeRecord, workspace.runtime_record)
    assert record.runtime_mode in {item.value for item in RuntimeMode}
    assert record.project_path == str(project.resolve())
    assert record.cache_root and "/mnt/" not in record.cache_root
    assert record.tools.cli is True
    assert record.remotion_license_attestation == "free_license_eligible"
    # The agent's own tools are never recorded here as project facts.
    assert record.session.native_imagegen is CapabilityState.UNKNOWN_TO_CLI
    assert record.session.canva is CapabilityState.UNKNOWN_TO_CLI
    assert record.session.session_scoped is True
    assert "Re-check" in record.session.recheck_on_resume


def test_a_workflow_resumes_without_re_detecting_the_runtime(tmp_path) -> None:
    """Resume reads workflow-state.json; the runtime record is a diagnosis, not a gate."""
    from social_video.schemas.workflow import RemotionLicenseAttestation, Renderer
    from social_video.workflow import create_workflow, load_workflow
    from social_video.workspace.layout import Workspace

    project = tmp_path / "project"
    project.mkdir()
    (project / "input.mp4").write_bytes(b"fixture")
    workspace = Workspace.at(project / "edit")
    created = create_workflow(
        [project / "input.mp4"],
        workspace,
        project_root=project,
        renderer=Renderer.REMOTION,
        remotion_license_attestation=RemotionLicenseAttestation.FREE_LICENSE_ELIGIBLE,
    )
    workspace.runtime_record.unlink()

    resumed = load_workflow(workspace)

    assert resumed == created
    assert not workspace.runtime_record.exists(), "resume must not need it"


def test_a_mounted_windows_source_keeps_its_heavy_files_in_the_linux_cache(
    tmp_path, monkeypatch
) -> None:
    """Render caches on /mnt/c are slow, and under OneDrive they get synced."""
    from social_video import paths
    from social_video.workspace.layout import Workspace

    source = tmp_path / "film.mp4"
    source.write_bytes(b"fixture")
    monkeypatch.setattr(paths, "is_wsl_mount_path", lambda value: True)
    monkeypatch.setattr("social_video.workspace.layout.is_wsl_mount_path", lambda value: True)
    monkeypatch.setattr("social_video.workspace.layout.app_home", lambda: tmp_path / "linux-cache")

    workspace = Workspace.for_source(source)

    assert str(workspace.root).startswith(str(tmp_path / "linux-cache"))
    assert "OneDrive" not in str(workspace.root)


def test_the_adapter_exists_and_refuses_the_unsafe_shortcuts() -> None:
    """The Windows adapter is part of the repository, and reviewable as text."""
    from pathlib import Path as _Path

    adapter = _Path(__file__).resolve().parents[2] / "scripts/windows/social-video-agent.ps1"
    assert adapter.is_file()
    text = adapter.read_text(encoding="utf-8")
    code = _executable_lines(text)

    # The things it must never do, checked against the code rather than the
    # comments -- the help block names them in order to disclaim them.
    assert "Invoke-Expression" not in code
    assert "sh -lc" not in code
    assert "ffmpeg.exe" not in code
    assert "python.exe" not in code and "node.exe" not in code
    # The things it must do.
    assert "exit $LASTEXITCODE" in code
    assert "--distribution" in code
    assert "@engineArgs" in code, "arguments are passed as an array, never joined"
    assert "--exec" in code, "the engine is started without the Linux shell"
    for problem in ("wsl_missing", "wsl_broken", "no_distribution", "wsl1_only", "engine_missing"):
        assert problem in code, problem


def _executable_lines(text: str) -> str:
    """The script without its help block or comment lines."""
    body = text.split("#>", 1)[-1]
    return "\n".join(line for line in body.splitlines() if not line.strip().startswith("#"))


# --- the engine's side of the hybrid mode -----------------------------------


def _inside_wsl() -> Probes:
    def no_wsl_exe(argv):
        raise AssertionError(f"the engine must not call wsl.exe back: {argv}")

    return Probes(platform="linux", inside_wsl=lambda: True, run=no_wsl_exe)


def test_the_engine_knows_a_windows_agent_started_it(monkeypatch: pytest.MonkeyPatch) -> None:
    from social_video import __version__, runtime

    monkeypatch.setattr(runtime, "_wsl_version", lambda: 2)

    status = detect_runtime(
        env={"SOCIAL_VIDEO_AGENT_PLATFORM": "windows", DISTRIBUTION_ENV: "Ubuntu-24.04"},
        probes=_inside_wsl(),
    )

    assert status.mode is RuntimeMode.WINDOWS_AGENT_WSL_RUNTIME
    assert status.usable
    assert status.agent_platform == "win32"
    assert status.distribution == Distribution(name="Ubuntu-24.04", version=2)
    assert status.engine_version == __version__
    assert status.to_dict()["engine_platform"] == "wsl"


def test_without_the_adapter_inside_wsl_is_still_wsl_native() -> None:
    status = detect_runtime(env={"WSL_DISTRO_NAME": "Ubuntu"}, probes=_inside_wsl())

    assert status.mode is RuntimeMode.WSL_NATIVE


def test_the_engine_side_falls_back_to_wsls_own_distribution_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from social_video import runtime

    monkeypatch.setattr(runtime, "_wsl_version", lambda: 2)

    status = detect_runtime(
        env={"SOCIAL_VIDEO_AGENT_PLATFORM": "windows", "WSL_DISTRO_NAME": "Debian"},
        probes=_inside_wsl(),
    )

    assert status.distribution is not None and status.distribution.name == "Debian"


def test_a_utf16_listing_decoded_as_utf8_still_parses() -> None:
    """What subprocess hands back from `wsl --list --verbose` on Windows."""
    raw = "  NAME      STATE           VERSION\r\n* Ubuntu    Running         2\r\n"
    garbled = raw.encode("utf-16-le").decode("utf-8")
    assert "\x00" in garbled

    assert parse_distributions(garbled) == (Distribution("Ubuntu", 2, True),)


def test_stage_0_through_the_adapter_records_the_hybrid_mode(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from social_video import paths, runtime
    from social_video.schemas.base import load_artifact
    from social_video.schemas.runtime import RuntimeRecord
    from social_video.schemas.workflow import Renderer
    from social_video.workflow import create_workflow
    from social_video.workspace.layout import Workspace

    monkeypatch.setattr(paths, "is_wsl", lambda: True)
    monkeypatch.setattr(runtime, "_wsl_version", lambda: 2)
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setenv("SOCIAL_VIDEO_AGENT_PLATFORM", "windows")
    monkeypatch.setenv(DISTRIBUTION_ENV, "Ubuntu")
    monkeypatch.delenv(MODE_ENV, raising=False)
    project = tmp_path / "project"
    project.mkdir()
    (project / "input.mp4").write_bytes(b"fixture")
    workspace = Workspace.at(project / "edit")

    create_workflow(
        [project / "input.mp4"], workspace, project_root=project, renderer=Renderer.FFMPEG
    )

    record = load_artifact(RuntimeRecord, workspace.runtime_record)
    assert record.runtime_mode == "windows-agent-wsl-runtime"
    assert record.agent_platform == "win32"
    assert record.engine_platform == "wsl"
    assert record.wsl_distribution == "Ubuntu"
    assert record.problems == []


def test_doctor_through_the_adapter_reports_the_hybrid_mode_without_false_alarms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from social_video import doctor, paths, runtime

    monkeypatch.setattr(paths, "is_wsl", lambda: True)
    monkeypatch.setattr(runtime, "_wsl_version", lambda: 2)
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setenv("SOCIAL_VIDEO_AGENT_PLATFORM", "windows")
    monkeypatch.setenv(DISTRIBUTION_ENV, "Ubuntu")
    monkeypatch.delenv(MODE_ENV, raising=False)
    report = doctor.DoctorReport()

    doctor._check_runtime(report)

    by_name = {check.name: check for check in report.checks}
    assert by_name["runtime mode"].ok
    assert by_name["runtime mode"].detail.startswith("windows-agent-wsl-runtime")
    assert all(by_name[name].ok for name in ("wsl2", "wsl distribution", "wsl engine"))
