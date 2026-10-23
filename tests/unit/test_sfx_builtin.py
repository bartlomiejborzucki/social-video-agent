from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from social_video.errors import SocialVideoError
from social_video.motion import sfx
from social_video.motion.sfx import builtin_library, library


def _serve(monkeypatch: pytest.MonkeyPatch, payloads: dict[str, bytes]) -> list[str]:
    fetched: list[str] = []

    def urlopen(request, timeout: float = 0):
        fetched.append(request.full_url)
        return io.BytesIO(payloads[request.full_url])

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    return fetched


def test_the_built_in_set_is_downloaded_once_and_found_by_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads = {f"https://example.invalid/{name}": name.encode() for name in sfx.BUILTIN}
    monkeypatch.setattr(
        sfx,
        "BUILTIN",
        {
            name: (url, hashlib.sha256(data).hexdigest())
            for name, (url, data) in zip(sfx.BUILTIN, payloads.items(), strict=True)
        },
    )
    fetched = _serve(monkeypatch, payloads)

    directory = builtin_library(tmp_path / "sfx")
    assert len(fetched) == len(payloads)
    found = library(directory)
    assert found["transition"] and found["graphic"]

    builtin_library(tmp_path / "sfx")
    assert len(fetched) == len(payloads), "a verified file is not downloaded again"


def test_a_built_in_effect_that_does_not_match_its_hash_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sfx, "BUILTIN", {"whoosh.wav": ("https://example.invalid/w", "0" * 64)})
    _serve(monkeypatch, {"https://example.invalid/w": b"something else"})
    with pytest.raises(SocialVideoError, match="pinned hash"):
        builtin_library(tmp_path / "sfx")
    assert not (tmp_path / "sfx" / "whoosh.wav").exists()
