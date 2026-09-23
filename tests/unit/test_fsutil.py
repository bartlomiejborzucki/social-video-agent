"""Files appear under their final name complete, or not at all."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from social_video.fsutil import atomic_copy, atomic_target, utc_timestamp


def test_a_failed_write_leaves_the_previous_file_and_no_debris(tmp_path: Path) -> None:
    target = tmp_path / "out" / "final.mp4"
    target.parent.mkdir()
    target.write_bytes(b"good")

    with pytest.raises(RuntimeError), atomic_target(target) as partial:
        partial.write_bytes(b"half")
        raise RuntimeError("interrupted")

    assert target.read_bytes() == b"good"
    assert [p.name for p in target.parent.iterdir()] == ["final.mp4"]


def test_concurrent_writers_never_share_a_staging_name(tmp_path: Path) -> None:
    target = tmp_path / "final.json"

    with atomic_target(target) as first, atomic_target(target) as second:
        assert first != second
        first.write_bytes(b"1")
        second.write_bytes(b"2")

    # The outer block publishes last, and the last publisher wins whole.
    assert target.read_bytes() == b"1"
    assert [p.name for p in tmp_path.iterdir()] == ["final.json"]


def test_copy_creates_missing_parents(tmp_path: Path) -> None:
    source = tmp_path / "a.bin"
    source.write_bytes(b"data")

    target = atomic_copy(source, tmp_path / "deep" / "er" / "b.bin")

    assert target.read_bytes() == b"data"


def test_timestamps_are_utc_to_the_second() -> None:
    stamp = utc_timestamp()

    parsed = datetime.fromisoformat(stamp)
    assert parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0
    assert parsed.microsecond == 0


def test_the_flush_uses_a_handle_windows_will_flush(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows' fsync fails with EBADF on a read-only handle; emulate that rule."""
    import errno
    import os
    import sys

    from social_video import fsutil

    real_fsync = os.fsync

    def windows_like_fsync(fd: int) -> None:
        if sys.platform != "win32":
            import fcntl

            if fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY:
                raise OSError(errno.EBADF, "Bad file descriptor")
        real_fsync(fd)

    monkeypatch.setattr(fsutil.os, "fsync", windows_like_fsync)

    with atomic_target(tmp_path / "final.json") as partial:
        partial.write_text("{}", encoding="utf-8")

    assert (tmp_path / "final.json").read_text(encoding="utf-8") == "{}"
