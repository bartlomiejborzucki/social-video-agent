"""Properties of the Windows/WSL path recognisers, checked on every host.

The example-based tests in ``test_path_boundary.py`` pin known cases. These
generate names the examples never thought of -- Polish letters, brackets,
quotes, spaces in odd places -- because every recent path regression came from
a name nobody had written a test for. Only pure string logic is exercised here,
so the properties hold identically on Linux, macOS and Windows.
"""

from __future__ import annotations

import string
from unittest import mock

from hypothesis import given, settings
from hypothesis import strategies as st

from social_video import paths

drive = st.sampled_from(string.ascii_letters)
separator = st.sampled_from(["\\", "/"])
#: Filename characters a user can really type, backslash and slash excluded.
segment = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs", "Cc"),
        blacklist_characters="\\/",
    ),
    min_size=1,
    max_size=12,
)
segments = st.lists(segment, min_size=1, max_size=5)


@given(drive, separator, st.text(max_size=40))
def test_any_drive_letter_path_is_recognised(letter: str, sep: str, rest: str) -> None:
    assert paths.is_windows_drive_path(f"{letter}:{sep}{rest}")


@given(st.text(max_size=40))
def test_a_rootless_or_posix_path_is_never_a_drive_path(rest: str) -> None:
    assert not paths.is_windows_drive_path("/" + rest)
    assert not paths.is_windows_drive_path("./" + rest)


@given(st.sampled_from(string.ascii_lowercase), segments)
def test_every_wsl_mount_is_recognised(letter: str, parts: list[str]) -> None:
    assert paths.is_wsl_mount_path(f"/mnt/{letter}")
    assert paths.is_wsl_mount_path(f"/mnt/{letter}/" + "/".join(parts))


@given(st.text(alphabet=string.ascii_lowercase, min_size=2, max_size=6), segments)
def test_a_longer_mount_name_is_not_a_drive(name: str, parts: list[str]) -> None:
    assert not paths.is_wsl_mount_path(f"/mnt/{name}/" + "/".join(parts))


@given(st.sampled_from(['"', "'"]), st.text(max_size=40))
def test_one_pair_of_quotes_is_removed_and_nothing_else(quote: str, inner: str) -> None:
    assert paths._strip_quotes(f"  {quote}{inner}{quote} ") == inner


@settings(max_examples=200)
@given(
    st.sampled_from(["wsl$", "wsl.localhost", "WSL$"]),
    st.text(alphabet=string.ascii_letters + string.digits + "-._", min_size=1, max_size=12),
    segments,
)
def test_a_unc_path_translates_to_the_same_segments(
    host: str, distribution: str, parts: list[str]
) -> None:
    raw = f"\\\\{host}\\{distribution}\\" + "\\".join(parts)
    assert paths.is_wsl_unc_path(raw)

    # Outside WSL there is no current distribution to disagree with.
    with mock.patch.object(paths, "current_distribution", return_value=None):
        translated = paths._from_unc(raw)

    assert translated == "/" + "/".join(parts).lstrip("/")
    assert not paths.is_wsl_unc_path(translated)
    assert not paths.is_windows_drive_path(translated)
