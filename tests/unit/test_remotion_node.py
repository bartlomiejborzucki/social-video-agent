"""The Node step of a Remotion render: progress, the time limit and bundle reuse."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from social_video import remotion_node
from social_video.errors import RemotionError
from social_video.remotion_node import (
    BUNDLE_ENV,
    KEEP_BUNDLES,
    PROGRESS_PREFIX,
    RenderProgress,
    bundle_cache_dir,
    bundle_key,
    ensure_bundle,
    parse_progress,
    progress_to,
    run_node,
    stage_serve_dir,
)
from social_video.remotion_runtime import RemotionRuntime


def _script(tmp_path: Path, body: str) -> list[str]:
    """A stand-in for `node render.mjs`: any program that prints and exits."""
    path = tmp_path / "stand_in.py"
    path.write_text(body, encoding="utf-8")
    return [sys.executable, str(path)]


def _runtime(tmp_path: Path) -> RemotionRuntime:
    root = tmp_path / "compositor"
    (root / "remotion").mkdir(parents=True)
    (root / "scripts" / "remotion").mkdir(parents=True)
    (root / "remotion" / "index.ts").write_text("export {};\n", encoding="utf-8")
    (root / "remotion" / "Scene.tsx").write_text("export const a = 1;\n", encoding="utf-8")
    (root / "scripts" / "remotion" / "render.mjs").write_text("// render\n", encoding="utf-8")
    (root / "package-lock.json").write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
    (root / "tsconfig.json").write_text("{}\n", encoding="utf-8")
    return RemotionRuntime(root, from_checkout=True)


def test_a_progress_line_is_data_and_anything_else_is_not() -> None:
    line = PROGRESS_PREFIX + (
        '{"stage": "render", "progress": 0.5, "rendered": 90, "total": 180, "elapsed_ms": 4200}'
    )

    progress = parse_progress(line)

    assert progress == RenderProgress("render", 0.5, rendered=90, total=180, elapsed_s=4.2)
    assert progress.describe() == "frame 90 of 180"
    assert parse_progress(PROGRESS_PREFIX + '{"stage": "bundle", "progress": 7}') == (
        RenderProgress("bundle", 1.0)
    )
    assert parse_progress("Rendered 90/180") is None
    assert parse_progress(PROGRESS_PREFIX + "{not json") is None


def test_progress_reaches_the_sink_and_stays_out_of_the_output(tmp_path: Path) -> None:
    argv = _script(
        tmp_path,
        "import sys\n"
        f"prefix = {PROGRESS_PREFIX!r}\n"
        'print("starting")\n'
        'print(prefix + \'{"stage": "render", "progress": 0.25, "rendered": 1, "total": 4}\','
        " file=sys.stderr)\n"
        'print(prefix + \'{"stage": "render", "progress": 1, "rendered": 4, "total": 4}\','
        " file=sys.stderr)\n"
        'print("warning: something Chrome said", file=sys.stderr)\n'
        "sys.exit(3)\n",
    )
    seen: list[RenderProgress] = []

    with progress_to(seen.append):
        code, said = run_node(argv, cwd=tmp_path, timeout=30, desc="The stand-in")

    assert code == 3
    assert [p.rendered for p in seen] == [1, 4] and seen[-1].fraction == 1.0
    assert "starting" in said and "something Chrome said" in said
    assert PROGRESS_PREFIX not in said


def test_a_sink_that_fails_does_not_stop_the_render(tmp_path: Path) -> None:
    argv = _script(
        tmp_path,
        f'print({PROGRESS_PREFIX!r} + \'{{"stage": "render", "progress": 0.5}}\')\nprint("done")\n',
    )

    def broken(_progress: RenderProgress) -> None:
        raise RuntimeError("the display went away")

    with progress_to(broken):
        code, said = run_node(argv, cwd=tmp_path, timeout=30, desc="The stand-in")

    assert code == 0 and "done" in said


def test_a_render_that_never_finishes_is_stopped_and_reported(tmp_path: Path) -> None:
    argv = _script(tmp_path, 'import time\nprint("drawing", flush=True)\ntime.sleep(600)\n')
    started = time.monotonic()

    with pytest.raises(RemotionError, match=r"did not finish within 1 s") as caught:
        run_node(argv, cwd=tmp_path, timeout=1, desc="The stand-in")

    assert time.monotonic() - started < 30
    assert "drawing" in str(caught.value)


def test_the_bundle_key_follows_the_sources(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    before = bundle_key(runtime, None)

    assert bundle_key(runtime, None) == before
    (runtime.root / "remotion" / "Scene.tsx").write_text("export const a = 2;\n", encoding="utf-8")
    edited = bundle_key(runtime, None)
    assert edited != before
    (runtime.root / "package-lock.json").write_text('{"lockfileVersion": 4}\n', encoding="utf-8")
    assert bundle_key(runtime, None) != edited

    custom = tmp_path / "custom-graphics"
    custom.mkdir()
    registry = custom / "registry.tsx"
    registry.write_text("export const CUSTOM_GRAPHICS = {};\n", encoding="utf-8")
    with_registry = bundle_key(runtime, registry)
    assert with_registry != bundle_key(runtime, None)
    (custom / "Licznik.tsx").write_text("export default () => null;\n", encoding="utf-8")
    assert bundle_key(runtime, registry) != with_registry


def _fake_build(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    builds: list[list[str]] = []

    def node(argv, **kwargs):
        builds.append(argv)
        out = Path(argv[4])
        (out / "public").mkdir(parents=True)
        (out / "index.html").write_text("<html></html>", encoding="utf-8")
        (out / "bundle.js").write_text("// built\n", encoding="utf-8")
        return 0, ""

    monkeypatch.setattr(remotion_node, "run_node", node)
    return builds


def test_a_bundle_is_built_once_and_reused(tmp_path: Path, monkeypatch) -> None:
    cache = tmp_path / "bundles"
    monkeypatch.setenv(BUNDLE_ENV, str(cache))
    runtime = _runtime(tmp_path)
    builds = _fake_build(monkeypatch)

    first = ensure_bundle("node", runtime, None, tmp_path / "work-1")
    second = ensure_bundle("node", runtime, None, tmp_path / "work-2")

    assert first == second == cache / bundle_key(runtime, None)
    assert len(builds) == 1 and builds[0][2] == "bundle"
    assert not (first / "public").exists(), "a kept bundle holds no reel's files"
    assert not list(cache.glob(".*.partial"))

    (runtime.root / "remotion" / "Scene.tsx").write_text("export const a = 3;\n", encoding="utf-8")
    assert ensure_bundle("node", runtime, None, tmp_path / "work-3") != first
    assert len(builds) == 2


def test_reuse_can_be_switched_off(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(BUNDLE_ENV, "off")
    runtime = _runtime(tmp_path)
    builds = _fake_build(monkeypatch)
    work = tmp_path / "work"

    assert bundle_cache_dir() is None
    assert ensure_bundle("node", runtime, None, work) == work / "bundle"
    assert ensure_bundle("node", runtime, None, tmp_path / "work-2").parent == tmp_path / "work-2"
    assert len(builds) == 2


def test_a_build_that_fails_leaves_nothing_behind(tmp_path: Path, monkeypatch) -> None:
    cache = tmp_path / "bundles"
    monkeypatch.setenv(BUNDLE_ENV, str(cache))
    monkeypatch.setattr(remotion_node, "run_node", lambda argv, **kwargs: (1, "Module not found"))

    with pytest.raises(RemotionError, match="Module not found"):
        ensure_bundle("node", _runtime(tmp_path), None, tmp_path / "work")

    assert not [entry for entry in cache.iterdir()]


def test_only_the_newest_bundles_are_kept(tmp_path: Path, monkeypatch) -> None:
    cache = tmp_path / "bundles"
    monkeypatch.setenv(BUNDLE_ENV, str(cache))
    runtime = _runtime(tmp_path)
    _fake_build(monkeypatch)
    made = []
    for version in range(KEEP_BUNDLES + 2):
        (runtime.root / "remotion" / "Scene.tsx").write_text(
            f"export const a = {version};\n", encoding="utf-8"
        )
        bundle = ensure_bundle("node", runtime, None, tmp_path / f"work-{version}")
        os.utime(bundle, (version + 1000, version + 1000))
        made.append(bundle)

    kept = sorted(entry for entry in cache.iterdir() if not entry.name.startswith("."))

    assert len(kept) == KEEP_BUNDLES
    assert made[-1] in kept and made[0] not in kept


def test_a_render_is_served_from_its_own_copy_of_a_kept_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "bundles" / "kept"
    (bundle / "assets").mkdir(parents=True)
    (bundle / "index.html").write_text("<html></html>", encoding="utf-8")
    (bundle / "assets" / "chunk.js").write_text("// chunk\n", encoding="utf-8")
    work = tmp_path / "work"
    public = work / "public"
    public.mkdir(parents=True)
    (public / "base.mp4").write_bytes(b"picture")

    serve = stage_serve_dir(bundle, public, work)

    assert serve == work / "serve" and serve != bundle
    assert (serve / "assets" / "chunk.js").read_text(encoding="utf-8") == "// chunk\n"
    assert (serve / "public" / "base.mp4").read_bytes() == b"picture"
    assert not public.exists(), "moved, so the base video exists once"
    assert sorted(p.name for p in bundle.iterdir()) == ["assets", "index.html"]


def test_a_bundle_built_for_one_render_is_served_in_place(tmp_path: Path) -> None:
    work = tmp_path / "work"
    bundle = work / "bundle"
    bundle.mkdir(parents=True)
    (bundle / "index.html").write_text("<html></html>", encoding="utf-8")
    public = work / "public"
    public.mkdir()
    (public / "base.mp4").write_bytes(b"picture")

    assert stage_serve_dir(bundle, public, work) == bundle
    assert (bundle / "public" / "base.mp4").is_file()
