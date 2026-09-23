"""Fetching a URL: real yt-dlp against a local server, never the internet."""

from __future__ import annotations

import functools
import hashlib
import http.server
import threading
from pathlib import Path

import pytest

from social_video.errors import ValidationError
from social_video.fetch import fetch_url, provenance_path
from social_video.schemas.base import load_artifact
from social_video.schemas.source import SourceProvenance
from tests.conftest import make_video, requires_ffmpeg

pytest.importorskip("yt_dlp")
pytestmark = [pytest.mark.integration, requires_ffmpeg]


@pytest.fixture
def served(tmp_path: Path):
    root = tmp_path / "www"
    make_video(root / "webinar.mp4", duration=1.5)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/webinar.mp4", root / "webinar.mp4"
    finally:
        server.shutdown()


def test_a_download_is_recorded_with_its_url_hash_and_the_users_right(
    served, tmp_path: Path
) -> None:
    url, original = served

    path, record = fetch_url(url, tmp_path / "sources", rights_statement=" our own  webinar ")

    assert path.is_file() and path.parent == tmp_path / "sources"
    assert path.read_bytes() == original.read_bytes()
    saved = load_artifact(SourceProvenance, provenance_path(path))
    assert saved == record
    assert saved.url == url
    assert saved.rights_statement == "our own webinar"
    assert saved.sha256 == hashlib.sha256(original.read_bytes()).hexdigest()
    assert saved.extractor.lower() == "generic"


def test_no_statement_of_rights_means_no_download(served, tmp_path: Path) -> None:
    url, _ = served

    with pytest.raises(ValidationError, match="a URL alone is not permission"):
        fetch_url(url, tmp_path / "sources", rights_statement="   ")

    assert not (tmp_path / "sources").exists()
