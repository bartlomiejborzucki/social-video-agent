"""The compositor is found in a checkout and set up from an installed wheel."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from social_video import remotion_runtime
from social_video.errors import SocialVideoError
from social_video.remotion_runtime import ASSETS, install_runtime, locate_runtime

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pretend to be a wheel: no checkout, compositor files under package data."""
    bundled = tmp_path / "site-packages" / "social_video" / "_remotion"
    for asset in ASSETS:
        path = bundled / asset
        if asset == "remotion":
            path.mkdir(parents=True)
            (path / "index.ts").write_text("export {};\n", encoding="utf-8")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(remotion_runtime, "_checkout_root", lambda: None)
    monkeypatch.setattr(remotion_runtime, "_BUNDLED", bundled)
    monkeypatch.setenv("SOCIAL_VIDEO_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(remotion_runtime.shutil, "which", lambda name: f"/usr/bin/{name}")
    return bundled


def test_a_checkout_uses_its_own_sources() -> None:
    runtime = locate_runtime()

    assert runtime is not None
    assert runtime.from_checkout
    assert runtime.root == ROOT
    assert runtime.entry == ROOT / "remotion" / "index.ts"


def test_an_installed_package_renders_from_the_app_cache(installed: Path, tmp_path: Path) -> None:
    runtime = locate_runtime()

    assert runtime is not None
    assert not runtime.from_checkout
    assert runtime.root.is_relative_to(tmp_path / "home")
    assert not runtime.dependencies_installed
    assert "--install-remotion" in runtime.install_hint


def test_a_build_without_the_compositor_is_reported_as_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(remotion_runtime, "_checkout_root", lambda: None)
    monkeypatch.setattr(remotion_runtime, "_BUNDLED", tmp_path / "missing")

    assert locate_runtime() is None


def test_install_stages_the_bundle_and_moves_it_into_place(
    installed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], Path]] = []

    def fake_run(args, **kwargs):
        assert isinstance(args, list)
        assert "shell" not in kwargs
        cwd = Path(kwargs["cwd"])
        calls.append((args, cwd))
        if args[1] == "ci":
            (cwd / "node_modules" / "remotion").mkdir(parents=True)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(remotion_runtime.subprocess, "run", fake_run)

    runtime = install_runtime()

    assert runtime.dependencies_installed
    assert all((runtime.root / asset).exists() for asset in ASSETS)
    assert [args[1:3] for args, _ in calls] == [["ci", "--no-audit"], ["--no-install", "remotion"]]
    # Both steps ran in the staging copy, never in the live directory.
    assert all(cwd != runtime.root for _, cwd in calls)
    assert [p.name for p in runtime.root.parent.iterdir()] == [runtime.root.name]


def test_a_failed_install_leaves_nothing_that_looks_usable(
    installed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, "", "npm error code E403")

    monkeypatch.setattr(remotion_runtime.subprocess, "run", fake_run)

    with pytest.raises(SocialVideoError, match="E403"):
        install_runtime()

    runtime = locate_runtime()
    assert runtime is not None
    assert not runtime.root.exists()
    assert list(runtime.root.parent.iterdir()) == []


def test_the_wheel_ships_every_compositor_asset() -> None:
    tomllib = pytest.importorskip("tomllib")
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    shipped = config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]

    assert shipped == {asset: f"social_video/_remotion/{asset}" for asset in ASSETS}
