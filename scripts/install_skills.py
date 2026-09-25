#!/usr/bin/env python3
"""Install the canonical skills for whichever agents are present.

There is one source of truth: ``skills/``. Agent Skills is an open standard, so
the same folder is understood by Claude Code, Codex, and other compatible
hosts. For a Linux or macOS host this script links rather than copies, so
editing the repo updates the installed skill immediately.

A Windows destination is copied instead. A symlink made from WSL onto the
Windows drive is a Linux link to /home/...: native Windows sees a reparse point
it cannot follow, and a native Codex agent then cannot read SKILL.md. Rerun
this script after updating the repository to refresh the copy.

Usage:
    python scripts/install_skills.py            # install for every host found
    python scripts/install_skills.py --list     # show what would happen
    python scripts/install_skills.py --uninstall
    python scripts/install_skills.py --dest DIR [--copy]   # one explicit directory
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

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


def needs_copy(destination: Path) -> bool:
    """Whether a destination must get real files rather than a symlink.

    True on the Windows side: a Windows drive seen from WSL (``/mnt/c/...``),
    or any destination when this script runs on Windows itself.
    """
    from social_video.paths import is_wsl_mount_path

    return sys.platform == "win32" or is_wsl_mount_path(destination)


def _remove_previous(destination: Path) -> None:
    """Remove an earlier install of a skill, and nothing else.

    A symlink (including one WSL made that Windows cannot follow) is unlinked.
    A directory is removed only if it is a skill -- it has a SKILL.md -- so a
    mistyped destination can never delete someone's folder.
    """
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        destination.unlink()
        return
    if destination.is_dir():
        if not (destination / "SKILL.md").is_file():
            raise SystemExit(
                f"refusing to replace {destination}: it is a directory but not an installed "
                "skill (no SKILL.md). Move it away and rerun."
            )
        shutil.rmtree(destination)


def sync_copy(source: Path, destination: Path) -> str:
    """Install real files, atomically, replacing any earlier install.

    The copy is made beside the destination and renamed into place, so an
    interrupted run never leaves a half-copied skill. Links inside the source
    are followed, so every file on the Windows side is a regular file.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(f".{destination.name}.{uuid4().hex}.partial")
    try:
        shutil.copytree(source, staging, symlinks=False)
        _remove_previous(destination)
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return "copied (Windows cannot follow a WSL symlink)"


def install(source: Path, destination: Path, *, copy: bool = False) -> str:
    if copy or needs_copy(destination):
        return sync_copy(source, destination)
    return link(source, destination)


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
    parser.add_argument(
        "--dest",
        type=Path,
        help="Install into this skills directory only, instead of every host found.",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy real files instead of linking (always done for a Windows destination).",
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
    destinations = {"explicit destination": args.dest} if args.dest else targets()
    for host, directory in destinations.items():
        # Only install where the host actually lives, unless asked otherwise.
        exists = directory.parent.is_dir() or args.dest is not None
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
                    _remove_previous(destination)
                    print(f"{host}: removed {destination}")
                continue
            status = install(skill, destination, copy=args.copy)
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
