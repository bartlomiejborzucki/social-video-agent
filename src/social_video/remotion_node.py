"""Run the compositor's Node script: its progress, its time limit, its bundle.

`scripts/remotion/render.mjs` has two steps. ``bundle`` builds the compositor
(webpack, tens of megabytes) and ``render`` draws one video from a built
bundle. The bundle depends only on the compositor's own sources, so it is
built once per version of them and reused by every render and every variant;
what belongs to one reel -- the base video, fonts, plates -- is placed next to
a private copy of it as ``public/`` and never enters the kept bundle.

Both steps print progress lines the caller turns into a callback, and both run
under a wall-clock limit that stops the whole process group, so a browser that
never answers ends as an error rather than as a session that waits for ever.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from social_video.errors import RemotionError
from social_video.paths import app_home
from social_video.remotion_runtime import RemotionRuntime

log = logging.getLogger(__name__)

#: `render.mjs` prints one JSON object per line behind this prefix.
PROGRESS_PREFIX = "@@social-video-progress "
#: A directory that moves the kept bundles, or ``off`` to build one per render.
BUNDLE_ENV = "SOCIAL_VIDEO_REMOTION_BUNDLE_CACHE"
#: Bundles kept, most recently used first. A reel with `custom` components has
#: a bundle of its own, so more than one is normal.
KEEP_BUNDLES = 3
BUNDLE_TIMEOUT_S = 1800
#: An abandoned build is removed once it is this old.
STALE_BUILD_S = 24 * 3600


@dataclass(frozen=True)
class RenderProgress:
    """Where the compositor is: building its bundle, or drawing frames."""

    stage: str
    #: 0 to 1 within the stage.
    fraction: float
    rendered: int = 0
    total: int = 0
    elapsed_s: float = 0.0

    def describe(self) -> str:
        if self.stage == "render" and self.total:
            return f"frame {self.rendered} of {self.total}"
        return "building the compositor"


ProgressSink = Callable[[RenderProgress], None]

_sink: ProgressSink | None = None


@contextlib.contextmanager
def progress_to(sink: ProgressSink | None) -> Iterator[None]:
    """Send the progress of every render inside the block to ``sink``.

    A render is reached through several layers (delivery, variants, the
    pipeline); this lets the one caller that owns a terminal show progress
    without each of them carrying a callback.
    """
    global _sink
    previous, _sink = _sink, sink
    try:
        yield
    finally:
        _sink = previous


def _log_sink() -> ProgressSink:
    """Progress for a run nobody watches: one log line per quarter of a render."""
    reported: set[tuple[str, int]] = set()

    def sink(progress: RenderProgress) -> None:
        if progress.stage != "render":
            return
        quarter = int(progress.fraction * 4)
        if quarter == 0 or (progress.stage, quarter) in reported:
            return
        reported.add((progress.stage, quarter))
        log.info(
            "Remotion: %d %% (%s, %.0f s)",
            quarter * 25,
            progress.describe(),
            progress.elapsed_s,
        )

    return sink


def parse_progress(line: str) -> RenderProgress | None:
    """One progress line as data; ``None`` for anything else the script prints."""
    if not line.startswith(PROGRESS_PREFIX):
        return None
    try:
        data = json.loads(line[len(PROGRESS_PREFIX) :])
        return RenderProgress(
            stage=str(data["stage"]),
            fraction=min(1.0, max(0.0, float(data.get("progress", 0.0)))),
            rendered=int(data.get("rendered", 0)),
            total=int(data.get("total", 0)),
            elapsed_s=float(data.get("elapsed_ms", 0)) / 1000.0,
        )
    except (ValueError, KeyError, TypeError):
        return None


def run_node(argv: list[str], *, cwd: Path, timeout: float, desc: str) -> tuple[int, str]:
    """Run the Node script; returns its exit code and the tail of what it said.

    Progress lines go to the sink set by :func:`progress_to` (a log line per
    quarter when there is none) and are kept out of the returned text. Past
    ``timeout`` seconds the process and everything it started are stopped and
    a :class:`RemotionError` says so.
    """
    sink = _sink or _log_sink()
    lines: deque[str] = deque(maxlen=200)
    # Its own process group, so stopping it also stops the browser it starts.
    own_group = {"start_new_session": True} if os.name == "posix" else {}
    proc = subprocess.Popen(  # argv list, never a shell string
        argv,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        **own_group,  # type: ignore[call-overload]
    )

    def pump() -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            progress = parse_progress(line)
            if progress is None:
                if not line.startswith(PROGRESS_PREFIX):
                    lines.append(line)
                continue
            try:
                sink(progress)
            except Exception:  # a display that fails must not stop a render
                log.debug("progress sink failed", exc_info=True)

    reader = threading.Thread(target=pump, name="remotion-output", daemon=True)
    reader.start()
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _stop(proc)
        reader.join(5)
        tail = "\n".join(list(lines)[-30:])
        raise RemotionError(
            f"{desc} did not finish within {timeout:.0f} s and was stopped."
            + (f"\n{tail}" if tail else "")
        ) from exc
    except BaseException:
        # Ctrl-C, or the caller being torn down: do not leave a browser behind.
        _stop(proc)
        raise
    reader.join(10)
    return code, "\n".join(lines)


def _stop(proc: subprocess.Popen[str]) -> None:
    """End the process and, where the platform has them, its whole group."""

    def send(sig: int) -> None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            if os.name == "posix":
                os.killpg(proc.pid, sig)
            else:
                proc.send_signal(sig)

    send(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            send(signal.SIGKILL)
        else:
            proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=10)


# -- the bundle -------------------------------------------------------------


def bundle_cache_dir() -> Path | None:
    """Where built bundles are kept, or ``None`` when reuse is switched off."""
    raw = os.environ.get(BUNDLE_ENV, "").strip()
    if raw.casefold() in {"off", "0", "false", "no"}:
        return None
    if raw:
        return Path(raw).expanduser().resolve()
    return app_home() / "remotion-bundles"


def bundle_key(runtime: RemotionRuntime, registry: Path | None) -> str:
    """A name for the bundle these sources build: changes when any of them does.

    Covers the compositions, the render script, the npm lockfile (so a Remotion
    upgrade rebuilds) and the checked `custom` components of this reel.
    """
    digest = hashlib.blake2b(digest_size=16)
    root = runtime.root
    files = [p for p in sorted((root / "remotion").rglob("*")) if p.is_file()]
    files += [runtime.script, root / "package-lock.json", root / "tsconfig.json"]
    if registry is not None:
        files += [p for p in sorted(registry.parent.iterdir()) if p.is_file()]
    # The built page records where the compositor lives.
    digest.update(str(root).encode("utf-8"))
    for path in files:
        name = path.name if registry is not None and path.parent == registry.parent else None
        label = f"custom/{name}" if name else str(path.relative_to(root))
        digest.update(b"\0" + label.encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def ensure_bundle(node: str, runtime: RemotionRuntime, registry: Path | None, work: Path) -> Path:
    """The built compositor for these sources: reused when kept, built when not.

    A build goes into a private sibling and is renamed into place, so two
    renders that start together never see half a bundle; whichever finishes
    second keeps the first one's.
    """
    cache = bundle_cache_dir()
    if cache is None:
        target = work / "bundle"
        _build(node, runtime, registry, target, work)
        return target
    target = cache / bundle_key(runtime, registry)
    if _usable(target):
        with contextlib.suppress(OSError):
            os.utime(target)  # most recently used
        log.debug("reusing the compositor bundle %s", target.name)
        return target
    cache.mkdir(parents=True, exist_ok=True)
    partial = cache / f".{target.name}.{uuid4().hex}.partial"
    try:
        _build(node, runtime, registry, partial, work)
        try:
            partial.rename(target)
        except OSError:
            # Another render published the same bundle first.
            if not _usable(target):
                raise
    finally:
        shutil.rmtree(partial, ignore_errors=True)
    _prune(cache, keep=target)
    return target


def _usable(bundle: Path) -> bool:
    return (bundle / "index.html").is_file()


def _build(
    node: str, runtime: RemotionRuntime, registry: Path | None, out: Path, work: Path
) -> None:
    empty = work / "bundle-public"
    empty.mkdir(parents=True, exist_ok=True)
    argv = [node, str(runtime.script), "bundle", str(runtime.entry), str(out), str(empty)]
    if registry is not None:
        argv.append(str(registry))
    code, said = run_node(
        argv, cwd=runtime.root, timeout=BUNDLE_TIMEOUT_S, desc="Building the compositor"
    )
    if code != 0 or not _usable(out):
        detail = "\n".join(said.strip().splitlines()[-30:])
        raise RemotionError(f"Remotion could not build the compositor (exit {code}):\n{detail}")
    # The script's public directory was empty; a render brings its own.
    shutil.rmtree(out / "public", ignore_errors=True)


def _prune(cache: Path, *, keep: Path) -> None:
    """Keep the newest bundles and drop builds that were abandoned."""
    now = time.time()
    bundles: list[tuple[float, Path]] = []
    for entry in cache.iterdir():
        try:
            modified = entry.stat().st_mtime
        except OSError:
            continue
        if entry.name.startswith("."):
            if entry.name.endswith(".partial") and now - modified > STALE_BUILD_S:
                shutil.rmtree(entry, ignore_errors=True)
            continue
        if entry.is_dir() and entry != keep:
            bundles.append((modified, entry))
    bundles.sort(reverse=True)
    for _modified, old in bundles[KEEP_BUNDLES - 1 :]:
        shutil.rmtree(old, ignore_errors=True)


def stage_serve_dir(bundle: Path, public: Path, work: Path) -> Path:
    """The directory one render is served from: the bundle plus its ``public/``.

    A kept bundle is shared, so it is never written to: its files are linked
    (copied where the filesystem cannot link) into the render's own work
    directory, and the render's files are moved in beside them -- moved, not
    copied, so the base video exists once.
    """
    if bundle.parent == work:
        serve = bundle  # built for this render alone
    else:
        serve = work / "serve"
        for source in sorted(bundle.rglob("*")):
            relative = source.relative_to(bundle)
            if relative.parts[0] == "public":
                continue
            destination = serve / relative
            if source.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(source, destination)
            except OSError:
                shutil.copy2(source, destination)
    shutil.rmtree(serve / "public", ignore_errors=True)
    public.rename(serve / "public")
    return serve
