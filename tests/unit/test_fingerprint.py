"""Tests for cache fingerprints.

Upstream caches on the filename alone, so a re-exported source is never
noticed. These tests pin down that content decides, and mtime does not.
"""

from __future__ import annotations

import os

from social_video.fingerprint import cache_key, file_fingerprint, options_fingerprint


def write(tmp_path, name, data: bytes):
    p = tmp_path / name
    p.write_bytes(data)
    return p


class TestFileFingerprint:
    def test_same_content_same_fingerprint(self, tmp_path):
        a = write(tmp_path, "a.bin", b"hello world" * 100)
        b = write(tmp_path, "b.bin", b"hello world" * 100)
        assert file_fingerprint(a) == file_fingerprint(b)

    def test_changed_content_changes_fingerprint(self, tmp_path):
        a = write(tmp_path, "a.bin", b"hello world" * 100)
        before = file_fingerprint(a)
        a.write_bytes(b"hello worlD" * 100)
        assert file_fingerprint(a) != before

    def test_changed_length_changes_fingerprint(self, tmp_path):
        a = write(tmp_path, "a.bin", b"x" * 1000)
        before = file_fingerprint(a)
        a.write_bytes(b"x" * 1001)
        assert file_fingerprint(a) != before

    def test_touch_does_not_change_fingerprint(self, tmp_path):
        # Copying a file or checking it out of git changes mtime. That must not
        # throw away an expensive transcript.
        a = write(tmp_path, "a.bin", b"stable" * 500)
        before = file_fingerprint(a)
        os.utime(a, (0, 0))
        assert file_fingerprint(a) == before

    def test_detects_a_change_only_at_the_tail(self, tmp_path):
        # Remuxing often rewrites only the trailing atom, which is why both ends
        # are hashed rather than just the head.
        big = bytearray(b"a" * (3 * 1024 * 1024))
        a = write(tmp_path, "a.bin", bytes(big))
        before = file_fingerprint(a)
        big[-10:] = b"different!"
        a.write_bytes(bytes(big))
        assert file_fingerprint(a) != before


class TestOptionsFingerprint:
    def test_order_does_not_matter(self):
        assert options_fingerprint(a=1, b=2) == options_fingerprint(b=2, a=1)

    def test_value_change_matters(self):
        assert options_fingerprint(model="small") != options_fingerprint(model="base")

    def test_none_is_the_same_as_absent(self):
        assert options_fingerprint(a=1, b=None) == options_fingerprint(a=1)

    def test_cache_key_combines_both(self, tmp_path):
        a = write(tmp_path, "a.bin", b"data" * 100)
        assert cache_key(a, model="small") != cache_key(a, model="base")
        assert cache_key(a, model="small") == cache_key(a, model="small")
