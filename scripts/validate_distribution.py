#!/usr/bin/env python3
"""Validate plugin, marketplace, skill, and synchronized versions offline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from social_video import __version__
from social_video.project_validation import validate_marketplace, validate_plugin, validate_skill


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    results = [
        validate_plugin(root),
        validate_plugin(root / "plugins" / "social-video-agent"),
        validate_marketplace(root / ".agents" / "plugins" / "marketplace.json"),
        validate_skill(root / "skills" / "social-video-agent"),
    ]
    errors = [error for result in results for error in result.errors]
    for manifest in (
        root / ".codex-plugin" / "plugin.json",
        root / "plugins" / "social-video-agent" / ".codex-plugin" / "plugin.json",
    ):
        try:
            version = json.loads(manifest.read_text(encoding="utf-8"))["version"]
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            errors.append(f"{manifest}: cannot read version: {exc}")
        else:
            if version != __version__:
                errors.append(f"{manifest}: version {version} != package {__version__}")
    payload = {
        "ok": not errors,
        "checks": [{"name": result.name, "ok": result.ok} for result in results],
        "errors": errors,
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for item in payload["checks"]:
            print(f"{'OK' if item['ok'] else 'ERROR'}  {item['name']}")
        for error in errors:
            print(f"ERROR  {error}", file=sys.stderr)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
