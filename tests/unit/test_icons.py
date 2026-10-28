"""Icons over the head: a licensed set fetched once, a project dictionary, brand limits."""

from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from social_video.errors import SocialVideoError, ValidationError
from social_video.motion import icons
from social_video.motion.icons import (
    icon_evidence,
    icon_file,
    icon_library,
    icon_problems,
    load_icon_dictionary,
)
from social_video.project_config import compile_brand_contract
from social_video.qa.motion import check_motion
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import MotionElement, MotionPlan
from social_video.workspace.layout import Workspace

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M4 12h16"/></svg>'


def _tarball() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in (
            ("package/LICENSE", b"MIT License"),
            ("package/icons/outline/bath.svg", SVG),
            ("package/icons/filled/bath.svg", SVG),
            ("package/icons/outline/../../escape.svg", SVG),
            ("package/README.md", b"readme"),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


@pytest.fixture
def fake_registry(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    data = _tarball()
    fetched: list[str] = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(request, timeout):
        fetched.append(request.full_url)
        return Response(data)

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr(icons, "TARBALL_SHA256", hashlib.sha256(data).hexdigest())
    return fetched


def test_the_set_is_fetched_once_and_only_its_outline_icons_are_kept(
    tmp_path: Path, fake_registry: list[str]
) -> None:
    library = icon_library(tmp_path / "icons")
    assert sorted(p.name for p in library.iterdir()) == [".sha256", "LICENSE", "bath.svg"]
    assert not (tmp_path / "escape.svg").exists()
    assert icon_file("bath", tmp_path / "icons").read_bytes() == SVG
    assert len(fake_registry) == 1 and fake_registry[0].endswith("icons-3.48.0.tgz")
    with pytest.raises(ValidationError, match="has no icon 'moon'"):
        icon_file("moon", tmp_path / "icons")
    with pytest.raises(ValidationError, match="not an icon name"):
        icon_file("../bath", tmp_path / "icons")
    evidence = icon_evidence("bath", library / "bath.svg", 2.5)
    assert evidence["set"] == "Tabler Icons" and evidence["licence"] == "MIT"
    assert evidence["sha256"] == hashlib.sha256(SVG).hexdigest()


def test_a_download_that_does_not_match_its_hash_is_refused(
    tmp_path: Path, fake_registry: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(icons, "TARBALL_SHA256", "0" * 64)
    with pytest.raises(SocialVideoError, match="pinned hash"):
        icon_library(tmp_path / "icons")


def test_the_dictionary_maps_words_and_their_forms_to_icons(tmp_path: Path) -> None:
    path = tmp_path / "icons.yaml"
    path.write_text(
        "icons:\n  kąpiel: bath\n  bajka: book\nsynonyms:\n  kąpiel: [wanna]\n", encoding="utf-8"
    )
    dictionary = load_icon_dictionary(path)
    assert dictionary.lookup("Kąpieli,") == ("kąpiel", "bath")
    assert dictionary.lookup("Wanna!") == ("kąpiel", "bath")
    assert dictionary.lookup("wannie") == ("kąpiel", "bath")
    assert dictionary.lookup("bajkę") == ("bajka", "book")
    assert dictionary.lookup("sen") is None
    path.write_text("icons:\n  kąpiel: Bath Tub\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="not an icon name"):
        load_icon_dictionary(path)
    path.write_text("icons:\n  kąpiel: bath\nsynonyms:\n  sen: [spanie]\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="no icon: sen"):
        load_icon_dictionary(path)


def test_the_project_names_its_dictionary_in_the_config(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / ".social-video").mkdir(parents=True)
    (project / "Lato.ttf").write_bytes(b"fixture-font")
    (project / ".social-video" / "icons.yaml").write_text("icons: {}\n", encoding="utf-8")
    config = project / "social-video.yaml"
    config.write_text(
        "schema_version: 1\nfont_file: Lato.ttf\nicon_dictionary: .social-video/icons.yaml\n",
        encoding="utf-8",
    )
    contract = compile_brand_contract(config, Workspace.at(project / "edit"), project_root=project)
    assert contract.brand.icon_dictionary == str(project / ".social-video" / "icons.yaml")
    config.write_text(
        "schema_version: 1\nfont_file: Lato.ttf\nicon_dictionary: missing.yaml\n", encoding="utf-8"
    )
    with pytest.raises(ValidationError, match="does not exist"):
        compile_brand_contract(config, None, project_root=project)


def _icon(**fields) -> MotionElement:
    values = {"start": 2.0, "end": 3.0, "icon": "bath", "reason": "The bath, as it is named."}
    values.update(fields)
    return MotionElement(type="icon", **values)


def test_an_icon_pops_in_over_the_head_for_a_moment() -> None:
    icon = _icon()
    assert (icon.x_pct, icon.y_pct, icon.size_pct) == (0.5, 0.17, 9.0)
    assert icon.box[3] < 0.25  # wholly in the top zone, over the head
    sticker = MotionElement(type="sticker", start=2, end=3, emoji="x", reason="r")
    assert (sticker.x_pct, sticker.y_pct) == (0.78, 0.3)
    with pytest.raises(PydanticValidationError, match=r"0\.6-1\.2 s"):
        _icon(end=4.0)
    with pytest.raises(PydanticValidationError, match="names one icon"):
        _icon(icon=None)
    with pytest.raises(PydanticValidationError, match="pops in"):
        _icon(animation="shake")
    with pytest.raises(PydanticValidationError, match="opening frame"):
        _icon(start=0.0, end=1.0)
    with pytest.raises(PydanticValidationError, match="only used by an icon"):
        MotionElement(type="callout", start=1, end=3, text="?", icon="bath", reason="r")
    with pytest.raises(PydanticValidationError, match="remove icon"):
        MotionPlan(rationale="r", sensitive_topic=True, elements=[_icon()])


def test_icons_have_their_own_limit_per_energy() -> None:
    plan = MotionPlan(
        rationale="r", elements=[_icon(start=1.0 + 2 * n, end=2.0 + 2 * n) for n in range(3)]
    )
    assert icon_problems(plan, energy="bold") == []
    assert icon_problems(plan, energy="lively") == [
        "3 icon(s); motion_energy lively allows 2 per reel"
    ]
    assert icon_problems(plan, energy="calm") == ["3 icon(s); motion_energy calm allows 0 per reel"]


def test_motion_qa_measures_an_icon_against_faces_and_captions() -> None:
    from social_video.schemas.brand import BrandProfile, CaptionStyle
    from social_video.schemas.config import BrandContract

    contract = BrandContract(
        project_config_path="c.yaml", project_config_sha256="c" * 64, project_root="/p",
        brand=BrandProfile(captions=CaptionStyle(margin_pct=22, font_size_pct=3.6),
                           motion_energy="lively"),
        output_width=1080, output_height=1920, output_fps="30/1",
    )  # fmt: skip
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=8)])
    track = CaptionTrack(
        cues=[CaptionCue(index=1, start=0, end=8, text="kąpiel",
                         words=[CaptionWord(text="kąpiel", start=2.0, end=2.5)])]
    )  # fmt: skip
    plan = MotionPlan(rationale="r", elements=[_icon(), _icon(start=5.0, end=6.0, y_pct=0.72)])

    def face(_t: float) -> list[tuple[float, float, float, float]]:
        return [(0.3, 0.24, 0.7, 0.5)]  # the head, below the icon's default place

    checks = {
        c.name: c for c in check_motion(edl, plan, contract, captions=track, faces=face).checks
    }
    assert checks["icon at 2.00s clear of faces"].passed
    assert checks["icon at 2.00s clear of captions"].passed
    assert checks["icon at 2.00s within the energy's limit"].passed
    assert not checks["icon at 5.00s clear of captions"].passed
