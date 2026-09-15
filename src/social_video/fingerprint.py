"""Content fingerprints, so a cache can tell when its input actually changed.

Upstream video-use caches transcripts by checking whether a file named after
the source stem exists. That cannot detect a re-exported source, collides
between same-named files in different folders, and ignores the language and
speaker-count settings entirely -- so re-running with different options
silently returns the previous result.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

#: How much of each end of the file to read. Reading a whole 4K master to decide
#: whether to re-transcribe would cost more than the transcription.
_CHUNK = 1024 * 1024


def file_fingerprint(path: str | Path) -> str:
    """Fingerprint a media file cheaply but honestly.

    Hashes the size, the first megabyte, and the last megabyte. A re-encode, a
    re-export, or a trim changes at least one of the three. Reading both ends
    rather than just the head matters: many editors rewrite only the trailing
    ``moov`` atom when remuxing.

    Modification time is deliberately excluded: copying a file or checking it
    out of git changes mtime without changing content, and that should not
    invalidate an expensive transcript.
    """
    p = Path(path)
    size = p.stat().st_size
    h = hashlib.blake2b(digest_size=16)
    h.update(str(size).encode())
    with p.open("rb") as f:
        h.update(f.read(_CHUNK))
        if size > _CHUNK * 2:
            f.seek(-_CHUNK, 2)
            h.update(f.read(_CHUNK))
    return h.hexdigest()


def options_fingerprint(**options: Any) -> str:
    """Fingerprint the settings that would change a result.

    ``None`` values are dropped so that omitting an option and passing it as
    ``None`` are the same cache entry.
    """
    cleaned = {k: v for k, v in sorted(options.items()) if v is not None}
    payload = json.dumps(cleaned, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.blake2b(payload.encode("utf-8"), digest_size=8).hexdigest()


def cache_key(path: str | Path, **options: Any) -> str:
    """Combined key for one source under one set of options."""
    return f"{file_fingerprint(path)}.{options_fingerprint(**options)}"
