"""Atomic file publication and timestamps shared by every writer.

A finished file only ever appears under its final name complete: it is written
to a private sibling first, flushed to disk, and moved into place with an
atomic rename. The sibling's name is unique per write, so two concurrent runs
publishing the same target cannot trample each other's half-written file.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


@contextmanager
def atomic_target(target: Path) -> Iterator[Path]:
    """Yield a staging path; publish it as ``target`` only if the block succeeds.

    The staging path ends in ``.partial``, so a writer that infers the format
    from the file name (Pillow does) must be told the format explicitly.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.{uuid4().hex}.partial")
    try:
        yield partial
        # Windows refuses to flush a read-only handle (EBADF), so open for update.
        with partial.open("r+b") as handle:
            os.fsync(handle.fileno())
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def atomic_copy(source: Path, target: Path) -> Path:
    """Copy ``source`` to ``target``, which never exists half-written."""
    with atomic_target(target) as partial:
        shutil.copy2(source, partial)
    return target


def atomic_write_bytes(target: Path, data: bytes) -> Path:
    with atomic_target(target) as partial:
        partial.write_bytes(data)
    return target


def utc_timestamp() -> str:
    """Now, in UTC, as the ISO-8601 seconds-precision string every artifact uses."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
