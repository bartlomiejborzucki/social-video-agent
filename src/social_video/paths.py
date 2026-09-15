"""Cross-platform locations for caches, downloaded tools, and models.

No hard-coded ``/tmp`` and no macOS-only assumptions: upstream video-use writes
temp files into the system temp dir and then interpolates those paths straight
into ffmpeg filter strings, which breaks on Windows (``C:\\Users\\...`` contains
both a colon and backslashes) and on any POSIX box whose ``TMPDIR`` has a space.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "social-video-agent"


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
