#!/usr/bin/env python3
"""Install the canonical skills for whichever agents are present.

There is one source of truth: ``skills/``. Agent Skills is an open standard, so
the same folder is understood by Claude Code, Codex, and other compatible
hosts. This script links rather than copies, so editing the repo updates the
installed skill immediately.

Usage:
    python scripts/install_skills.py            # install for every host found
    python scripts/install_skills.py --list     # show what would happen
    python scripts/install_skills.py --uninstall
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"


def targets() -> dict[str, Path]:
    """Where each host looks for user-level skills."""
    home = Path.home()
    return {
        "Claude Code": home / ".claude" / "skills",
        "Agent Skills (Codex, and others)": home / ".agents" / "skills",
    }


def link(source: Path, destination: Path) -> str:
    """Symlink, falling back to a copy where symlinks are unavailable.

    Windows needs either developer mode or elevation to create symlinks, which
    is a documented upstream install failure elsewhere; copying is a worse but
    working answer rather than an error.
    """
    if destination.is_symlink() or destination.exists():
        if destination.is_symlink() and destination.resolve() == source.resolve():
            return "already linked"
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        else:
            destination.unlink()

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        destination.symlink_to(source, target_is_directory=True)
        return "linked"
    except (OSError, NotImplementedError):
        shutil.copytree(source, destination)
        return "copied (symlinks unavailable)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="Show targets and exit.")
    parser.add_argument("--uninstall", action="store_true", help="Remove installed skills.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Install for every known host, even ones with no config directory yet.",
    )
    args = parser.parse_args()

    skills = sorted(p for p in SKILLS.iterdir() if (p / "SKILL.md").is_file())
    if not skills:
        print(f"no skills found in {SKILLS}", file=sys.stderr)
        return 1

    print(f"skills in {SKILLS}:")
    for skill in skills:
        print(f"  {skill.name}")
    print()

    installed_any = False
    for host, directory in targets().items():
        # Only install where the host actually lives, unless asked otherwise.
        exists = directory.parent.is_dir()
        if not exists and not args.all and not args.uninstall:
            print(f"{host}: not found ({directory.parent} does not exist) - skipped")
            continue
        if args.list:
            print(f"{host}: would install into {directory}")
            continue

        for skill in skills:
            destination = directory / skill.name
            if args.uninstall:
                if destination.is_symlink() or destination.exists():
                    if destination.is_dir() and not destination.is_symlink():
                        shutil.rmtree(destination)
                    else:
                        destination.unlink()
                    print(f"{host}: removed {destination}")
                continue
            status = link(skill, destination)
            print(f"{host}: {skill.name} -> {destination} ({status})")
            installed_any = True

    if installed_any:
        print()
        print("Restart your agent so it picks up the new skill.")
        if not shutil.which("social-video"):
            print(
                "Note: the `social-video` command is not on PATH. Install the package "
                "with `uv sync` or `pip install -e .` and make sure its bin directory "
                "is on PATH, or the skill's commands will not run.",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(main())
