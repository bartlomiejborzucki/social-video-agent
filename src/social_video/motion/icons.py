"""Icons over the head: a small flat picture of the thing just named.

When the speaker names a thing ("kąpiel", "bajka"), a small icon of it can
pop in over the head for a moment. The icons come from one set whose licence
allows commercial use, Tabler Icons (MIT), downloaded once into the cache from
the npm registry at a pinned version and checked against a pinned hash;
nothing is bundled. The render manifest records the set, its version, licence
and source, and the hash of every icon drawn, as `icons_applied`.

A project names which word shows which icon in a dictionary (`icon_dictionary`
in the config, e.g. `.social-video/icons.yaml`)::

    icons:
      kąpiel: bath
      bajka: book
    synonyms:
      kąpiel: [wanna, kąpieli]

`motion suggest` proposes an icon only for a word the dictionary lists, with
Polish endings handled as for b-roll ("kąpieli" finds `kąpiel`).
"""

from __future__ import annotations

import hashlib
import io
import re
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from social_video.errors import SocialVideoError, ValidationError

ICON_SET = "Tabler Icons"
ICON_VERSION = "3.48.0"
ICON_LICENCE = "MIT"
ICON_SOURCE = "https://github.com/tabler/tabler-icons"
TARBALL = f"https://registry.npmjs.org/@tabler/icons/-/icons-{ICON_VERSION}.tgz"
TARBALL_SHA256 = "28447dcf6f0bb2b8d92c59a1b3d30900a180de2e97d7db4d267e6320dc68f449"
#: Only the outline icons are used: one stroke weight, drawn in one colour.
OUTLINE = "package/icons/outline/"
NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VOWELS = frozenset("aeiouyąęó")


def icon_library(directory: Path | None = None) -> Path:
    """The outline icons, downloaded once and checked against the pinned hash."""
    import urllib.request

    from social_video.fsutil import atomic_write_bytes
    from social_video.paths import app_home

    target = directory or app_home() / "icons" / f"tabler-{ICON_VERSION}"
    stamp = target / ".sha256"
    if stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == TARBALL_SHA256:
        return target
    try:
        request = urllib.request.Request(TARBALL, headers={"User-Agent": "social-video-agent"})
        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read()
    except OSError as exc:
        raise SocialVideoError(f"could not download {ICON_SET} from {TARBALL}: {exc}") from exc
    if hashlib.sha256(data).hexdigest() != TARBALL_SHA256:
        raise SocialVideoError(f"{TARBALL} does not match its pinned hash")
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            # Only plain files with a known shape of name: nothing in the
            # archive decides where a file lands.
            if not member.isfile():
                continue
            if member.name == "package/LICENSE":
                name = "LICENSE"
            elif member.name.startswith(OUTLINE) and member.name.endswith(".svg"):
                name = member.name[len(OUTLINE) :]
                if not NAME.match(name[:-4]):
                    continue
            else:
                continue
            extracted = archive.extractfile(member)
            if extracted is not None:
                atomic_write_bytes(target / name, extracted.read())
    atomic_write_bytes(stamp, TARBALL_SHA256.encode())
    return target


def icon_file(name: str, directory: Path | None = None) -> Path:
    """The SVG for ``name``; an icon the set does not have is refused by name."""
    if not NAME.match(name):
        raise ValidationError(f"icon {name!r} is not an icon name (lowercase, e.g. 'bath')")
    path = icon_library(directory) / f"{name}.svg"
    if not path.is_file():
        raise ValidationError(
            f"{ICON_SET} {ICON_VERSION} has no icon {name!r}; see https://tabler.io/icons"
        )
    return path


def icon_evidence(name: str, path: Path, at: float) -> dict:
    return {
        "at": at,
        "icon": name,
        "set": ICON_SET,
        "version": ICON_VERSION,
        "licence": ICON_LICENCE,
        "source": ICON_SOURCE,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


@dataclass(frozen=True)
class IconDictionary:
    """Which word shows which icon, and the other words that say the same."""

    icons: dict[str, str] = field(default_factory=dict)
    synonyms: dict[str, list[str]] = field(default_factory=dict)

    def lookup(self, spoken: str) -> tuple[str, str] | None:
        """``(entry, icon)`` for a spoken word the dictionary covers, else None."""
        from social_video.captions.emphasis import normalise
        from social_video.motion.broll import _stem_match

        key = normalise(spoken)
        if len(key) < 3:
            return None
        for entry, icon in self.icons.items():
            forms = {normalise(entry), *(normalise(s) for s in self.synonyms.get(entry, []))}
            if key in forms or _stem_match(key, {f for f in forms if len(f) >= 3}):
                return entry, icon
            # A noun ending in a vowel changes it as it declines: "bajka",
            # "bajkę", "bajki"; "wanna", "wannie".
            stems = {f[:-1] for f in forms if len(f) >= 5 and f[-1] in VOWELS}
            if any(key.startswith(s) and len(key) - len(s) <= 3 for s in stems):
                return entry, icon
        return None


def load_icon_dictionary(path: Path) -> IconDictionary:
    if not path.is_file():
        raise ValidationError(f"no icon dictionary at {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not isinstance(data.get("icons", {}), dict):
        raise ValidationError(f"{path}: expected `icons:` mapping a word to an icon name")
    icons = {str(word).casefold(): str(name) for word, name in (data.get("icons") or {}).items()}
    for word, name in icons.items():
        if not NAME.match(name):
            raise ValidationError(f"{path}: {word!r} names {name!r}, not an icon name")
    synonyms = {
        str(word).casefold(): [str(v) for v in (values or [])]
        for word, values in (data.get("synonyms") or {}).items()
    }
    if unknown := set(synonyms) - set(icons):
        names = ", ".join(sorted(unknown))
        raise ValidationError(f"{path}: synonyms for words with no icon: {names}")
    return IconDictionary(icons=icons, synonyms=synonyms)
