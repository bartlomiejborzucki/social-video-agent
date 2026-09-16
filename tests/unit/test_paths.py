from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from social_video import paths
from social_video.workspace import layout


@pytest.mark.parametrize(
    "value",
    [r"C:\Users\Test User\Videos\Mój film.mp4", "D:/Media/video.mp4"],
)
def test_recognizes_windows_drive_paths(value):
    assert paths.is_windows_drive_path(value)


@pytest.mark.parametrize("value", ["/mnt/c/video.mp4", "relative/video.mp4", "C:relative"])
def test_does_not_misclassify_linux_or_drive_relative_paths(value):
    assert not paths.is_windows_drive_path(value)


def test_preserves_linux_unicode_path(tmp_path):
    source = tmp_path / "Mój film ąćęłńóśźż.mp4"
    source.touch()
    assert paths.normalize_user_path(source, must_exist=True) == source.resolve()


@pytest.mark.skipif(os.name == "nt", reason="WSL uses POSIX pathlib semantics")
def test_windows_path_uses_wslpath_without_a_shell(monkeypatch):
    calls = []
    monkeypatch.setattr(paths, "is_wsl", lambda: True)
    monkeypatch.setattr(paths.shutil, "which", lambda name: "/usr/bin/wslpath")

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv, 0, "/mnt/c/Users/Test User/Videos/Mój film.mp4\n", ""
        )

    monkeypatch.setattr(paths.subprocess, "run", fake_run)
    result = paths.normalize_user_path(r"C:\Users\Test User\Videos\Mój film.mp4")
    assert result == Path("/mnt/c/Users/Test User/Videos/Mój film.mp4")
    assert calls[0][0] == [
        "/usr/bin/wslpath",
        "-u",
        r"C:\Users\Test User\Videos\Mój film.mp4",
    ]
    assert "shell" not in calls[0][1]


def test_windows_path_outside_wsl_has_clear_error(monkeypatch):
    monkeypatch.setattr(paths, "is_wsl", lambda: False)
    with pytest.raises(ValueError, match="inside WSL"):
        paths.normalize_user_path(r"C:\video.mp4")


def test_missing_path_validation(tmp_path):
    with pytest.raises(FileNotFoundError, match="does not exist"):
        paths.normalize_user_path(tmp_path / "missing.mp4", must_exist=True)


def test_mounted_source_gets_linux_cache_workspace(tmp_path, monkeypatch):
    source = Path("/mnt/c/Users/Test User/Videos/Mój film.mp4")
    monkeypatch.setattr(layout, "normalize_user_path", lambda *_args, **_kwargs: source)
    monkeypatch.setattr(layout, "app_home", lambda: tmp_path / "cache")
    workspace = layout.Workspace.for_source(r"C:\Users\Test User\Videos\Mój film.mp4")
    assert workspace.root.is_relative_to(tmp_path / "cache" / "workspaces")
    assert "M-j-film" in workspace.root.parent.name


def test_linux_source_keeps_inspectable_adjacent_workspace(tmp_path):
    source = tmp_path / "source.mp4"
    source.touch()
    assert layout.Workspace.for_source(source).root == tmp_path / "edit"
