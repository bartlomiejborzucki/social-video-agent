"""Load, validate and compile project video configuration."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import yaml

from social_video.config_migration import migrate_project_config
from social_video.errors import ValidationError
from social_video.paths import normalize_user_path
from social_video.schemas.base import save_artifact
from social_video.schemas.brand import BrandProfile, CaptionCase, CaptionPosition, CaptionStyle
from social_video.schemas.config import BrandContract, ProjectVideoConfig
from social_video.workspace.layout import Workspace

CONFIG_CANDIDATES = (Path(".social-video/config.yaml"), Path("social-video.yaml"))

DEFAULT_CONFIG = """schema_version: 1
brand_name: Project brand
font: Lato
font_file:
font_fallback:
  - Noto Sans
  - DejaVu Sans
brand_colors:
  - "#28BCA5"
logo_file:
logo_usage: none
caption_style:
  case: as_spoken
  font_weight: bold
  text_color: "#FFFFFF"
  background_color: "#28BCA5"
  background_style: rounded_box
  corner_radius: 24
  outline_color: "#394463"
  # `none` on top of a background box: an outline thickens every glyph and
  # costs the line width that long words need.
  outline_or_shadow: none
  # Percent of output height. 3.6% is ~69 px at 1080x1920, which fits an
  # ordinary Polish phrase in two lines. Larger values do not, and captions
  # are never truncated to make them fit.
  font_size_pct: 3.6
  max_lines: 2
  max_words_per_cue: 4
  max_chars_per_cue: 24
  position: lower_safe_zone
  bottom_margin_pct: 22
safe_margins:
  top: 6
  right: 6
  bottom: 22
  left: 6
editing_profile: calm-expert
punch_in_intensity: 0.25
broll_density: 0
music_policy: none
sfx_policy: none
# Voice cleanup. `measured` repairs only what this recording measures as
# broken -- rumble, mains hum, an audible noise floor, hot sibilants, a wide
# loudness range -- each with a ceiling that keeps it the same voice. Every
# render reports what it changed. Set `none` to render the audio as recorded,
# or pass `--no-audio-cleanup` to one render.
audio_cleanup_policy: measured
# Whether this project permits sending a prompt to an image tool. That covers
# the agent's own native ImageGen as well as an API: the prompt leaves the
# machine either way. `none` blocks every route; media is never uploaded.
image_generation_policy: none
target_platforms: []
default_aspect_ratio: "9:16"
default_resolution: "1080x1920"
default_fps_policy: "30"
delivery_output:
"""


def find_project_config(project_root: Path) -> Path | None:
    root = project_root.resolve()
    return next(
        (root / relative for relative in CONFIG_CANDIDATES if (root / relative).is_file()),
        None,
    )


def init_project_config(project_root: Path, *, force: bool = False) -> Path:
    target = project_root.resolve() / ".social-video" / "config.yaml"
    if target.exists() and not force:
        raise ValidationError(f"project config already exists: {target}; use --force to replace it")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(DEFAULT_CONFIG, encoding="utf-8")
    return target


def load_project_config(path: Path) -> ProjectVideoConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValidationError(f"cannot read project video config {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValidationError(f"project video config must be a mapping: {path}")
    # Renames carry over silently; a stale editorial value raises instead.
    migrated = migrate_project_config(raw, source=str(path))
    try:
        config = ProjectVideoConfig.model_validate(migrated)
    except Exception as exc:
        raise ValidationError(f"invalid project video config {path}: {exc}") from exc
    _validate_local_assets(config, path.parent)
    return config


def compile_brand_contract(
    config_path: Path, workspace: Workspace, *, project_root: Path | None = None
) -> BrandContract:
    config_path = config_path.resolve()
    config = load_project_config(config_path)
    root = (project_root or _config_project_root(config_path)).resolve()
    font_file = (
        _resolve_asset(config.font_file, root) if config.font_file else _system_font(config.font)
    )
    if font_file is None:
        raise ValidationError(
            f"configured font family {config.font!r} is not installed and font_file was not set; "
            "install the font inside WSL or point font_file to a project asset"
        )
    logo_file = _resolve_asset(config.logo_file, root) if config.logo_file else None
    if config.logo_usage == "required" and logo_file is None:
        raise ValidationError("branding requires a logo, but logo_file was not configured")
    style = config.caption_style
    brand = BrandProfile(
        name=config.brand_name,
        captions=CaptionStyle(
            font_family=config.font,
            font_file=str(font_file) if font_file else None,
            font_size_pct=style.font_size_pct,
            bold=style.font_weight == "bold",
            primary_colour=style.text_color,
            background_colour=style.background_color,
            background_box=style.background_style.value != "none",
            background_style=style.background_style,
            corner_radius=style.corner_radius,
            outline_colour=style.outline_color,
            outline_or_shadow=style.outline_or_shadow,
            outline_width=3 if style.outline_or_shadow.value == "outline" else 0,
            shadow=3 if style.outline_or_shadow.value == "shadow" else 0,
            position=CaptionPosition(style.position),
            margin_pct=style.bottom_margin_pct,
            case=CaptionCase(style.case),
            max_lines=style.max_lines,
            max_words_per_cue=style.max_words_per_cue,
            max_chars_per_cue=style.max_chars_per_cue,
        ),
        accent_colour=(config.brand_colors or [style.background_color])[0],
        logo_path=str(logo_file) if logo_file else None,
        logo_usage=config.logo_usage,
        safe_margin_pct=max(config.safe_margins.values(), default=6),
        motion_intensity=config.punch_in_intensity,
        broll_density=config.broll_density,
        music_enabled=config.music_policy != "none",
        sfx_enabled=config.sfx_policy != "none",
    )
    width, height = config.resolution
    contract = BrandContract(
        project_config_path=str(config_path),
        project_config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
        project_root=str(root),
        brand=brand,
        output_width=width,
        output_height=height,
        output_fps=config.fps,
        delivery_output=(
            str(_resolve_output(config.delivery_output, root)) if config.delivery_output else None
        ),
        resolved_font_file=str(font_file) if font_file else None,
        resolved_logo_file=str(logo_file) if logo_file else None,
        image_generation_enabled=config.image_generation_policy != "none",
        music_policy=config.music_policy,
        sfx_policy=config.sfx_policy,
        audio_cleanup_policy=config.audio_cleanup_policy,
        target_platforms=list(config.target_platforms),
        safe_margins={
            "top": config.safe_margins.get("top", 6),
            "right": config.safe_margins.get("right", 6),
            "bottom": config.safe_margins.get("bottom", style.bottom_margin_pct),
            "left": config.safe_margins.get("left", 6),
        },
    )
    contract.validate_assets()
    workspace.ensure()
    save_artifact(contract, workspace.brand_contract)
    return contract


def apply_contract_to_edl(edl, contract: BrandContract):
    edl.output_width = contract.output_width
    edl.output_height = contract.output_height
    edl.output_fps = contract.output_fps
    edl.brand_profile = contract.project_config_sha256
    return edl


def _config_project_root(path: Path) -> Path:
    return path.parent.parent if path.parent.name == ".social-video" else path.parent


def _resolve_asset(value: str, root: Path, *, must_exist: bool = True) -> Path:
    path = Path(value).expanduser()
    resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValidationError(f"configured project path escapes project root: {value}") from None
    if must_exist and not resolved.is_file():
        raise ValidationError(f"configured project asset does not exist: {resolved}")
    return resolved


def _validate_local_assets(config: ProjectVideoConfig, config_dir: Path) -> None:
    root = config_dir.parent if config_dir.name == ".social-video" else config_dir
    if config.font_file:
        font = _resolve_asset(config.font_file, root)
        if font.suffix.casefold() not in {".ttf", ".otf", ".woff", ".woff2"}:
            raise ValidationError(f"font_file must be a supported font file: {font}")
    if config.logo_file:
        logo = _resolve_asset(config.logo_file, root)
        if logo.suffix.casefold() not in {".svg", ".png", ".webp", ".jpg", ".jpeg"}:
            raise ValidationError(f"logo_file must be SVG, PNG, WebP or JPEG: {logo}")


def _system_font(family: str) -> Path | None:
    fc_match = shutil.which("fc-match")
    if not fc_match:
        return None
    proc = subprocess.run(
        [fc_match, "-f", "%{family}\n%{file}", family],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    lines = proc.stdout.strip().splitlines()
    if proc.returncode != 0 or len(lines) < 2 or family.casefold() not in lines[0].casefold():
        return None
    candidate = Path(lines[1])
    return candidate.resolve() if candidate and candidate.is_file() else None


def _resolve_output(value: str, root: Path) -> Path:
    if len(value) >= 3 and value[1:3] in {":\\", ":/"}:
        return normalize_user_path(value)
    path = Path(value).expanduser()
    return (root / path).resolve() if not path.is_absolute() else path.resolve()
