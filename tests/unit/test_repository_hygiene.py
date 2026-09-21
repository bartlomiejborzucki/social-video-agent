"""Nothing private belongs in a public repository.

An agent working inside a user's project has their absolute paths, their
project names and their cloud-sync folders in context, and it is easy for one
of those to end up in a docstring, a fixture or a doc example. This scans what
git actually tracks, so the check is about what would be pushed rather than
about what happens to be on this disk.

Generic Windows placeholders (`C:\\Users\\User`, `Test User`, `bob`) are
deliberately allowed: the path-handling code exists because those paths are
hard, and its tests need to name them.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: Placeholder user names the Windows path tests and docs are allowed to use.
PLACEHOLDER_USERS = ("User", "Test User", "bob", "...")

#: Each pattern is something that is private by construction, with the reason
#: it must not be committed.
#: "OneDrive" itself is deliberately *not* forbidden: it is a Microsoft product
#: that the path layer has to handle and document, and naming it is necessary.
#: What is private is a particular person's folder, which the Windows-user rule
#: below catches by the user name -- `C:\Users\User\OneDrive\...` is a fine
#: example, `/mnt/c/Users/<a real name>/OneDrive/...` is not.
FORBIDDEN = (
    (
        re.compile(r"/home/[A-Za-z0-9._-]+/(?:projects|workspace|Documents|Desktop)/"),
        "an absolute path into somebody's home directory",
    ),
    (
        re.compile(r"\b[A-Za-z0-9._%+-]+@(?!example\.(?:com|org)\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "an email address; use the repository's git config instead",
    ),
)

#: Windows user paths are allowed only with a placeholder user name. The user
#: segment has to look like a directory name: prose that merely mentions
#: ``C:\\Users\\...`` is not a path.
WINDOWS_USER = re.compile(
    r"(?:/mnt/[a-z]/Users/|[A-Z]:\\{1,2}Users\\{1,2})(?P<user>[A-Za-z0-9 ._-]+|\.\.\.)"
)


def tracked_text_files() -> list[Path]:
    listing = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    files = []
    for name in listing.split("\0"):
        if not name:
            continue
        path = ROOT / name
        if not path.is_file() or path.suffix.casefold() in {".png", ".jpg", ".ttf", ".ico"}:
            continue
        files.append(path)
    return files


@pytest.mark.parametrize("path", tracked_text_files(), ids=lambda p: p.name)
def test_no_private_reference_is_committed(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        pytest.skip(f"{path.name} is not UTF-8 text")
    relative = path.relative_to(ROOT).as_posix()
    if relative == Path(__file__).relative_to(ROOT).as_posix():
        pytest.skip("this file names the patterns it forbids")
    for pattern, why in FORBIDDEN:
        found = pattern.search(text)
        assert found is None, f"{relative} contains {found.group(0)!r}: {why}"
    for match in WINDOWS_USER.finditer(text):
        user = match.group("user").strip()
        assert user in PLACEHOLDER_USERS, (
            f"{relative} names a real Windows user directory ({user!r}); "
            f"use one of {PLACEHOLDER_USERS} in examples and fixtures"
        )
