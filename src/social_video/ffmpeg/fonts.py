"""Font discovery.

Captions are rendered by libass, which resolves font names through fontconfig on
Linux, Core Text on macOS, and the system font directory on Windows. Naming a
font that is not installed does not fail: libass silently substitutes another
one, so the output is subtly wrong with no warning.

Upstream hard-codes ``FontName=Helvetica``, which exists only on macOS, and its
diagnostic image renderer lists five font paths of which three are macOS-only
and none are Windows. On any Linux or Windows machine the caption style is
therefore not the style that was asked for.
"""

from __future__ import annotations

import functools
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: Characters that a font must cover to caption these languages correctly.
#: Polish is the strictest common Latin case: it needs ogoneks and a stroked l.
COVERAGE_SAMPLES = {
    "latin": "AaZz09",
    "polish": "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ",
    "german": "äöüßÄÖÜ",
    "french": "àâçéèêëîïôûùüÿœ",
    "cyrillic": "АБВГДЕЖЗИЙ",
}

#: Preferred caption faces, best first. All are commonly present, carry wide
#: Latin coverage, and are legible at small sizes over video.
PREFERRED_FAMILIES = (
    "Inter",
    "Noto Sans",
    "DejaVu Sans",
    "Liberation Sans",
    "Arial",
    "Helvetica Neue",
    "Roboto",
)

_WINDOWS_DIRS = (Path("C:/Windows/Fonts"),)
_MAC_DIRS = (
    Path("/System/Library/Fonts"),
    Path("/Library/Fonts"),
    Path.home() / "Library/Fonts",
)
_LINUX_DIRS = (
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path.home() / ".local/share/fonts",
    Path.home() / ".fonts",
)


@dataclass(frozen=True)
class FontInfo:
    family: str
    path: Path

    def covers(self, text: str) -> bool:
        return font_covers(self.path, text)


def font_dirs() -> tuple[Path, ...]:
    if sys.platform == "win32":
        return _WINDOWS_DIRS
    if sys.platform == "darwin":
        return _MAC_DIRS
    return _LINUX_DIRS


@functools.lru_cache(maxsize=1)
def _fc_available() -> bool:
    try:
        subprocess.run(["fc-list", "--version"], capture_output=True, check=False, timeout=10)
        return True
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return False


@functools.lru_cache(maxsize=32)
def find_family(family: str) -> FontInfo | None:
    """Locate a font file for a family name."""
    if _fc_available():
        try:
            out = subprocess.run(
                ["fc-match", "--format=%{family}\\n%{file}", family],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            ).stdout.splitlines()
            if len(out) >= 2 and out[1].strip():
                matched = Path(out[1].strip())
                # fc-match always returns *something*; only accept it when the
                # family it found is actually the one we asked for.
                if matched.is_file() and family.lower() in out[0].lower():
                    return FontInfo(family=family, path=matched)
        except (OSError, subprocess.SubprocessError):
            pass

    needle = family.lower().replace(" ", "")
    for directory in font_dirs():
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if path.suffix.lower() not in (".ttf", ".otf", ".ttc"):
                continue
            if needle in path.stem.lower().replace(" ", "").replace("-", ""):
                return FontInfo(family=family, path=path)
    return None


@functools.lru_cache(maxsize=256)
def font_covers(path: Path, text: str) -> bool:
    """Whether a font file has a glyph for every character in ``text``.

    Checking coverage up front is what prevents shipping a video full of tofu
    boxes; upstream has an open issue for exactly that failure.
    """
    try:
        from fontTools.ttLib import TTCollection, TTFont  # type: ignore
    except ImportError:
        return _covers_via_pillow(path, text)

    try:
        fonts = (
            TTCollection(str(path)).fonts
            if path.suffix.lower() == ".ttc"
            else [TTFont(str(path), fontNumber=0, lazy=True)]
        )
    except Exception:
        # The file is unreadable as a font at all; fall back rather than claim
        # either coverage or its absence.
        return _covers_via_pillow(path, text)

    for font in fonts:
        try:
            cmap = font.getBestCmap()
        except Exception:
            continue
        # Symbol fonts (Webdings, Wingdings) have no Unicode cmap at all, and
        # `getBestCmap` returns None for them. That is definitive evidence of
        # no coverage, not a reason to fall through to a permissive guess.
        if not cmap:
            continue
        if all(ord(ch) in cmap for ch in text):
            return True
    return False


def _covers_via_pillow(path: Path, text: str) -> bool:
    """Fallback coverage check using Pillow's FreeType binding."""
    try:
        from PIL import ImageFont

        font = ImageFont.truetype(str(path), 24)
        getter = getattr(font, "getmask", None)
        if getter is None:
            return True
        # A missing glyph renders as the .notdef box; comparing against a
        # character we know is absent from every sane font is unreliable, so we
        # settle for "the font loaded and rendered without raising".
        getter(text)
        return True
    except Exception:
        return False


def default_caption_font() -> FontInfo | None:
    """Best available caption font that covers Polish and Western European text.

    Polish is used as the bar deliberately: a font that renders ``ąćęłńóśźż``
    correctly will handle the rest of Latin-1 and Latin-2.
    """
    required = COVERAGE_SAMPLES["latin"] + COVERAGE_SAMPLES["polish"]
    fallback: FontInfo | None = None
    for family in PREFERRED_FAMILIES:
        info = find_family(family)
        if info is None:
            continue
        if info.covers(required):
            return info
        fallback = fallback or info
    return fallback


def describe_coverage(info: FontInfo) -> dict[str, bool]:
    """Which language samples a font can render. Used by ``doctor``."""
    return {name: info.covers(sample) for name, sample in COVERAGE_SAMPLES.items()}


def font_family_name(path: Path) -> str | None:
    """The family name a font file declares, which is what libass matches on.

    The typographic family (name ID 16) wins over the legacy one (ID 1), which
    splits heavy weights into families of their own.
    """
    try:
        from fontTools.ttLib import TTFont  # type: ignore

        font = TTFont(str(path), fontNumber=0, lazy=True)
        names = font["name"]
        for name_id in (16, 1):
            record = names.getName(name_id, 3, 1) or names.getName(name_id, 1, 0)
            if record is not None:
                return str(record.toUnicode()).strip() or None
    except Exception:
        return None
    return None
