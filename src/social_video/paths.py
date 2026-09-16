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


def normalize_user_path(value: str | os.PathLike[str], *, must_exist: bool = False) -> Path:
    """Normalize a user-supplied Linux or Windows path for this runtime.

    Windows paths are translated by WSL's own ``wslpath`` command. The command
    receives an argument array, so spaces, Polish characters, and shell syntax
    remain ordinary filename characters.
    """
    raw = os.fspath(value)
    if is_windows_drive_path(raw) and sys.platform == "linux":
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
