"""Deterministically locate likely brand and editing context without repo ingestion."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import yaml

from social_video.errors import ValidationError
from social_video.fingerprint import file_fingerprint
from social_video.fsutil import utc_timestamp
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.project_context import (
    ContextClaim,
    ContextConfidence,
    ContextSource,
    ContextSources,
    ProjectConfig,
    ProjectContext,
)
from social_video.workspace.layout import Workspace

IGNORED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "coverage",
        ".cache",
        ".next",
        "target",
        "vendor",
        "models",
        "model-cache",
        "frames",
        "previews",
        "renders",
        "final",
        "qa",
    }
)
HIGH_VALUE_DIRS = frozenset(
    {
        "docs",
        "brand",
        "branding",
        "assets",
        "media",
        "marketing",
        "social",
        "content",
        "design",
        "guidelines",
        "templates",
        "references",
    }
)
NAME_TERMS = (
    "brand",
    "branding",
    "brandbook",
    "brand-book",
    "brand-guide",
    "identity",
    "styleguide",
    "style-guide",
    "design-system",
    "tone",
    "voice",
    "copywriting",
    "social-media",
    "video-guide",
    "video-guidelines",
    "editing",
    "montaz",
    "montaż",
    "reels",
    "shorts",
    "tiktok",
    "youtube",
    "instagram",
    "księga-marki",
    "zasady-montażu",
)
#: Terms a brand or editing document uses and an ordinary report does not.
#: Single generic words ("video", "social", "colour") were dropped: every
#: status report and meeting note contains several of them, which is how a
#: reports-heavy project used to fill the candidate list with weak hints.
TEXT_TERMS = (
    "brand",
    "brandbook",
    "brand guidelines",
    "tone of voice",
    "tone-of-voice",
    "typography",
    "colour palette",
    "color palette",
    "style guide",
    "styleguide",
    "logo usage",
    "caption style",
    "subtitle style",
    "safe zone",
    "księga marki",
    "identyfikacja wizualna",
    "zasady montażu",
    "montaż",
    "napisy",
    "czcionka",
    "paleta kolorów",
)
#: Filename fragments that make an asset reusable branding rather than stock.
ASSET_TERMS = ("logo", "font", "intro", "outro", "template")
TEXT_EXTENSIONS = frozenset({".md", ".txt", ".yaml", ".yml", ".json", ".toml", ".css"})
DOCUMENT_EXTENSIONS = frozenset({".pdf", ".docx", ".pptx"})
ASSET_EXTENSIONS = frozenset(
    {
        ".svg",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".ttf",
        ".otf",
        ".woff",
        ".woff2",
        ".ass",
        ".srt",
        ".vtt",
        ".mp3",
        ".wav",
    }
)
CONFIG_PATHS = (
    Path(".social-video/config.yaml"),
    Path("social-video.yaml"),
    Path("social-video.yml"),
)
#: A candidate has to be readable prose, a brand-capable document, or a
#: reusable asset. A report archive whose name happens to contain "brand" is
#: none of those, so extension is checked before any name scoring.
CANDIDATE_EXTENSIONS = TEXT_EXTENSIONS | DOCUMENT_EXTENSIONS | ASSET_EXTENSIONS
#: Tool state lives in dot directories; only our own config directory is read.
SCANNED_DOT_DIRS = frozenset({".social-video"})
#: An agent skill tree is instructions for a tool, never guidance about this
#: project's brand, wherever it is installed (`.codex/skills`, `skills/`, ...).
SKILL_MANIFEST = "skill.md"
MAX_FILES_SCANNED = 5000
MAX_CANDIDATES = 80
MAX_FILES_READ = 20
MAX_TEXT_BYTES = 64 * 1024
MAX_EXCERPT = 2000
MIN_CANDIDATE_SCORE = 25
MIN_TEXT_KEYWORD_HITS = 3
CONFIG_REFERENCE_SCORE = 90


def resolve_project_root(explicit: str | Path | None = None, *, cwd: Path | None = None) -> Path:
    """Resolve only an explicit path or the current directory's ancestry."""
    start = Path(explicit).expanduser() if explicit is not None else (cwd or Path.cwd())
    start = start.resolve(strict=False)
    if start.is_file():
        start = start.parent
    if explicit is not None:
        if not start.is_dir():
            raise ValidationError(f"target project root is not a directory: {start}")
        return start
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return start


def discover_project_context(
    project_root: str | Path,
    workspace: Workspace,
    *,
    refresh: bool = False,
) -> tuple[ProjectContext, ContextSources]:
    """Scan, cache, and persist project context under one edit workspace."""
    root = resolve_project_root(project_root)
    workspace.ensure()
    sources = _scan(root, excluded_roots=(workspace.root, workspace.heavy_root))
    if not refresh and workspace.context_sources.is_file() and workspace.project_context.is_file():
        cached_sources = load_artifact(ContextSources, workspace.context_sources)
        if (
            cached_sources.target_project_root == str(root)
            and cached_sources.fingerprint == sources.fingerprint
        ):
            cached = load_artifact(ProjectContext, workspace.project_context)
            cached.cache_status = "reused"
            return cached, cached_sources

    context = _build_context(root, sources)
    save_artifact(sources, workspace.context_sources)
    save_artifact(context, workspace.project_context)
    workspace.project_context_summary.write_text(_to_markdown(context, sources), encoding="utf-8")
    return context, sources


def _scan(root: Path, *, excluded_roots: tuple[Path, ...] = ()) -> ContextSources:
    raw: list[tuple[Path, int, list[str], str]] = []
    considered = 0
    truncated = False
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        dirs[:] = sorted(
            d
            for d in dirs
            if not _is_ignored_dir(d)
            and not any(_is_within(current_path / d, excluded) for excluded in excluded_roots)
        )
        depth = len(current_path.relative_to(root).parts)
        if depth >= 6:
            dirs[:] = []
        if current_path != root and any(name.casefold() == SKILL_MANIFEST for name in files):
            # An installed agent skill describes a tool, not this project.
            dirs[:] = []
            continue
        for filename in sorted(files):
            considered += 1
            if considered > MAX_FILES_SCANNED:
                truncated = True
                break
            path = current_path / filename
            try:
                path.resolve(strict=False).relative_to(root)
            except ValueError:
                # A symlinked file may appear lexically inside the project but
                # resolve outside it. Discovery must not cross that boundary.
                continue
            scored = _score_candidate(root, path)
            if scored is not None:
                raw.append((path, *scored))
        if truncated:
            break
    raw = _include_config_references(root, raw)
    raw.sort(key=lambda item: (-item[1], item[0].relative_to(root).as_posix().casefold()))
    candidate_overflow = len(raw) > MAX_CANDIDATES
    raw = raw[:MAX_CANDIDATES]
    candidates = [
        _context_source(root, path, score, signals, source_type, read=index < MAX_FILES_READ)
        for index, (path, score, signals, source_type) in enumerate(raw)
    ]
    digest_payload = [(item.path, item.fingerprint, item.relevance) for item in candidates]
    digest = hashlib.sha256(
        json.dumps(digest_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ContextSources(
        target_project_root=str(root),
        fingerprint=digest,
        scanned_at=utc_timestamp(),
        candidates_considered=considered,
        truncated=truncated or candidate_overflow,
        sources=candidates,
    )


def _is_ignored_dir(name: str) -> bool:
    folded = name.casefold()
    if folded.startswith("."):
        return folded not in SCANNED_DOT_DIRS
    return folded in IGNORED_DIRS


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return False
    return True


def _score_candidate(root: Path, path: Path) -> tuple[int, list[str], str] | None:
    relative = path.relative_to(root)
    lowered = relative.as_posix().casefold()
    suffix = path.suffix.casefold()
    signals: list[str] = []
    if relative in CONFIG_PATHS:
        return 100, ["explicit social-video configuration"], "project_config"
    if path.name.casefold() == "agents.md":
        return 96, ["applicable repository instructions"], "agents"
    if suffix not in CANDIDATE_EXTENSIONS:
        return None
    source_type = "asset" if suffix in ASSET_EXTENSIONS else "document"
    score = 0
    matched = [term for term in NAME_TERMS if term in lowered]
    if matched:
        score += min(50, 20 + len(matched) * 5)
        signals.append("filename: " + ", ".join(matched[:5]))
    reusable_asset = suffix in ASSET_EXTENSIONS and any(term in lowered for term in ASSET_TERMS)
    if reusable_asset:
        score += 35
        signals.append("likely reusable asset")
    if suffix in DOCUMENT_EXTENSIONS:
        score += 15
        signals.append("brand-capable document")
    hits = 0
    if suffix in TEXT_EXTENSIONS and not matched and not reusable_asset:
        hits = _text_keyword_hits(path)
        if hits >= MIN_TEXT_KEYWORD_HITS:
            score += min(30, 10 + hits * 5)
            signals.append(f"{hits} brand-specific keyword hit(s)")
    if not (matched or reusable_asset or hits >= MIN_TEXT_KEYWORD_HITS):
        # Sitting in docs/ is a location, not evidence about this brand.
        # Without one real signal the file is not a candidate at all.
        return None
    if any(part.casefold() in HIGH_VALUE_DIRS for part in relative.parts[:-1]):
        score += 15
        signals.append("high-value directory")
    if score < MIN_CANDIDATE_SCORE:
        return None
    confidence = "explicit" if score >= 80 else "strong" if score >= 45 else "weak"
    signals.append(f"{confidence} candidate")
    return min(score, 100), signals, source_type


def _text_keyword_hits(path: Path) -> int:
    try:
        text = path.read_bytes()[:MAX_TEXT_BYTES].decode("utf-8", "ignore").casefold()
    except OSError:
        return 0
    return sum(1 for term in TEXT_TERMS if term in text)


def _include_config_references(
    root: Path,
    raw: list[tuple[Path, int, list[str], str]],
) -> list[tuple[Path, int, list[str], str]]:
    """Include local files named by explicit config even if heuristics would miss them."""
    indexed = {path: index for index, (path, *_) in enumerate(raw)}
    configs = sorted(
        (entry for entry in raw if entry[3] == "project_config"),
        key=lambda entry: CONFIG_PATHS.index(entry[0].relative_to(root)),
    )
    signal = "referenced by explicit social-video configuration"
    for config_path, *_ in configs:
        config = _load_config(config_path).model_dump(exclude_none=True)
        asset_references = set(_config_asset_references(config))
        for reference in _config_references(config):
            path = (root / reference).resolve(strict=False)
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise ValidationError(
                    f"project video config reference leaves target project root: {reference}"
                ) from exc
            if not path.is_file():
                continue
            source_type = (
                "asset"
                if reference in asset_references or path.suffix.casefold() in ASSET_EXTENSIONS
                else "document"
            )
            existing = indexed.get(path)
            if existing is None:
                indexed[path] = len(raw)
                raw.append((path, CONFIG_REFERENCE_SCORE, [signal], source_type))
                continue
            # Naming a file in the config is explicit evidence, so it must not
            # be ranked by whatever the filename heuristic happened to score.
            _, score, signals, found_type = raw[existing]
            raw[existing] = (
                path,
                max(score, CONFIG_REFERENCE_SCORE),
                [signal, *signals],
                found_type if found_type != "document" else source_type,
            )
    return raw


def _context_source(
    root: Path,
    path: Path,
    score: int,
    signals: list[str],
    source_type: str,
    *,
    read: bool,
) -> ContextSource:
    extracted: dict[str, object] = {}
    excerpt = ""
    if source_type == "project_config":
        extracted = _load_config(path).model_dump(exclude_none=True)
    elif read:
        excerpt = _extract_text(path)
    confidence = (
        ContextConfidence.EXPLICIT
        if source_type in {"project_config", "agents"} or score >= 80
        else ContextConfidence.STRONGLY_INFERRED
        if score >= 45
        else ContextConfidence.WEAK_HINT
    )
    return ContextSource(
        path=path.relative_to(root).as_posix(),
        source_type=source_type,
        relevance=score,
        confidence=confidence,
        fingerprint=file_fingerprint(path),
        size_bytes=path.stat().st_size,
        signals=signals,
        extracted_facts=extracted,
        excerpt=excerpt,
    )


def _load_config(path: Path) -> ProjectConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValidationError(f"cannot read project video config {path}: {exc}") from exc
    try:
        return ProjectConfig.model_validate(raw)
    except Exception as exc:
        raise ValidationError(f"invalid project video config {path}: {exc}") from exc


def _extract_text(path: Path) -> str:
    suffix = path.suffix.casefold()
    try:
        if suffix in TEXT_EXTENSIONS or suffix == ".svg":
            return path.read_bytes()[:MAX_TEXT_BYTES].decode("utf-8", "ignore")[:MAX_EXCERPT]
        if suffix == ".pdf" and shutil.which("pdftotext"):
            proc = subprocess.run(
                ["pdftotext", "-f", "1", "-l", "4", str(path), "-"],
                capture_output=True,
                check=False,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            return proc.stdout[:MAX_EXCERPT] if proc.returncode == 0 else ""
        if suffix in {".docx", ".pptx"}:
            return _office_text(path)[:MAX_EXCERPT]
    except (OSError, subprocess.TimeoutExpired, zipfile.BadZipFile, ElementTree.ParseError):
        return ""
    return ""


def _office_text(path: Path) -> str:
    prefixes = ("word/document.xml",) if path.suffix.casefold() == ".docx" else ("ppt/slides/",)
    chunks: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if any(name.startswith(p) for p in prefixes)]
        for name in sorted(names)[:12]:
            root = ElementTree.fromstring(archive.read(name))
            chunks.extend(node.text or "" for node in root.iter() if node.text)
    return " ".join(chunks)


def _build_context(root: Path, sources: ContextSources) -> ProjectContext:
    configs = [item for item in sources.sources if item.source_type == "project_config"]
    selected = configs[0] if configs else None
    config = dict(selected.extracted_facts) if selected else {}
    conflicts: list[str] = []
    for other in configs[1:]:
        for key, value in other.extracted_facts.items():
            if key in config and config[key] != value:
                conflicts.append(f"{configs[0].path} overrides conflicting {key!r} in {other.path}")
    paths = [item.path for item in sources.sources]
    logos = [path for path in paths if "logo" in path.casefold()]
    fonts = [
        path
        for path in paths
        if Path(path).suffix.casefold() in {".ttf", ".otf", ".woff", ".woff2"}
    ]
    known_assets = [item.path for item in sources.sources if item.source_type == "asset"]
    style_sources = [
        item.path
        for item in sources.sources
        if item.source_type in {"project_config", "document"} and item.relevance >= 35
    ]
    direct = _style_config_references(config)
    ordered_sources = ([selected.path] if selected else []) + direct + style_sources
    style_sources = list(dict.fromkeys(ordered_sources))
    missing_references = [
        reference for reference in _config_references(config) if not (root / reference).is_file()
    ]
    return ProjectContext(
        target_project_root=str(root),
        generated_at=utc_timestamp(),
        source_fingerprint=sources.fingerprint,
        explicit_config=selected.path if selected else None,
        applicable_agents_files=[
            item.path for item in sources.sources if item.source_type == "agents"
        ],
        brand={"name": config["brand_name"]} if config.get("brand_name") else {},
        voice={"language": config.get("content_language") or config.get("language")}
        if config.get("content_language") or config.get("language")
        else {},
        visual_style={
            key: config[key]
            for key in ("punch_in_intensity", "broll_density", "image_generation_policy")
            if key in config
        },
        fonts=[
            value
            for value in [
                config.get("font"),
                config.get("font_file"),
                *(config.get("font_fallback") or []),
            ]
            if value
        ]
        or fonts,
        colors=config.get("brand_colors") or [],
        logos=[value for value in (config.get("logo_file"), config.get("logo")) if value] or logos,
        video_guidelines=[value for value in [config.get("editing_guide")] if value],
        caption_guidelines=config.get("caption_style") or {},
        editing_guidelines={
            key: config[key]
            for key in ("editing_profile", "punch_in_intensity", "broll_density")
            if key in config
        },
        audio_guidelines={
            key: config[key] for key in ("music_policy", "sfx_policy") if key in config
        },
        known_assets=known_assets,
        output_requirements={
            key: config[key]
            for key in (
                "safe_margins",
                "default_aspect_ratio",
                "default_resolution",
                "default_fps_policy",
                "target_platforms",
                "delivery_output",
                "preferred_output_directory",
            )
            if key in config
        },
        claims=_config_claims(selected.path, config) if selected else [],
        style_sources=style_sources,
        conflicts=conflicts,
        unknowns=[
            f"Configured local context file was not found: {path}" for path in missing_references
        ]
        or (
            []
            if style_sources
            else ["No explicit brandbook or project-specific video guideline was found."]
        ),
        config=config,
    )


def _config_references(config: dict[str, object]) -> list[str]:
    values = [
        config.get(key)
        for key in (
            "brandbook",
            "editing_guide",
            "logo",
            "logo_file",
            "font_file",
            "intro",
            "outro",
        )
    ]
    values.append(config.get("font"))
    fallbacks = config.get("font_fallback")
    if isinstance(fallbacks, list):
        values.extend(fallbacks)
    return list(
        dict.fromkeys(
            str(value)
            for value in values
            if isinstance(value, str) and _looks_like_local_path(value)
        )
    )


def _config_claims(source: str, config: dict[str, object]) -> list[ContextClaim]:
    mappings = {
        "brand_name": ("brand", "name"),
        "language": ("voice", "language"),
        "content_language": ("voice", "content_language"),
        "editing_profile": ("editing", "profile"),
        "caption_style": ("captions", "style"),
        "font": ("visual", "font"),
        "brand_colors": ("visual", "colors"),
        "music_policy": ("audio", "music_policy"),
        "sfx_policy": ("audio", "sfx_policy"),
    }
    return [
        ContextClaim(
            category=category,
            key=claim_key,
            value=config[key],
            source=source,
            confidence=ContextConfidence.EXPLICIT,
        )
        for key, (category, claim_key) in mappings.items()
        if key in config
    ]


def _style_config_references(config: dict[str, object]) -> list[str]:
    return [
        str(config[key])
        for key in ("brandbook", "editing_guide")
        if isinstance(config.get(key), str)
    ]


def _config_asset_references(config: dict[str, object]) -> list[str]:
    keys = ("logo", "logo_file", "font_file", "intro", "outro", "font")
    values = [config.get(key) for key in keys]
    fallbacks = config.get("font_fallback")
    if isinstance(fallbacks, list):
        values.extend(fallbacks)
    return [
        str(value) for value in values if isinstance(value, str) and _looks_like_local_path(value)
    ]


def _looks_like_local_path(value: str) -> bool:
    return (
        "/" in value
        or "\\" in value
        or Path(value).suffix.casefold()
        in (TEXT_EXTENSIONS | DOCUMENT_EXTENSIONS | ASSET_EXTENSIONS)
    )


def _to_markdown(context: ProjectContext, sources: ContextSources) -> str:
    lines = [
        "# Project context",
        "",
        f"Target project: `{context.target_project_root}`",
        f"Cache: `{context.cache_status}`",
        "",
        "## Explicit configuration",
        "",
    ]
    if context.explicit_config:
        lines.append(f"- `{context.explicit_config}` overrides heuristic context.")
    else:
        lines.append("- No social-video.yaml configuration found; defaults follow discovery.")
    lines.extend(["", "## Context sources", ""])
    for source in sources.sources[:20]:
        lines.append(
            f"- `{source.path}` — {source.confidence.value}, relevance {source.relevance}/100"
        )
    if not sources.sources:
        lines.append("- No relevant project guidance found; use social-video-agent defaults.")
    if context.claims:
        lines.extend(["", "## Explicit facts", ""])
        for claim in context.claims:
            lines.append(
                f"- `{claim.category}.{claim.key}`: `{claim.value}` "
                f"— `{claim.source}` ({claim.confidence.value})"
            )
    if context.conflicts:
        lines.extend(["", "## Conflicts", "", *(f"- {item}" for item in context.conflicts)])
    if context.unknowns:
        lines.extend(["", "## Unknowns", "", *(f"- {item}" for item in context.unknowns)])
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "Facts are source-linked. Heuristic candidates are not automatically treated as rules.",
            "Current user instructions override project defaults.",
            "",
        ]
    )
    return "\n".join(lines)
