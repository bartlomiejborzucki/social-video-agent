"""The single entry point for invoking ffmpeg and ffprobe.

Design rules, all of them reactions to defects found in the upstream audit:

* Arguments are always an argv list. Never a shell string, never string
  concatenation. Paths may contain spaces, quotes, and non-ASCII characters.
* stderr is always captured *and* surfaced on failure. See
  :class:`social_video.errors.FFmpegError`.
* Binary discovery is explicit and overridable, so a bootstrapped or
  non-standard ffmpeg works without editing code.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from social_video.errors import FFmpegError, ToolNotFoundError
from social_video.paths import tools_dir

log = logging.getLogger(__name__)

#: Environment overrides, checked before anything else.
_ENV_OVERRIDE = {"ffmpeg": "SOCIAL_VIDEO_FFMPEG", "ffprobe": "SOCIAL_VIDEO_FFPROBE"}


@functools.lru_cache(maxsize=8)
def find_binary(name: str) -> str:
    """Locate ``ffmpeg`` or ``ffprobe``.

    Order: explicit environment override, then a build we bootstrapped into the
    app cache, then ``PATH``. On Windows ``shutil.which`` already applies
    ``PATHEXT``, so ``.exe`` needs no special handling here.
    """
    override = os.environ.get(_ENV_OVERRIDE.get(name, ""))
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file():
            return str(candidate)
        raise ToolNotFoundError(
            f"{_ENV_OVERRIDE[name]} points at {candidate}, which is not a file."
        )

    exe = f"{name}.exe" if sys.platform == "win32" else name
    bundled = tools_dir() / "ffmpeg" / "bin" / exe
    if bundled.is_file():
        return str(bundled)

    found = shutil.which(name)
    if found:
        return found

    raise ToolNotFoundError(
        f"{name} was not found on PATH.\n"
        f"Install it with your package manager (e.g. `sudo apt install ffmpeg`,\n"
        f"`brew install ffmpeg`, `winget install Gyan.FFmpeg`), or let us fetch a\n"
        f"static build with `social-video doctor --install-ffmpeg`, or point\n"
        f"{_ENV_OVERRIDE.get(name, 'the override variable')} at an existing binary."
    )


def run_ffmpeg(
    args: Sequence[str],
    *,
    desc: str = "ffmpeg invocation",
    timeout: float | None = None,
) -> str:
    """Run ffmpeg with the given arguments (excluding the binary itself).

    ``-hide_banner`` and ``-nostdin`` are always prepended: without ``-nostdin``
    a backgrounded ffmpeg can steal the agent's terminal input.

    Returns the captured stderr, which is where ffmpeg writes its progress and
    the ``loudnorm``/``signalstats`` output we sometimes need to parse.
    """
    argv = [find_binary("ffmpeg"), "-hide_banner", "-nostdin", *args]
    return _run(argv, desc=desc, timeout=timeout).stderr


def run_ffprobe(
    args: Sequence[str],
    *,
    desc: str = "ffprobe invocation",
    timeout: float | None = None,
) -> str:
    """Run ffprobe and return stdout."""
    argv = [find_binary("ffprobe"), "-hide_banner", *args]
    return _run(argv, desc=desc, timeout=timeout).stdout


def run_ffprobe_json(
    args: Sequence[str],
    *,
    desc: str = "ffprobe invocation",
    timeout: float | None = None,
) -> dict[str, Any]:
    """Run ffprobe in JSON output mode and parse the result.

    Unlike upstream, a probe failure raises instead of silently returning a
    default. Upstream's ``is_portrait_source`` swallows seven exception types
    and assumes landscape, so a probe hiccup on a portrait phone clip silently
    renders it 1920 wide by 3413 tall.
    """
    argv = ["-v", "error", "-print_format", "json", *args]
    raw = run_ffprobe(argv, desc=desc, timeout=timeout)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FFmpegError(
            f"{desc}: ffprobe returned output that is not valid JSON",
            args_used=[find_binary("ffprobe"), *argv],
            returncode=0,
            stderr=raw[:4000],
        ) from exc


def _run(argv: list[str], *, desc: str, timeout: float | None) -> subprocess.CompletedProcess[str]:
    log.debug("exec: %s", argv)
    try:
        # argv list, never shell=True.
        proc = subprocess.run(
            argv,
            capture_output=True,
            timeout=timeout,
            check=False,
            # ffmpeg emits UTF-8; never let a legacy console codepage decide.
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:  # pragma: no cover - guarded by find_binary
        raise ToolNotFoundError(f"{argv[0]} disappeared between lookup and exec") from exc
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError(
            f"{desc}: timed out after {timeout}s",
            args_used=argv,
            returncode=-1,
            stderr=(exc.stderr or b"").decode("utf-8", "replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or ""),
        ) from exc

    if proc.returncode != 0:
        raise FFmpegError(
            desc, args_used=argv, returncode=proc.returncode, stderr=proc.stderr or ""
        )
    return proc


@functools.lru_cache(maxsize=1)
def _ffmpeg_filters() -> frozenset[str]:
    """Names of every filter the installed ffmpeg exposes."""
    out = _run(
        [find_binary("ffmpeg"), "-hide_banner", "-filters"], desc="list filters", timeout=30
    ).stdout
    names: set[str] = set()
    for line in out.splitlines():
        # Format: " TSC avgblur    V->V  Apply Average Blur filter."
        parts = line.split()
        if len(parts) >= 3 and not line.startswith("Filters:") and "=" not in parts[0]:
            names.add(parts[1])
    return frozenset(names)


@functools.lru_cache(maxsize=1)
def _ffmpeg_buildconf() -> str:
    """The `--enable-*` configuration string of the installed ffmpeg."""
    out = _run(
        [find_binary("ffmpeg"), "-hide_banner", "-version"], desc="ffmpeg version", timeout=30
    ).stdout
    return out


def has_filter(name: str) -> bool:
    """Whether the installed ffmpeg provides a given filter."""
    try:
        return name in _ffmpeg_filters()
    except (FFmpegError, ToolNotFoundError):
        return False


def has_libass() -> bool:
    """Whether subtitles can be burned in.

    Homebrew's ffmpeg formula has shipped without libass, which is upstream
    issue #133: subtitle burn-in crashes on a documented macOS install.
    """
    return has_filter("subtitles") and "--enable-libass" in _ffmpeg_buildconf()


def has_libzimg() -> bool:
    """Whether the HDR->SDR tone-map chain can run.

    The chain needs ``zscale``, which only exists with ``--enable-libzimg``.
    Upstream applies the chain with no capability check, so on an ffmpeg without
    zimg the render dies with ``No such filter: 'zscale'``.
    """
    return has_filter("zscale")


def ffmpeg_version() -> str:
    """First line of ``ffmpeg -version``, for diagnostics."""
    return _ffmpeg_buildconf().splitlines()[0] if _ffmpeg_buildconf() else "unknown"
