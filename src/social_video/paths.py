"""Cross-platform locations for caches, downloaded tools, and models.

No hard-coded ``/tmp`` and no macOS-only assumptions: upstream video-use writes
temp files into the system temp dir and then interpolates those paths straight
into ffmpeg filter strings, which breaks on Windows (``C:\\Users\\...`` contains
both a colon and backslashes) and on any POSIX box whose ``TMPDIR`` has a space.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "social-video-agent"
_WINDOWS_DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_WSL_MOUNT_PATH = re.compile(r"^/mnt/[a-z](?:/|$)", re.IGNORECASE)
#: Windows' view of a WSL filesystem. A Windows file picker hands these out, so
#: an agent running on Windows can easily pass one in.
_WSL_UNC_PATH = re.compile(
    r"^\\\\wsl(?:\$|\.localhost)\\(?P<distribution>[^\\]+)\\(?P<rest>.*)$",
    re.IGNORECASE,
)


def is_wsl() -> bool:
    """Return whether this process is running inside WSL."""
    if sys.platform != "linux":
        return False
    for candidate in (Path("/proc/sys/kernel/osrelease"), Path("/proc/version")):
        try:
            if "microsoft" in candidate.read_text(encoding="utf-8").lower():
                return True
        except OSError:
            continue
    return False


def is_windows_drive_path(value: str | os.PathLike[str]) -> bool:
    """Recognize an absolute Windows drive-letter path before pathlib mangles it."""
    return bool(_WINDOWS_DRIVE_PATH.match(os.fspath(value)))


def is_wsl_mount_path(value: str | os.PathLike[str]) -> bool:
    """Return whether a Linux path is on a Windows drive mounted by WSL."""
    return bool(_WSL_MOUNT_PATH.match(os.fspath(value).replace("\\", "/")))


def is_wsl_unc_path(value: str | os.PathLike[str]) -> bool:
    """Recognize ``\\\\wsl$\\Ubuntu\\home\\...`` and its ``wsl.localhost`` spelling."""
    return bool(_WSL_UNC_PATH.match(os.fspath(value)))


def current_distribution() -> str | None:
    """The WSL distribution this process is in, if it is in one."""
    return (os.environ.get("WSL_DISTRO_NAME") or "").strip() or None


def _strip_quotes(raw: str) -> str:
    """Drop one matched pair of surrounding quotes.

    A copied Windows path arrives quoted often enough that keeping the quotes
    would turn them into part of the filename, which fails later and further
    away. A file whose name both starts and ends with a quote is not worth
    supporting at that cost.
    """
    text = raw.strip()
    for quote in ('"', "'"):
        if len(text) >= 2 and text.startswith(quote) and text.endswith(quote):
            return text[1:-1]
    return text


def _from_unc(raw: str) -> str:
    """Translate a WSL UNC path, but only for the distribution we are in."""
    match = _WSL_UNC_PATH.match(raw)
    assert match is not None  # guarded by the caller
    distribution = match.group("distribution")
    current = current_distribution()
    if current and distribution.casefold() != current.casefold():
        raise ValueError(
            f"{raw!r} points inside the WSL distribution {distribution!r}, but this process "
            f"is running in {current!r}. Another distribution's filesystem is not reachable "
            "as a path here; pass a path inside this distribution, or a /mnt/<drive>/... path."
        )
    rest = match.group("rest").replace("\\", "/").lstrip("/")
    return "/" + rest


def normalize_user_path(value: str | os.PathLike[str], *, must_exist: bool = False) -> Path:
    """Normalize a user-supplied Linux or Windows path for this runtime.

    Handles a drive-letter path, a quoted path, a WSL UNC path, a
    ``/mnt/<drive>/...`` path and an ordinary Linux path. Windows drive paths
    are translated by WSL's own ``wslpath``, which is given an argument array,
    so spaces, Polish characters, brackets and shell syntax stay ordinary
    filename characters.

    Normalising twice is safe and is the same as normalising once: the result of
    a conversion is already a Linux path, so it is not converted again. That is
    what stops ``/mnt/c/mnt/c/...`` from ever being built.
    """
    raw = _strip_quotes(os.fspath(value))
    if is_wsl_unc_path(raw):
        if not is_wsl():
            raise ValueError(
                f"WSL path {raw!r} can only be resolved from inside WSL. Run the engine "
                "there, or pass a /mnt/<drive>/... path."
            )
        raw = _from_unc(raw)
    # A drive-letter path is already native on Windows. On every POSIX host it
    # is meaningful only inside WSL, where wslpath performs the conversion.
    if is_windows_drive_path(raw) and sys.platform != "win32":
        if not is_wsl():
            raise ValueError(
                f"Windows path {raw!r} can only be translated when running inside WSL."
            )
        converter = shutil.which("wslpath")
        if not converter:
            raise RuntimeError(
                "wslpath is unavailable inside WSL; pass the equivalent /mnt/<drive>/... path."
            )
        result = subprocess.run(
            [converter, "-u", raw],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            detail = (result.stderr or "path conversion failed").strip()
            raise ValueError(f"Could not convert Windows path {raw!r} with wslpath: {detail}")
        raw = result.stdout.strip()

    path = Path(raw).expanduser().resolve(strict=False)
    if must_exist and not path.exists():
        raise FileNotFoundError(f"File or directory does not exist: {path}")
    return path


def app_home() -> Path:
    """Root for everything we cache or download.

    Honours ``SOCIAL_VIDEO_HOME`` first so users can relocate it, then the
    platform convention.
    """
    override = os.environ.get("SOCIAL_VIDEO_HOME")
    if override:
        return Path(override).expanduser().resolve()

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / APP_NAME
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / APP_NAME


def tools_dir() -> Path:
    """Where a bootstrapped ffmpeg build is unpacked."""
    return app_home() / "tools"


def models_dir() -> Path:
    """Where we stage ASR and face-detection model files."""
    return app_home() / "models"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
