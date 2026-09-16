from __future__ import annotations

import hashlib

import pytest

from social_video.errors import SocialVideoError
from social_video.ffmpeg.bootstrap import _guard_members, _verify_checksum


def test_checksum_manifest_accepts_matching_asset(tmp_path):
    archive = tmp_path / "ffmpeg.tar.xz"
    archive.write_bytes(b"verified bytes")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksums = tmp_path / "checksums.sha256"
    checksums.write_text(f"{digest} *{archive.name}\n", encoding="utf-8")
    _verify_checksum(archive, checksums)


def test_checksum_manifest_rejects_tampered_asset(tmp_path):
    archive = tmp_path / "ffmpeg.tar.xz"
    archive.write_bytes(b"tampered")
    checksums = tmp_path / "checksums.sha256"
    checksums.write_text(f"{'0' * 64}  {archive.name}\n", encoding="utf-8")
    with pytest.raises(SocialVideoError, match="verification failed"):
        _verify_checksum(archive, checksums)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "folder/../../escape"])
def test_archive_guard_rejects_traversal_and_absolute_names(name):
    with pytest.raises(SocialVideoError, match="unsafe archive"):
        _guard_members([name])
