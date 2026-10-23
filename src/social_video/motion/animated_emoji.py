"""Animated stickers from Google's Noto Animated Emoji.

`@remotion/animated-emoji` draws them; the clips (VP8 with alpha, 512 px) are
not part of that package, so each one a plan uses is downloaded once from the
`remotion-dev/animated-emoji` repository at a pinned commit and cached.

The animations are licensed CC BY 4.0: a reel that shows one must credit
Google. The render manifest records the credit beside the sticker.
"""

from __future__ import annotations

import re
import urllib.request
from functools import cache
from pathlib import Path

from social_video.errors import SocialVideoError, ValidationError

#: The asset repository's commit; jsDelivr serves it immutably.
ASSET_COMMIT = "84bfdfbd5fb97729cb1973d9003017fe669f8c92"
ASSET_URL = f"https://cdn.jsdelivr.net/gh/remotion-dev/animated-emoji@{ASSET_COMMIT}/public"
#: Half size, 512 px: a sticker is at most a fifth of the frame's height.
SCALE = "0.5"
LICENCE = "CC BY 4.0"
CREDIT = "Animated emoji: Noto Animated Emoji by Google, CC BY 4.0"
_ENTRY = re.compile(r'name: "([^"]+)",[^}]*?codepoint: "([^"]+)"', re.DOTALL)


def _package_data() -> Path:
    from social_video.remotion_runtime import locate_runtime

    runtime = locate_runtime()
    if runtime is None:
        raise SocialVideoError("the Remotion compositor is not installed")
    return (
        runtime.root
        / "node_modules"
        / "@remotion"
        / "animated-emoji"
        / "dist"
        / "esm"
        / "index.mjs"
    )


@cache
def _names(source: Path) -> dict[str, str]:
    if not source.is_file():
        raise SocialVideoError(f"@remotion/animated-emoji is not installed ({source})")
    return {codepoint: name for name, codepoint in _ENTRY.findall(source.read_text("utf-8"))}


def codepoint(emoji: str) -> str:
    return "_".join(f"{ord(ch):x}" for ch in emoji)


def emoji_name(emoji: str, source: Path | None = None) -> str | None:
    """The animation's name for an emoji, with or without its variation selector."""
    names = _names(source or _package_data())
    key = codepoint(emoji)
    return names.get(key) or names.get(key.replace("_fe0f", "")) or names.get(f"{key}_fe0f")


def fetch_animation(name: str, directory: Path | None = None) -> Path:
    """The clip for ``name``, downloaded once into the cache."""
    from social_video.fsutil import atomic_write_bytes
    from social_video.paths import app_home

    target = (directory or app_home() / "animated-emoji" / ASSET_COMMIT) / f"{name}-{SCALE}x.webm"
    if target.is_file() and target.stat().st_size > 0:
        return target
    url = f"{ASSET_URL}/{name}-{SCALE}x.webm"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "social-video-agent"})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
    except OSError as exc:
        raise SocialVideoError(f"could not download the animated emoji {url}: {exc}") from exc
    # A WebM file starts with the EBML magic number.
    if not data.startswith(b"\x1a\x45\xdf\xa3"):
        raise SocialVideoError(f"{url} is not a WebM file")
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(target, data)
    return target


def require_name(emoji: str, source: Path | None = None) -> str:
    name = emoji_name(emoji, source)
    if name is None:
        raise ValidationError(
            f"{emoji} has no animated version in Noto Animated Emoji; "
            "set animated: false for this sticker or choose another emoji"
        )
    return name
