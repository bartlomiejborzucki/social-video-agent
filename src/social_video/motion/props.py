"""Props: large pictures from the project's own library, shown on their word.

A prop is the thing being talked about held up to the camera without holding
it: a book cover, a filled-in form, a screenshot of a page, a clock face. It
comes from the project, never from the network, and only with its rights
written down. The library is a folder of PNG/WebP files beside a
``props.yaml``::

    props:
      - id: okladka
        file: okladka.png
        description: Okładka poradnika
        keywords: [poradnik, książka]
        rights: własne zdjęcie, zgoda autorki
        source: sesja produktowa

A prop with a child's face, or without rights, is refused. ``motion suggest``
proposes a prop where a word of its ``keywords`` is said.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator

from social_video.errors import ValidationError
from social_video.fsutil import sha256_file
from social_video.schemas.base import Artifact
from social_video.schemas.motion import ElementPosition, MotionElement, MotionElementType

#: Where a project keeps its props, relative to the project root.
DEFAULT_LIBRARY = "assets/props"
PICTURE = {".png", ".webp"}
#: A prop never takes more of the frame's height than this.
PROP_MAX_HEIGHT = 0.45
#: Clear space below the top safe margin, in 1920-high pixels.
TOP_GAP = 40


class PropInfo(Artifact):
    """One prop as ``props.yaml`` describes it."""

    id: str = Field(pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
    file: str
    description: str = ""
    keywords: list[str] = Field(default_factory=list)
    #: Whose picture it is and the consent to show it, in the owner's words.
    rights: str = ""
    source: str = ""
    child_face_visible: bool = False

    @field_validator("file")
    @classmethod
    def _picture(cls, value: str) -> str:
        if Path(value).suffix.casefold() not in PICTURE:
            raise ValueError(f"a prop is a .png or .webp picture, not {value!r}")
        if Path(value).is_absolute() or ".." in Path(value).parts:
            raise ValueError(f"a prop's file is inside the library folder: {value!r}")
        return value


class PropLibrary(Artifact):
    directory: str
    props: list[PropInfo] = Field(default_factory=list)

    def by_id(self, prop_id: str) -> PropInfo:
        for prop in self.props:
            if prop.id == prop_id:
                return prop
        known = ", ".join(p.id for p in self.props) or "<none>"
        raise KeyError(f"prop {prop_id!r} is not in the library; known: {known}")

    def path(self, prop: PropInfo) -> Path:
        return Path(self.directory) / prop.file


def library_dir(project_root: Path, configured: str | None = None) -> Path:
    """The prop folder, which must lie inside the project root."""
    root = project_root.resolve()
    directory = (root / (configured or DEFAULT_LIBRARY)).resolve()
    try:
        directory.relative_to(root)
    except ValueError:
        raise ValidationError(f"the prop library escapes the project root: {directory}") from None
    return directory


def load_props(directory: Path) -> PropLibrary:
    """The library's ``props.yaml``; an empty library when there is none."""
    import yaml

    meta = directory / "props.yaml"
    if not meta.is_file():
        return PropLibrary(directory=str(directory))
    data = yaml.safe_load(meta.read_text(encoding="utf-8")) or {}
    try:
        library = PropLibrary(
            directory=str(directory),
            props=[PropInfo.model_validate(entry) for entry in data.get("props", [])],
        )
    except Exception as exc:
        raise ValidationError(f"invalid {meta}: {exc}") from exc
    seen: set[str] = set()
    for prop in library.props:
        if prop.id in seen:
            raise ValidationError(f"{meta}: prop id {prop.id!r} is listed twice")
        seen.add(prop.id)
    return library


def plan_props(plan, directory: Path) -> tuple[dict[str, Path], list[dict]]:
    """The files of every prop the plan shows, checked, and their evidence.

    Refuses a prop that is not in the library, has no rights, shows a
    child's face, or whose file is missing.
    """
    used = sorted({e.prop for e in plan.elements if e.type is MotionElementType.PROP and e.prop})
    if not used:
        return {}, []
    library = load_props(directory)
    files: dict[str, Path] = {}
    evidence: list[dict] = []
    for prop_id in used:
        try:
            prop = library.by_id(prop_id)
        except KeyError as exc:
            raise ValidationError(str(exc.args[0])) from None
        if not prop.rights.strip():
            raise ValidationError(f"prop {prop_id!r} has no rights in props.yaml; it is not shown")
        if prop.child_face_visible:
            raise ValidationError(f"prop {prop_id!r} shows a child's face; it is never shown")
        path = library.path(prop).resolve()
        try:
            path.relative_to(directory.resolve())
        except ValueError:
            raise ValidationError(f"prop {prop_id!r} points outside its library") from None
        if not path.is_file():
            raise ValidationError(f"prop {prop_id!r}: {path} does not exist")
        files[prop_id] = path
        evidence.append(
            {"id": prop_id, "file": prop.file, "sha256": sha256_file(path), "rights": prop.rights}
        )
    return files, evidence


def prop_aspect(picture: Path) -> float:
    from PIL import Image

    with Image.open(picture) as image:
        width, height = image.size
    return width / max(height, 1)


def prop_box(
    element: MotionElement,
    picture: Path,
    *,
    width: int = 1080,
    height: int = 1920,
    margins: dict[str, float] | None = None,
) -> tuple[float, float, float, float]:
    """The prop's (left, top, right, bottom), as fractions of the frame."""
    margins = margins or {}
    aspect = prop_aspect(picture)
    card_w = element.size_pct / 100.0
    card_h = card_w * width / aspect / height
    if card_h > PROP_MAX_HEIGHT:
        card_w *= PROP_MAX_HEIGHT / card_h
        card_h = PROP_MAX_HEIGHT
    left = (1.0 - card_w) / 2
    if element.placement is ElementPosition.TOP:
        top = margins.get("top", 6.0) / 100.0 + TOP_GAP / 1920
    else:
        top = (1.0 - card_h) / 2 - 0.06
    return left, top, left + card_w, top + card_h
