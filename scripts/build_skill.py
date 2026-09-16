#!/usr/bin/env python3
"""Build a small reproducible ZIP containing only the canonical skill."""

from __future__ import annotations

import zipfile
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    skill = root / "skills" / "social-video-agent"
    output = root / "dist" / "social-video-agent-skill.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for source in sorted(path for path in skill.rglob("*") if path.is_file()):
            relative = Path("social-video-agent") / source.relative_to(skill)
            info = zipfile.ZipInfo(str(relative), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            zf.writestr(info, source.read_bytes(), compresslevel=9)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
