"""Fetch a working ffmpeg when the system does not have one.

Needs no administrator rights, which matters on locked-down machines and in CI.
The build is downloaded into the app cache, never into the repository: these are
GPL binaries and redistributing them inside an Apache-2.0 project would be a
licensing mistake.
"""

from __future__ import annotations

import hashlib
import logging
import platform
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from social_video.errors import SocialVideoError
from social_video.paths import ensure_dir, tools_dir

log = logging.getLogger(__name__)

#: BtbN's builds are the practical choice: current, static, and built with
#: libass and libzimg, which are exactly the two capabilities a minimal ffmpeg
#: tends to lack and that we need for captions and HDR sources.
_BASE = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest"

_ASSETS = {
    ("Linux", "x86_64"): "ffmpeg-master-latest-linux64-gpl.tar.xz",
    ("Linux", "aarch64"): "ffmpeg-master-latest-linuxarm64-gpl.tar.xz",
    ("Windows", "AMD64"): "ffmpeg-master-latest-win64-gpl.zip",
    ("Windows", "x86_64"): "ffmpeg-master-latest-win64-gpl.zip",
}


def _asset_name() -> str:
    key = (platform.system(), platform.machine())
    if key in _ASSETS:
        return _ASSETS[key]
    if key[0] == "Darwin":
        raise SocialVideoError(
            "No static build is published for macOS. Install ffmpeg with "
            "`brew install ffmpeg`, and check that it includes libass "
            "(`ffmpeg -filters | grep subtitles`)."
        )
    raise SocialVideoError(
        f"No static ffmpeg build is available for {key[0]} {key[1]}. "
        f"Install ffmpeg with your system package manager instead."
    )


def install_static_ffmpeg(*, progress: bool = True, force: bool = False) -> Path:
    """Download and unpack a static ffmpeg. Returns the binary path."""
    target = ensure_dir(tools_dir()) / "ffmpeg"
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    existing = target / "bin" / exe
    if existing.is_file() and not force:
        log.info("static ffmpeg already present at %s", existing)
        return existing

    asset = _asset_name()
    url = f"{_BASE}/{asset}"
    log.info("downloading %s", url)

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / asset
        _download(url, archive, progress=progress)
        checksums = Path(tmp) / "checksums.sha256"
        _download(f"{_BASE}/checksums.sha256", checksums, progress=False)
        _verify_checksum(archive, checksums)
        extracted = Path(tmp) / "x"
        extracted.mkdir()
        _extract(archive, extracted)

        # Archives unpack to a single versioned directory containing bin/.
        roots = [p for p in extracted.iterdir() if p.is_dir()]
        source_root = roots[0] if len(roots) == 1 else extracted
        if not (source_root / "bin").is_dir():
            raise SocialVideoError(f"unexpected archive layout in {asset}: no bin/ directory found")
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(source_root), str(target))

    binary = target / "bin" / exe
    if not binary.is_file():
        raise SocialVideoError(f"ffmpeg was not found at {binary} after extraction")
    if sys.platform != "win32":
        for tool in binary.parent.iterdir():
            tool.chmod(0o755)
    log.info("ffmpeg installed at %s", binary)
    return binary


def _download(url: str, dest: Path, *, progress: bool) -> None:
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with dest.open("wb") as out:
                while chunk := response.read(1 << 20):
                    out.write(chunk)
                    done += len(chunk)
                    if progress and total:
                        pct = done * 100 // total
                        print(f"\r  downloading ffmpeg: {pct}%", end="", file=sys.stderr)
            if progress:
                print("", file=sys.stderr)
    except OSError as exc:
        raise SocialVideoError(f"could not download ffmpeg from {url}: {exc}") from exc


def _extract(archive: Path, dest: Path) -> None:
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            _guard_members(zf.namelist())
            zf.extractall(dest)
    else:
        with tarfile.open(archive) as tf:
            members = tf.getmembers()
            _guard_members([member.name for member in members])
            _guard_members(
                [member.linkname for member in members if member.issym() or member.islnk()]
            )
            tf.extractall(dest)


def _verify_checksum(archive: Path, checksums: Path) -> None:
    """Match the downloaded asset against the publisher's SHA-256 manifest."""
    expected = None
    for line in checksums.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == archive.name:
            expected = parts[0].lower()
            break
    if not expected or len(expected) != 64:
        raise SocialVideoError(f"no SHA-256 entry found for {archive.name}")
    digest = hashlib.sha256()
    with archive.open("rb") as source:
        while chunk := source.read(1 << 20):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise SocialVideoError(f"SHA-256 verification failed for {archive.name}")


def _guard_members(names: list[str]) -> None:
    """Refuse archives that would write outside the destination.

    Standard defence against a path-traversal entry in a downloaded archive.
    """
    for name in names:
        if name.startswith("/") or ".." in Path(name).parts:
            raise SocialVideoError(f"refusing unsafe archive entry: {name!r}")
