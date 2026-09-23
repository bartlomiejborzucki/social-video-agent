"""Download a recording the user has the right to edit, and record where it came from.

Opt-in, behind the ``fetch`` extra (yt-dlp). A URL is not permission: most
platforms' terms forbid downloading other people's videos, and editing them is
usually a copyright question. So the command refuses to run without the user's
own statement of their right to the material -- "our webinar", "my channel",
"CC BY 4.0, credited" -- and writes that statement, the URL, what the site says
about the licence, and the file's hash into a provenance record beside it.

The downloaded file then becomes an ordinary immutable source.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

from social_video.errors import SocialVideoError, ToolNotFoundError, ValidationError
from social_video.ffmpeg.run import find_binary
from social_video.fsutil import utc_timestamp
from social_video.schemas.base import save_artifact
from social_video.schemas.source import SourceProvenance

#: Social recordings never need more; capping it keeps a 4K upload from
#: becoming a 10 GB source for a 1080x1920 short.
MAX_HEIGHT = 2160


def provenance_path(media: Path) -> Path:
    return media.with_name(media.name + ".provenance.json")


def fetch_url(url: str, directory: Path, *, rights_statement: str) -> tuple[Path, SourceProvenance]:
    """Download one video (never a playlist) as MP4 and record its provenance."""
    statement = " ".join(rights_statement.split())
    if not statement:
        raise ValidationError(
            "state your right to edit this material with --rights, for example "
            '--rights "our own webinar recording"; a URL alone is not permission'
        )
    if importlib.util.find_spec("yt_dlp") is None:
        raise ToolNotFoundError(
            "downloading from a URL needs yt-dlp: `pip install 'social-video-agent[fetch]'`"
        )
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    directory.mkdir(parents=True, exist_ok=True)
    options = {
        "format": f"bv*[height<={MAX_HEIGHT}]+ba/b[height<={MAX_HEIGHT}]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(directory / "%(title).120B [%(id)s].%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        # Never overwrite: an existing file may already be someone's source.
        "overwrites": False,
        "ffmpeg_location": find_binary("ffmpeg"),
    }
    try:
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
            if info is None:
                raise SocialVideoError(f"nothing could be downloaded from {url}")
            downloads = info.get("requested_downloads") or []
            path = Path(
                downloads[0]["filepath"] if downloads else downloader.prepare_filename(info)
            )
    except DownloadError as exc:
        raise SocialVideoError(f"could not download {url}: {exc}") from exc
    if not path.is_file():
        raise SocialVideoError(f"the download from {url} did not produce a file at {path}")

    record = SourceProvenance(
        url=url,
        webpage_url=str(info.get("webpage_url") or url),
        extractor=str(info.get("extractor_key") or info.get("extractor") or ""),
        video_id=str(info.get("id") or ""),
        title=str(info.get("title") or ""),
        uploader=str(info.get("uploader") or ""),
        license=info.get("license"),
        downloaded_at=utc_timestamp(),
        sha256=_sha256(path),
        rights_statement=statement,
    )
    save_artifact(record, provenance_path(path))
    return path, record


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
