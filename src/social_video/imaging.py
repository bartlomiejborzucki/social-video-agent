"""Shared still-image helpers.

Pillow is already a dependency, and a cover is a still, so covers are composed
here rather than in Remotion. That keeps them available on the FFmpeg-only route
and makes them reproducible without a browser.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

from social_video.errors import ValidationError

#: What we accept as a background plate or logo.
SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
#: A still that is larger than this is a mistake, not a design.
MAX_IMAGE_BYTES = 20 * 1024 * 1024


def load_image(path: Path, *, label: str = "image") -> Image.Image:
    """Open an image, failing with a message that names the offending file."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise ValidationError(f"{label} does not exist: {path}")
    if path.suffix.casefold() not in SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise ValidationError(f"{label} must be one of {supported}: {path}")
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValidationError(f"{label} exceeds the {MAX_IMAGE_BYTES // 1024 // 1024} MB limit")
    try:
        image = Image.open(path)
        image.load()
    except OSError as exc:
        raise ValidationError(f"{label} is not a readable image: {path} ({exc})") from exc
    return image


def cover_crop(image: Image.Image, width: int, height: int) -> Image.Image:
    """Scale to fill the canvas and centre-crop the overflow.

    Padding a generated plate would show the canvas colour at the edges, which
    is exactly the seam a designed cover must not have.
    """
    source = image.convert("RGB")
    scale = max(width / source.width, height / source.height)
    scaled = source.resize(
        (max(width, round(source.width * scale)), max(height, round(source.height * scale))),
        Image.Resampling.LANCZOS,
    )
    left = (scaled.width - width) // 2
    top = (scaled.height - height) // 2
    return scaled.crop((left, top, left + width, top + height))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
