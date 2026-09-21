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
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"


def targets() -> dict[str, Path]:
    """Where each host looks for user-level skills.

    On WSL the Windows home is included too, so a native Windows Codex agent
    can find the skill while the engine stays in Linux. Only the skill folder
    crosses: FFmpeg, Node, Python and Remotion are never duplicated on Windows,
    because in the hybrid mode every media operation is delegated back into WSL.
    """
    home = Path.home()
    found = {
        "Claude Code": home / ".claude" / "skills",
        "Agent Skills (Codex, and others)": home / ".agents" / "skills",
    }
    windows_home = windows_user_home()
    if windows_home is not None:
        found["Windows agent (native Codex)"] = windows_home / ".agents" / "skills"
    return found


def windows_user_home() -> Path | None:
    """The Windows user's home as seen from WSL, or None when not applicable.

    Resolved from Windows itself rather than assembled from a username: a
    redirected or domain profile is not under ``/mnt/c/Users/<name>``, and
    guessing would install the skill where nothing looks for it.
    """
    from social_video.paths import is_wsl  # local import: keeps --list cheap

    if not is_wsl():
        return None
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    if powershell is None:
        return None
    try:
        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", "$HOME"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
    except OSError:
        return None
    raw = (result.stdout or "").strip()
    if result.returncode != 0 or not raw:
        return None
    converter = shutil.which("wslpath")
    if converter is None:
        return None
    converted = subprocess.run(
        [converter, "-u", raw],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    )
    path = Path((converted.stdout or "").strip())
    return path if converted.returncode == 0 and path.is_dir() else None


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
        print("Restart your agent, or start a new session, so it picks up the skill list.")
        if windows_user_home() is not None:
            print(
                "Windows agent: only the skill folder was installed there. The engine stays "
                "in WSL and is reached through scripts/windows/social-video-agent.ps1; do "
                "not install FFmpeg, Node, Python or Remotion on the Windows side."
            )
        if not shutil.which("social-video-agent"):
            print(
                "Note: the `social-video-agent` command is not on PATH. Install the package "
                "with `uv sync` or `pip install -e .` and make sure its bin directory "
                "is on PATH, or the skill's commands will not run.",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(main())
