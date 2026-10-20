"""Building the source manifest from files on disk."""

from __future__ import annotations

from pathlib import Path

from social_video.errors import SocialVideoError
from social_video.ffmpeg.probe import probe
from social_video.fingerprint import file_fingerprint
from social_video.schemas.source import SourceEntry, SourceManifest

#: Extensions we will consider. Matched case-insensitively, unlike upstream's
#: literal set which silently skips `.M4V`, `.webm`, `.mts` and `.Mp4`.
MEDIA_EXTENSIONS = frozenset(
    {
        ".mp4",
        ".mov",
        ".mkv",
        ".avi",
        ".m4v",
        ".webm",
        ".mpg",
        ".mpeg",
        ".mts",
        ".m2ts",
        ".ts",
        ".wmv",
        ".flv",
        ".3gp",
        ".insv",
        ".wav",
        ".mp3",
        ".m4a",
        ".aac",
        ".flac",
        ".ogg",
        ".opus",
    }
)


def is_media(path: Path) -> bool:
    return path.suffix.lower() in MEDIA_EXTENSIONS


def describe_source(path: str | Path, *, source_id: str | None = None) -> SourceEntry:
    """Probe one file into a manifest entry."""
    p = Path(path).expanduser().resolve()
    info = probe(p)
    video = info.video
    return SourceEntry(
        id=source_id or p.stem,
        path=str(p),
        fingerprint=file_fingerprint(p),
        size_bytes=info.size_bytes,
        duration=info.duration,
        width=video.width if video else 0,
        height=video.height if video else 0,
        rotation=video.rotation if video else 0,
        frame_rate=video.frame_rate if video else "0/1",
        pix_fmt=video.pix_fmt if video else "",
        color_transfer=video.color_transfer if video else "",
        video_codec=video.codec if video else "",
        audio_tracks=len(info.audio),
    )


def build_manifest(paths: list[str | Path], *, recursive: bool = True) -> SourceManifest:
    """Build a manifest from files and directories.

    Ids are file stems, disambiguated by parent directory when two files share
    one. Upstream keys its cache on the stem alone, so two different `clip.mp4`
    files in different folders collide on a single entry.
    """
    found: list[Path] = []
    for raw in paths:
        p = Path(raw).expanduser().resolve()
        if p.is_dir():
            walker = p.rglob("*") if recursive else p.iterdir()
            found.extend(sorted(x for x in walker if x.is_file() and is_media(x)))
        elif p.is_file():
            found.append(p)
        else:
            raise SocialVideoError(f"not found: {p}")

    if not found:
        raise SocialVideoError(
            "no media files found. Supported extensions: " + ", ".join(sorted(MEDIA_EXTENSIONS))
        )

    stems: dict[str, int] = {}
    for p in found:
        stems[p.stem] = stems.get(p.stem, 0) + 1

    entries: list[SourceEntry] = []
    for p in found:
        sid = p.stem if stems[p.stem] == 1 else f"{p.parent.name}_{p.stem}"
        entries.append(describe_source(p, source_id=sid))
    return SourceManifest(sources=entries)


def id_for_path(manifest: SourceManifest, path: str | Path) -> str | None:
    """The id a manifest already gives this file, if any."""
    wanted = Path(path).expanduser().resolve()
    for entry in manifest.sources:
        if Path(entry.path).expanduser().resolve() == wanted:
            return entry.id
    return None


def merge_manifest(existing: SourceManifest, added: SourceManifest) -> SourceManifest:
    """Every source of both, the added entry winning for a shared id or file."""
    added_paths = {Path(e.path).resolve() for e in added.sources}
    kept = [
        e
        for e in existing.sources
        if e.id not in added.ids and Path(e.path).resolve() not in added_paths
    ]
    return SourceManifest(sources=[*kept, *added.sources])


def add_source(
    manifest: SourceManifest, path: str | Path, *, source_id: str | None = None
) -> tuple[SourceManifest, SourceEntry, str]:
    """Add one file to a manifest, or refresh its entry. Returns what happened.

    An id already taken by a different file is refused rather than repointed:
    the EDL and the transcripts name sources by id, so a silent swap would
    cut picture from a recording nobody chose.
    """
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise SocialVideoError(f"not found: {p}")
    if not is_media(p):
        raise SocialVideoError(
            f"{p.name} is not a media file. Supported extensions: "
            + ", ".join(sorted(MEDIA_EXTENSIONS))
        )
    known = id_for_path(manifest, p)
    sid = source_id or known or p.stem
    if not sid.strip() or "/" in sid or "\\" in sid:
        raise SocialVideoError(f"invalid source id {sid!r}")
    for entry in manifest.sources:
        if entry.id == sid and Path(entry.path).resolve() != p:
            raise SocialVideoError(
                f"source id {sid!r} already names {entry.path}; choose another with --id"
            )
    if known is not None and known != sid:
        raise SocialVideoError(
            f"{p.name} is already in the manifest as {known!r}; transcripts and plans use "
            "that id, so it is not renamed"
        )
    entry = describe_source(p, source_id=sid)
    previous = next((e for e in manifest.sources if e.id == sid), None)
    if previous is None:
        status = "added"
    elif previous.fingerprint != entry.fingerprint:
        status = "updated"
    else:
        status = "unchanged"
    sources = [e for e in manifest.sources if e.id != sid]
    sources.append(entry)
    return SourceManifest(sources=sources), entry, status
