#!/usr/bin/env python3
"""Compare the commits recorded in upstreams.yml against upstream HEAD.

Writes a report to upstream-report.json and sets the `changed` output. Does not
modify anything in the repository: detection only.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
REPORT = ROOT / "upstream-report.json"

#: Entries we only note in passing rather than raising an issue for.
QUIET = {"watch"}


def remote_head(url: str) -> str | None:
    """Resolve the default branch HEAD without cloning."""
    try:
        out = subprocess.run(
            ["git", "ls-remote", url, "HEAD"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    return out.stdout.split()[0]


def main() -> int:
    data = yaml.safe_load((ROOT / "upstreams.yml").read_text(encoding="utf-8"))
    moved = []

    for entry in data.get("upstreams", []):
        recorded = str(entry.get("reviewed_sha", "")).strip()
        url = entry.get("url")
        if not url or "@" in recorded:
            # A date-pinned entry has no commit to compare; skip quietly.
            continue

        head = remote_head(url)
        if head is None:
            print(f"?? {entry['repository']}: could not reach upstream")
            continue

        if head.startswith(recorded) or recorded.startswith(head[:12]):
            print(f"ok {entry['repository']}: unchanged at {recorded[:12]}")
            continue

        print(f"!! {entry['repository']}: {recorded[:12]} -> {head[:12]}")
        moved.append(
            {
                "repository": entry["repository"],
                "url": url,
                "purpose": entry.get("purpose", ""),
                "integration": entry.get("integration", "unknown"),
                "old_sha": recorded,
                "new_sha": head,
                "components": entry.get("components", []),
                "watch_for": entry.get("watch_for", []),
                "quiet": entry.get("integration") in QUIET,
            }
        )

    REPORT.write_text(json.dumps(moved, indent=2), encoding="utf-8")
    actionable = [m for m in moved if not m["quiet"]]

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with pathlib.Path(output).open("a", encoding="utf-8") as fh:
            fh.write(f"changed={'true' if actionable else 'false'}\n")
            fh.write(f"count={len(actionable)}\n")

    print(f"\n{len(actionable)} upstream(s) need review, {len(moved)} moved in total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
