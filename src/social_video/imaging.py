"""Shared still-image helpers.

Pillow is already a dependency, and a cover is a still, so covers are composed
here rather than in Remotion. That keeps them available on the FFmpeg-only route
and makes them reproducible without a browser.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from PIL import Image

from social_video.errors import ValidationError
from social_video.ffmpeg.run import find_binary

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


def contact_sheet(
    video: Path,
    moments: list[tuple[float, str]],
    output: Path,
    *,
    tile_width: int = 270,
    colours: list[tuple[int, int, int] | None] | None = None,
) -> Path:
    """One labelled frame per ``(time, label)`` moment, four to a row.

    ``colours`` gives a tile its label bar and border colour, one per moment;
    None keeps the plain black bar.
    """
    from PIL import ImageDraw

    if not moments:
        raise ValidationError("a contact sheet needs at least one moment")
    frames: list[Image.Image] = []
    work = output.with_suffix(".frames")
    work.mkdir(parents=True, exist_ok=True)
    try:
        for index, (at, label) in enumerate(moments):
            still = work / f"{index:03d}.png"
            subprocess.run(
                [find_binary("ffmpeg"), "-v", "error", "-y", "-ss", f"{at:.3f}", "-i", str(video),
                 "-frames:v", "1", "-vf", f"scale={tile_width}:-2", str(still)],
                check=True, timeout=120,
            )  # fmt: skip
            with Image.open(still) as image:
                tile = image.convert("RGB")
            draw = ImageDraw.Draw(tile)
            colour = colours[index] if colours else None
            draw.rectangle((0, 0, tile.width, 26), fill=colour or (0, 0, 0))
            draw.text((6, 6), f"{at:5.2f}s  {label}", fill=(255, 255, 255))
            if colour is not None:
                draw.rectangle((0, 0, tile.width - 1, tile.height - 1), outline=colour, width=3)
            frames.append(tile)
    finally:
        for leftover in work.glob("*.png"):
            leftover.unlink()
        work.rmdir()
    columns = min(4, len(frames))
    rows = -(-len(frames) // columns)
    height = frames[0].height
    sheet = Image.new(
        "RGB", (columns * tile_width + (columns - 1) * 4, rows * height + (rows - 1) * 4)
    )
    for index, frame in enumerate(frames):
        sheet.paste(
            frame, ((index % columns) * (tile_width + 4), (index // columns) * (height + 4))
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    return output
