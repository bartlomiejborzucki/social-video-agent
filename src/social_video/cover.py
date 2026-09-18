"""Compose the cover still: brand typography over a frame or a generated plate.

The cover is the first thing anyone sees and the last thing this pipeline used
to leave to chance -- ``--poster`` simply grabbed a frame. It is composed with
Pillow rather than Remotion so it works on the FFmpeg-only route too, and so a
still costs no browser render.

Text is always drawn here, never asked of an image model.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont

from social_video.errors import ValidationError
from social_video.ffmpeg.fonts import default_caption_font, font_covers
from social_video.ffmpeg.run import run_ffmpeg
from social_video.imaging import cover_crop, load_image, sha256_file
from social_video.schemas.config import BrandContract
from social_video.schemas.visuals import CoverDesign

#: Pillow renders TrueType and OpenType. libass-only web formats are not usable here.
_PILLOW_FONT_SUFFIXES = {".ttf", ".otf"}
#: Title height as a fraction of the canvas, before shrinking to fit.
_TITLE_START_PCT = 8.2
_TITLE_MIN_PCT = 3.6
_MAX_TITLE_LINES = 4
#: Matches CoverDesign.title. Checked before drawing so a too-long title fails
#: with a reason rather than writing a file and then failing validation.
_MAX_TITLE_CHARS = 120


@dataclass(frozen=True)
class CoverStyle:
    width: int = 1080
    height: int = 1920
    accent: str = "#FFD400"
    text_colour: str = "#FFFFFF"
    background_colour: str = "#101114"
    font_file: Path | None = None
    logo_file: Path | None = None
    bold: bool = True
    margins: tuple[float, float, float, float] = (6.0, 6.0, 12.0, 6.0)

    @classmethod
    def from_contract(cls, contract: BrandContract) -> CoverStyle:
        margins = contract.safe_margins or {}
        return cls(
            width=contract.output_width,
            height=contract.output_height,
            accent=contract.brand.accent_colour,
            text_colour=contract.brand.captions.primary_colour,
            background_colour=contract.brand.background_colour,
            font_file=Path(contract.resolved_font_file) if contract.resolved_font_file else None,
            bold=contract.brand.captions.bold,
            logo_file=(
                Path(contract.resolved_logo_file)
                if contract.resolved_logo_file and contract.brand.logo_usage != "none"
                else None
            ),
            margins=(
                float(margins.get("top", 6)),
                float(margins.get("right", 6)),
                float(margins.get("bottom", 12)),
                float(margins.get("left", 6)),
            ),
        )


def extract_frame(video: Path, at: float, target: Path) -> Path:
    """Pull one frame from the finished video to use as the cover background."""
    target.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-y",
            "-ss",
            f"{max(0.0, at):.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            "-update",
            "1",
            str(target),
        ],
        desc="extract cover frame",
        timeout=300,
    )
    if not target.is_file():
        raise ValidationError(f"could not extract a cover frame at {at:.2f}s from {video}")
    return target


def compose_cover(
    output: Path,
    *,
    title: str,
    style: CoverStyle,
    subtitle: str | None = None,
    plate: Path | None = None,
    frame: Path | None = None,
    frame_at: float | None = None,
) -> CoverDesign:
    """Draw the cover and return its inspectable design record."""
    title = " ".join(title.split())
    if not title:
        raise ValidationError("a cover needs a title")
    if len(title) > _MAX_TITLE_CHARS:
        raise ValidationError(
            f"the cover title is {len(title)} characters; nothing over {_MAX_TITLE_CHARS} "
            "is readable at thumbnail size"
        )
    subtitle = " ".join(subtitle.split()) if subtitle else None
    if plate is not None and frame is not None:
        raise ValidationError("a cover has one background: pass either a plate or a frame")

    source = plate or frame
    background_kind: Literal["frame", "plate", "solid"] = (
        "plate" if plate else "frame" if frame else "solid"
    )
    canvas = (
        cover_crop(load_image(source, label="cover background"), style.width, style.height)
        if source is not None
        else Image.new("RGB", (style.width, style.height), style.background_colour)
    )
    canvas = _apply_scrim(canvas, style)
    font_path = _resolve_font(style, f"{title} {subtitle or ''}")
    _draw_text(canvas, title, subtitle, style, font_path)
    if style.logo_file is not None:
        _draw_logo(canvas, style)

    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(f".{output.name}.partial")
    try:
        canvas.save(partial, format="JPEG", quality=92, subsampling=1, optimize=True)
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
    return CoverDesign(
        path=str(output),
        width=style.width,
        height=style.height,
        title=title,
        subtitle=subtitle,
        background=background_kind,
        frame_at=frame_at if background_kind == "frame" else None,
        plate=str(plate) if plate else None,
        font_file=str(font_path) if font_path else None,
        logo_file=str(style.logo_file) if style.logo_file else None,
        sha256=sha256_file(output),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def _apply_scrim(canvas: Image.Image, style: CoverStyle) -> Image.Image:
    """Darken the lower half so white type stays legible over any background."""
    scrim = Image.new("L", (1, style.height))
    for y in range(style.height):
        position = y / max(1, style.height - 1)
        # Flat and light across the top third, ramping to near-opaque at the base.
        value = 40 if position < 0.35 else 40 + int(205 * ((position - 0.35) / 0.65) ** 1.6)
        scrim.putpixel((0, y), min(235, value))
    mask = scrim.resize((style.width, style.height))
    shade = Image.new("RGB", canvas.size, "#05070A")
    return Image.composite(shade, canvas, mask.point(lambda v: v))


def _resolve_font(style: CoverStyle, text: str) -> Path | None:
    candidates: list[Path] = []
    if style.font_file and style.font_file.suffix.casefold() in _PILLOW_FONT_SUFFIXES:
        candidates.append(style.font_file)
    fallback = default_caption_font()
    if fallback is not None:
        candidates.append(fallback.path)
    for candidate in candidates:
        if not candidate.is_file():
            continue
        # A cover headline set in a Regular face reads as a default, not a design.
        preferred = _bold_variant(candidate) if style.bold else candidate
        if font_covers(preferred, text):
            return preferred
        if preferred != candidate and font_covers(candidate, text):
            return candidate
    if candidates:
        # Rendering tofu boxes into the one image people judge the video by is
        # worse than refusing: say which glyphs are missing and stop.
        raise ValidationError(
            f"no available font covers the cover text. Tried: "
            f"{', '.join(str(path) for path in candidates)}. Set font_file in the "
            "project config to a .ttf or .otf with the glyphs this title needs."
        )
    raise ValidationError("no usable font was found for the cover title")


def _bold_variant(path: Path) -> Path:
    """Use the family's Bold face when it sits beside the Regular one."""
    stem = path.stem
    for regular, bold in (("-Regular", "-Bold"), ("Regular", "Bold"), ("", "-Bold"), ("", "Bold")):
        if regular and regular not in stem:
            continue
        replaced = stem.replace(regular, bold) if regular else stem + bold
        candidate = path.with_name(f"{replaced}{path.suffix}")
        if candidate.is_file():
            return candidate
    return path


def _draw_text(
    canvas: Image.Image,
    title: str,
    subtitle: str | None,
    style: CoverStyle,
    font_path: Path | None,
) -> None:
    draw = ImageDraw.Draw(canvas)
    _top_pct, right_pct, bottom_pct, left_pct = style.margins
    left = int(style.width * left_pct / 100)
    right = style.width - int(style.width * right_pct / 100)
    bottom = style.height - int(style.height * bottom_pct / 100)
    max_width = right - left

    size = int(style.height * _TITLE_START_PCT / 100)
    minimum = int(style.height * _TITLE_MIN_PCT / 100)
    while True:
        font = _load_font(font_path, size)
        lines = _wrap(draw, title, font, max_width)
        if len(lines) <= _MAX_TITLE_LINES or size <= minimum:
            break
        size = max(minimum, int(size * 0.92))
    line_height = int(size * 1.08)
    block_height = line_height * len(lines)

    subtitle_font = None
    subtitle_lines: list[str] = []
    if subtitle:
        subtitle_font = _load_font(font_path, max(18, int(size * 0.42)))
        subtitle_lines = _wrap(draw, subtitle, subtitle_font, max_width)[:2]
        block_height += int(size * 0.42 * 1.25) * len(subtitle_lines) + int(size * 0.35)

    y = bottom - block_height
    bar_height = max(6, int(style.height * 0.006))
    bar_y = y - int(size * 0.45)
    draw.rectangle(
        (left, bar_y, left + int(max_width * 0.22), bar_y + bar_height),
        fill=style.accent,
    )
    for line in lines:
        draw.text((left, y), line, font=font, fill=style.text_colour)
        y += line_height
    if subtitle_font is not None:
        y += int(size * 0.35)
        for line in subtitle_lines:
            draw.text((left, y), line, font=subtitle_font, fill=style.accent)
            y += int(size * 0.42 * 1.25)


def _draw_logo(canvas: Image.Image, style: CoverStyle) -> None:
    assert style.logo_file is not None
    if style.logo_file.suffix.casefold() == ".svg":
        # Pillow cannot rasterise SVG; the video renderer handles it, the cover
        # simply goes without rather than shipping a broken mark.
        return
    logo = load_image(style.logo_file, label="logo").convert("RGBA")
    top_pct, right_pct, _bottom, _left = style.margins
    box_height = int(style.height * 0.055)
    scale = box_height / logo.height
    resized = logo.resize((max(1, round(logo.width * scale)), box_height), Image.Resampling.LANCZOS)
    x = style.width - int(style.width * right_pct / 100) - resized.width
    y = int(style.height * top_pct / 100)
    canvas.paste(resized, (x, y), resized)


def _load_font(path: Path | None, size: int) -> ImageFont.FreeTypeFont:
    if path is None:
        raise ValidationError("no usable font was found for the cover title")
    try:
        return ImageFont.truetype(str(path), size)
    except OSError as exc:
        raise ValidationError(f"cannot load cover font {path}: {exc}") from exc


def _wrap(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int
) -> list[str]:
    """Greedy wrap by measured width, so it works for any language."""
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    # A single word wider than the canvas still has to break somewhere.
    broken: list[str] = []
    for line in lines:
        if draw.textlength(line, font=font) <= width or " " in line:
            broken.append(line)
            continue
        broken.extend(textwrap.wrap(line, max(4, len(line) // 2)) or [line])
    return broken
