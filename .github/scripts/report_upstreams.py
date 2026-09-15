#!/usr/bin/env python3
"""Open or update one issue per moved upstream.

One issue per repository, reused across runs so the history of a given
upstream's movement stays in one place rather than accumulating duplicates.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
LABEL = "upstream"


def gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"gh {' '.join(args)} failed: {result.stderr.strip()}", file=sys.stderr)
    return result.stdout.strip()


def ensure_label() -> None:
    gh(
        "label",
        "create",
        LABEL,
        "--description",
        "Upstream project has moved and needs review",
        "--color",
        "0E8A16",
    )


def body_for(entry: dict) -> str:
    components = "\n".join(f"- `{c}`" for c in entry["components"]) or "- _(none recorded)_"
    watch = "\n".join(f"- {w}" for w in entry["watch_for"]) or "- _(nothing specific recorded)_"
    compare = f"{entry['url']}/compare/{entry['old_sha'][:12]}...{entry['new_sha'][:12]}"

    return f"""\
`{entry["repository"]}` has moved since we last reviewed it.

| | |
|---|---|
| **Purpose here** | {entry["purpose"]} |
| **Integration** | `{entry["integration"]}` |
| **Reviewed** | `{entry["old_sha"][:12]}` |
| **Upstream HEAD** | `{entry["new_sha"][:12]}` |
| **Compare** | {compare} |

### Our components derived from or depending on it
{components}

### What to look for
{watch}

### Review checklist

- [ ] Read the diff. Does it touch anything listed above?
- [ ] **Has upstream fixed something we carry a custom patch for?** If so, drop
      our patch rather than keeping the divergence.
- [ ] Does it change behaviour our tests assert?
- [ ] Is there a fix worth adapting?
- [ ] Is there a change of ours worth offering upstream in return?
- [ ] Update `reviewed_sha` and `reviewed_on` in `upstreams.yml`.

Nothing has been merged. This is a notification.

<sub>Opened automatically by `.github/workflows/upstream-monitor.yml`.</sub>
"""


def main() -> int:
    report = json.loads((ROOT / "upstream-report.json").read_text(encoding="utf-8"))
    actionable = [e for e in report if not e.get("quiet")]
    if not actionable:
        print("nothing actionable")
        return 0

    ensure_label()
    existing = gh(
        "issue",
        "list",
        "--label",
        LABEL,
        "--state",
        "open",
        "--json",
        "number,title",
        "--limit",
        "100",
    )
    try:
        open_issues = json.loads(existing) if existing else []
    except json.JSONDecodeError:
        open_issues = []

    for entry in actionable:
        title = f"upstream: {entry['repository']} has new commits"
        match = next((i for i in open_issues if i["title"] == title), None)
        body = body_for(entry)

        if match:
            gh("issue", "comment", str(match["number"]), "--body", body)
            print(f"commented on #{match['number']} for {entry['repository']}")
        else:
            gh("issue", "create", "--title", title, "--body", body, "--label", LABEL)
            print(f"opened an issue for {entry['repository']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
