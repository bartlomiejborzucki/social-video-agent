"""Every path crosses the Windows/WSL boundary exactly once, or not at all.

The failures these prevent are all silent: `/mnt/c/mnt/c/...` from converting
twice, a lost space from joining a command string, a quote that became part of
the filename, and a `C:\\...` path handed straight to a Linux FFmpeg.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from social_video import paths

WINDOWS_CASES = {
    "plain": (r"C:\Users\User\Videos\film.mp4", "/mnt/c/Users/User/Videos/film.mp4"),
    "spaces": (
        r"C:\Users\Test User\Videos\Mój film testowy.mp4",
        "/mnt/c/Users/Test User/Videos/Mój film testowy.mp4",
    ),
    "polish": (
        r"C:\Users\User\Wideo\Zażółć gęślą jaźń.mp4",
        "/mnt/c/Users/User/Wideo/Zażółć gęślą jaźń.mp4",
    ),
    "brackets-and-dashes": (
        r"C:\Users\User\Videos\rozmowa (2026-09-21) - finał.mp4",
        "/mnt/c/Users/User/Videos/rozmowa (2026-09-21) - finał.mp4",
    ),
    "onedrive": (
        r"C:\Users\User\OneDrive\projects\reel\source.mp4",
        "/mnt/c/Users/User/OneDrive/projects/reel/source.mp4",
    ),
    "other-drive": (r"D:\Media\clip.mp4", "/mnt/d/Media/clip.mp4"),
}


#: The Windows/WSL boundary only exists on a Linux host. Elsewhere `resolve()`
#: is native and rightly so: on Windows a rootless `/mnt/c/...` gains the
#: current drive, and on macOS `/home/...` crosses an autofs firmlink. Those
#: hosts still run the recognisers below, which are pure string logic.
only_on_linux = pytest.mark.skipif(
    sys.platform != "linux", reason="path translation across the WSL boundary is Linux behaviour"
)


@pytest.fixture
def in_wsl(monkeypatch: pytest.MonkeyPatch):
    """Pretend to be inside WSL, with a wslpath that behaves like the real one."""
    monkeypatch.setattr(paths, "is_wsl", lambda: True)
    monkeypatch.setattr(paths.shutil, "which", lambda name: "/usr/bin/wslpath")
    seen: list[list[str]] = []

    def fake_run(argv, **kwargs):
        seen.append(list(argv))
        raw = argv[-1]
        drive = raw[0].lower()
        rest = raw[2:].replace("\\", "/").lstrip("/")
        return subprocess.CompletedProcess(argv, 0, stdout=f"/mnt/{drive}/{rest}\n", stderr="")

    monkeypatch.setattr(paths.subprocess, "run", fake_run)
    return seen


@only_on_linux
@pytest.mark.parametrize("case", list(WINDOWS_CASES), ids=list(WINDOWS_CASES))
def test_a_windows_path_is_translated_by_wslpath(case: str, in_wsl) -> None:
    raw, expected = WINDOWS_CASES[case]

    result = paths.normalize_user_path(raw)

    assert result == Path(expected)
    # wslpath is given an argument array, so nothing in the name is shell syntax.
    assert in_wsl[-1] == ["/usr/bin/wslpath", "-u", raw]


@only_on_linux
@pytest.mark.parametrize("case", list(WINDOWS_CASES), ids=list(WINDOWS_CASES))
def test_normalising_twice_is_the_same_as_once(case: str, in_wsl) -> None:
    raw, expected = WINDOWS_CASES[case]

    once = paths.normalize_user_path(raw)
    twice = paths.normalize_user_path(once)

    assert once == twice == Path(expected)
    assert "/mnt/c/mnt/" not in str(twice)
    assert str(twice).count("/mnt/") <= 1


@only_on_linux
def test_an_already_converted_mount_path_is_left_alone(in_wsl) -> None:
    result = paths.normalize_user_path("/mnt/c/Users/User/Videos/film.mp4")

    assert result == Path("/mnt/c/Users/User/Videos/film.mp4")
    assert in_wsl == [], "a Linux path needs no conversion"


@only_on_linux
def test_a_linux_path_is_never_sent_through_wslpath(in_wsl) -> None:
    result = paths.normalize_user_path("/home/user/projects/reel/source.mp4")

    assert result == Path("/home/user/projects/reel/source.mp4")
    assert in_wsl == []


@only_on_linux
def test_a_quoted_path_does_not_keep_its_quotes(in_wsl) -> None:
    """A copied Windows path arrives quoted often enough to matter."""
    result = paths.normalize_user_path('"C:\\Users\\Test User\\Videos\\Mój film.mp4"')

    assert result == Path("/mnt/c/Users/Test User/Videos/Mój film.mp4")
    assert '"' not in str(result)


@only_on_linux
@pytest.mark.parametrize(
    "raw",
    [
        r"\\wsl$\Ubuntu\home\user\projects\reel\source.mp4",
        r"\\wsl.localhost\Ubuntu\home\user\projects\reel\source.mp4",
    ],
    ids=["wsl$", "wsl.localhost"],
)
def test_a_wsl_unc_path_resolves_inside_its_own_distribution(
    raw: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(paths, "is_wsl", lambda: True)
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")

    assert paths.is_wsl_unc_path(raw)
    assert paths.normalize_user_path(raw) == Path("/home/user/projects/reel/source.mp4")


def test_a_unc_path_for_another_distribution_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Another distribution's filesystem is not reachable as a plain path."""
    monkeypatch.setattr(paths, "is_wsl", lambda: True)
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")

    with pytest.raises(ValueError, match="is running in 'Ubuntu'"):
        paths.normalize_user_path(r"\\wsl$\Debian\home\user\clip.mp4")


@only_on_linux
def test_a_windows_path_outside_wsl_is_refused_rather_than_guessed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guessing /mnt/c on a machine with no such mount would fail far away."""
    monkeypatch.setattr(paths, "is_wsl", lambda: False)

    with pytest.raises(ValueError, match="only be translated when running inside WSL"):
        paths.normalize_user_path(r"C:\Users\User\Videos\film.mp4")
    with pytest.raises(ValueError, match="only be resolved from inside WSL"):
        paths.normalize_user_path(r"\\wsl$\Ubuntu\home\user\clip.mp4")


def test_recognisers_do_not_overlap() -> None:
    assert paths.is_windows_drive_path(r"C:\x\y.mp4")
    assert not paths.is_windows_drive_path("/mnt/c/x/y.mp4")
    assert paths.is_wsl_mount_path("/mnt/c/x/y.mp4")
    assert not paths.is_wsl_mount_path("/home/user/y.mp4")
    assert paths.is_wsl_unc_path(r"\\wsl$\Ubuntu\home\u\y.mp4")
    assert not paths.is_wsl_unc_path(r"C:\x\y.mp4")


@only_on_linux
def test_the_heavy_cache_stays_off_the_windows_mount(monkeypatch: pytest.MonkeyPatch) -> None:
    """Render caches on /mnt/c are slow and, under OneDrive, get synced."""
    monkeypatch.delenv("SOCIAL_VIDEO_HOME", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", "/home/user/.cache")

    home = paths.app_home()

    assert not paths.is_wsl_mount_path(home)
    assert str(home).startswith("/home/user/.cache")
