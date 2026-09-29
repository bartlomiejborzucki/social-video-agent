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
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont

from social_video.errors import ValidationError
from social_video.ffmpeg.fonts import default_caption_font, font_covers
from social_video.ffmpeg.run import run_ffmpeg
from social_video.fsutil import atomic_target, utc_timestamp
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
_MAX_FIGURE_CHARS = 8

CoverLayout = Literal["bottom", "top", "boxed", "number"]
#: The layouts `cover` can draw; references/generated-visuals.md says when to use which.
COVER_LAYOUTS: tuple[str, ...] = ("bottom", "top", "boxed", "number")


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
    layout: CoverLayout = "bottom",
    figure: str | None = None,
) -> CoverDesign:
    """Draw the cover and return its inspectable design record."""
    if layout not in COVER_LAYOUTS:
        raise ValidationError(
            f"unknown cover layout {layout!r}; choose one of {', '.join(COVER_LAYOUTS)}"
        )
    figure = " ".join(figure.split()) if figure else None
    if layout == "number" and not figure:
        raise ValidationError('the number layout needs --figure, e.g. "3" or "-40%"')
    if figure and len(figure) > _MAX_FIGURE_CHARS:
        raise ValidationError(
            f"the cover figure is {len(figure)} characters; keep it to {_MAX_FIGURE_CHARS}"
        )
    if figure and layout != "number":
        raise ValidationError("--figure is drawn only by the number layout")
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
    canvas = _apply_scrim(canvas, style, _SCRIMS[layout])
    font_path = _resolve_font(style, f"{figure or ''} {title} {subtitle or ''}")
    canvas, box = _place_type(canvas, layout, title, subtitle, figure, style, font_path)
    if style.logo_file is not None:
        _draw_logo(canvas, style)

    with atomic_target(output) as partial:
        canvas.save(partial, format="JPEG", quality=92, subsampling=1, optimize=True)
    return CoverDesign(
        path=str(output),
        width=style.width,
        height=style.height,
        title=title,
        subtitle=subtitle,
        layout=layout,
        figure=figure,
        text_box=list(box),
        grid_safe=is_grid_safe(box, style.width, style.height),
        background=background_kind,
        frame_at=frame_at if background_kind == "frame" else None,
        plate=str(plate) if plate else None,
        font_file=str(font_path) if font_path else None,
        logo_file=str(style.logo_file) if style.logo_file else None,
        sha256=sha256_file(output),
        created_at=utc_timestamp(),
    )


def _apply_scrim(canvas: Image.Image, style: CoverStyle, kind: str = "bottom") -> Image.Image:
    """Darken where the type sits so white type stays legible over any background."""
    scrim = Image.new("L", (1, style.height))
    for y in range(style.height):
        position = y / max(1, style.height - 1)
        if kind == "top":
            position = 1.0 - position
        if kind == "flat":
            value = 90
        else:
            # Flat and light across the far third, ramping to near-opaque at the text.
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


def grid_band(width: int, height: int) -> tuple[int, int]:
    """Rows a 3:4 profile-grid crop of a tall cover keeps (Instagram shows the centre)."""
    visible = width * 4 / 3
    if height <= visible:
        return 0, height
    offset = int((height - visible) / 2)
    return offset, height - offset


def is_grid_safe(box: tuple[int, int, int, int], width: int, height: int) -> bool:
    top, bottom = grid_band(width, height)
    return box[1] >= top and box[3] <= bottom


def _place_type(
    canvas: Image.Image,
    layout: str,
    title: str,
    subtitle: str | None,
    figure: str | None,
    style: CoverStyle,
    font_path: Path | None,
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """Draw the type on its own layer, measure what was actually drawn, and nudge it
    into the zone. Line heights are estimates; descenders and accents are not."""
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    _DRAW[layout](layer, title, subtitle, figure, style, font_path)
    drawn = layer.getbbox()
    if drawn is None:
        raise ValidationError("the cover type drew nothing")
    _left, top, _right, bottom = _zone(style)
    shift = 0
    if drawn[3] > bottom:
        shift = bottom - drawn[3]
    if drawn[1] + shift < top:
        shift = top - drawn[1]
    placed = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    placed.paste(layer, (0, shift))
    composed = canvas.convert("RGBA")
    composed.alpha_composite(placed)
    box = (drawn[0], drawn[1] + shift, drawn[2], drawn[3] + shift)
    return composed.convert("RGB"), box


def _zone(style: CoverStyle) -> tuple[int, int, int, int]:
    """Where type may sit: inside the safe margins and inside the profile-grid crop."""
    top_pct, right_pct, bottom_pct, left_pct = style.margins
    grid_top, grid_bottom = grid_band(style.width, style.height)
    return (
        int(style.width * left_pct / 100),
        max(int(style.height * top_pct / 100), grid_top),
        style.width - int(style.width * right_pct / 100),
        min(style.height - int(style.height * bottom_pct / 100), grid_bottom),
    )


def _fit(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: Path | None,
    *,
    width: int,
    height: int,
    start: int,
    minimum: int,
    max_lines: int = _MAX_TITLE_LINES,
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    """The largest size at which ``text`` wraps into the box, down to ``minimum``."""
    size = start
    while True:
        font = _load_font(font_path, size)
        lines = _wrap(draw, text, font, width)
        fits = len(lines) <= max_lines and int(size * 1.08) * len(lines) <= height
        if fits or size <= minimum:
            return font, lines, size
        size = max(minimum, int(size * 0.92))


def _subtitle_lines(draw, subtitle, font_path, size, width):
    if not subtitle:
        return None, [], 0
    font = _load_font(font_path, max(18, int(size * 0.42)))
    lines = _wrap(draw, subtitle, font, width)[:2]
    return font, lines, int(size * 0.42 * 1.25) * len(lines) + int(size * 0.35)


def _draw_stack(
    canvas: Image.Image,
    title: str,
    subtitle: str | None,
    style: CoverStyle,
    font_path: Path | None,
    *,
    anchor: str,
) -> None:
    """Accent bar, title and subtitle, left-aligned, anchored to the zone's top or bottom."""
    draw = ImageDraw.Draw(canvas)
    left, top, right, bottom = _zone(style)
    width = right - left
    font, lines, size = _fit(
        draw, title, font_path, width=width, height=int((bottom - top) * 0.55),
        start=int(style.height * _TITLE_START_PCT / 100),
        minimum=int(style.height * _TITLE_MIN_PCT / 100),
    )  # fmt: skip
    line_height = int(size * 1.08)
    sub_font, sub_lines, sub_height = _subtitle_lines(draw, subtitle, font_path, size, width)
    bar_height = max(6, int(style.height * 0.006))
    lead = int(size * 0.45)
    block = line_height * len(lines) + sub_height
    y = top + lead if anchor == "top" else bottom - block
    bar = (left, y - lead, left + int(width * 0.22), y - lead + bar_height)
    draw.rectangle(bar, fill=style.accent)
    for line in lines:
        draw.text((left, y), line, font=font, fill=style.text_colour)
        y += line_height
    if sub_font is not None:
        y += int(size * 0.35)
        for line in sub_lines:
            draw.text((left, y), line, font=sub_font, fill=style.accent)
            y += int(size * 0.42 * 1.25)


def _draw_bottom(canvas, title, subtitle, figure, style, font_path):
    _draw_stack(canvas, title, subtitle, style, font_path, anchor="bottom")


def _draw_top(canvas, title, subtitle, figure, style, font_path):
    _draw_stack(canvas, title, subtitle, style, font_path, anchor="top")


def _draw_boxed(canvas, title, subtitle, figure, style, font_path):
    """Each title line on its own accent block, centred: the sticker look."""
    draw = ImageDraw.Draw(canvas)
    left, top, right, bottom = _zone(style)
    width = right - left
    font, lines, size = _fit(
        draw, title, font_path, width=int(width * 0.86), height=int((bottom - top) * 0.5),
        start=int(style.height * 6.8 / 100), minimum=int(style.height * _TITLE_MIN_PCT / 100),
    )  # fmt: skip
    pad_x, pad_y = int(size * 0.28), int(size * 0.14)
    line_height = int(size * 1.08) + 2 * pad_y + int(size * 0.08)
    sub_font, sub_lines, sub_height = _subtitle_lines(draw, subtitle, font_path, size, width)
    ink = _ink_on(style.accent, style)
    centre = (left + right) // 2
    y = bottom - line_height * len(lines) - sub_height
    for line in lines:
        x0, y0, x1, y1 = draw.textbbox((0, 0), line, font=font)
        x = centre - (x1 - x0) // 2 - x0
        plate = (x + x0 - pad_x, y + y0 - pad_y, x + x1 + pad_x, y + y1 + pad_y)
        draw.rounded_rectangle(plate, radius=int(size * 0.18), fill=style.accent)
        draw.text((x, y), line, font=font, fill=ink)
        y += line_height
    if sub_font is not None:
        y += int(size * 0.2)
        for line in sub_lines:
            x0, _y0, x1, _y1 = draw.textbbox((0, 0), line, font=sub_font)
            x = centre - (x1 - x0) // 2 - x0
            draw.text((x, y), line, font=sub_font, fill=style.text_colour)
            y += int(size * 0.42 * 1.25)


def _draw_number(canvas, title, subtitle, figure, style, font_path):
    """One huge figure in the accent colour over the title: '3 mistakes', '-40%'."""
    assert figure is not None
    draw = ImageDraw.Draw(canvas)
    left, top, right, bottom = _zone(style)
    width = right - left
    fig_size = int(style.height * 0.2)
    while fig_size > int(style.height * 0.06):
        fig_font = _load_font(font_path, fig_size)
        if draw.textlength(figure, font=fig_font) <= width:
            break
        fig_size = int(fig_size * 0.92)
    fig_font = _load_font(font_path, fig_size)
    font, lines, size = _fit(
        draw, title, font_path, width=width, height=int((bottom - top) * 0.3),
        start=int(style.height * 6.0 / 100), minimum=int(style.height * _TITLE_MIN_PCT / 100),
        max_lines=3,
    )  # fmt: skip
    line_height = int(size * 1.08)
    sub_font, sub_lines, sub_height = _subtitle_lines(draw, subtitle, font_path, size, width)
    fx0, fy0, _fx1, fy1 = draw.textbbox((0, 0), figure, font=fig_font)
    figure_height = fy1 - fy0
    gap = int(size * 0.3)
    y = bottom - sub_height - line_height * len(lines) - gap - figure_height
    draw.text((left - fx0, y - fy0), figure, font=fig_font, fill=style.accent)
    y += figure_height + gap
    for line in lines:
        draw.text((left, y), line, font=font, fill=style.text_colour)
        y += line_height
    if sub_font is not None:
        y += int(size * 0.35)
        for line in sub_lines:
            draw.text((left, y), line, font=sub_font, fill=style.text_colour)
            y += int(size * 0.42 * 1.25)


def _ink_on(fill: str, style: CoverStyle) -> str:
    """Dark type on a light accent, the brand's text colour on a dark one."""
    value = fill.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return style.background_colour if luminance > 0.55 else style.text_colour


_DRAW = {
    "bottom": _draw_bottom,
    "top": _draw_top,
    "boxed": _draw_boxed,
    "number": _draw_number,
}
_SCRIMS = {"bottom": "bottom", "top": "top", "boxed": "flat", "number": "bottom"}


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


def compare_covers(designs: list[CoverDesign], output: Path, *, tile_width: int = 360) -> Path:
    """The candidate covers side by side, each with the profile-grid crop outlined."""
    if not designs:
        raise ValidationError("there are no covers to compare")
    tiles: list[Image.Image] = []
    for design in designs:
        with Image.open(design.path) as image:
            tile = image.convert("RGB")
        scale = tile_width / tile.width
        tile = tile.resize((tile_width, round(tile.height * scale)), Image.Resampling.LANCZOS)
        draw = ImageDraw.Draw(tile)
        top, bottom = grid_band(design.width, design.height)
        if (top, bottom) != (0, design.height):
            edge = (0, round(top * scale), tile.width - 1, round(bottom * scale))
            draw.rectangle(edge, outline=(255, 255, 255), width=2)
        draw.rectangle((0, 0, tile.width, 26), fill=(0, 0, 0))
        label = design.layout + ("" if design.grid_safe is not False else "  (outside grid)")
        draw.text((6, 6), label, fill=(255, 255, 255))
        tiles.append(tile)
    height = max(t.height for t in tiles)
    sheet = Image.new("RGB", (len(tiles) * (tile_width + 4) - 4, height), "#000000")
    for index, tile in enumerate(tiles):
        sheet.paste(tile, (index * (tile_width + 4), 0))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    return output
