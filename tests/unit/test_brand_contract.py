from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from social_video.compatibility import validate_component_versions
from social_video.delivery import validate_delivery_manifest
from social_video.editorial.review import apply_editorial_qa_artifacts
from social_video.errors import ValidationError
from social_video.pipeline import resolve_caption_track
from social_video.project_config import compile_brand_contract, load_project_config
from social_video.qa.brand import check_brand
from social_video.schemas.base import save_artifact
from social_video.schemas.captions import CaptionCue, CaptionTrack
from social_video.schemas.delivery import DeliveryItem, DeliveryManifest
from social_video.schemas.editorial_qa import EditorialFix, EditorialQA, EditorialQAStatus
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.qa import RenderManifest
from social_video.workspace.layout import Workspace


def _brand_config(project: Path) -> Path:
    assets = project / "assets"
    assets.mkdir(parents=True)
    font = assets / "Lato.ttf"
    font.write_bytes(b"fixture-font")
    config = project / "social-video.yaml"
    config.write_text(
        """schema_version: 1
brand_name: Example
font: Lato
font_file: assets/Lato.ttf
brand_colors: [\"#28BCA5\"]
caption_style:
  font_weight: bold
  text_color: \"#FFFFFF\"
  background_color: \"#28BCA5\"
  background_style: rounded_box
  corner_radius: 45
  outline_color: \"#394463\"
  outline_or_shadow: outline
  max_lines: 2
  max_words_per_cue: 6
  position: lower_safe_zone
  bottom_margin_pct: 15
default_aspect_ratio: \"9:16\"
default_resolution: \"1080x1920\"
default_fps_policy: \"30\"
""",
        encoding="utf-8",
    )
    return config


def test_project_config_compiles_exact_executable_brand(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config = _brand_config(project)
    workspace = Workspace.at(project / "edit")

    contract = compile_brand_contract(config, workspace, project_root=project)

    style = contract.brand.captions
    assert style.font_family == "Lato"
    assert style.primary_colour == "#FFFFFF"
    assert style.background_colour == "#28BCA5"
    assert style.outline_colour == "#394463"
    assert style.corner_radius == 45
    assert style.margin_pct == 15
    assert style.max_lines == 2
    assert contract.output_fps == "30/1"
    assert (contract.output_width, contract.output_height) == (1080, 1920)
    assert workspace.brand_contract.is_file()


@pytest.mark.parametrize(
    "change,match",
    [
        ("#28BCA5", "#NOTHEX"),
        ("bottom_margin_pct: 15", "bottom_margin_pct: 70"),
        ("font_file: assets/Lato.ttf", "font_file: assets/missing.ttf"),
    ],
)
def test_config_validation_rejects_invalid_contract(
    tmp_path: Path, change: str, match: str
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    path = _brand_config(project)
    path.write_text(path.read_text(encoding="utf-8").replace(change, match), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_project_config(path)


def test_component_version_mismatch_detects_old_cli_and_new_skill(tmp_path: Path) -> None:
    (tmp_path / ".codex-plugin").mkdir()
    (tmp_path / "skills/social-video-agent").mkdir(parents=True)
    (tmp_path / ".codex-plugin/plugin.json").write_text(
        json.dumps({"version": "0.1.0"}), encoding="utf-8"
    )
    (tmp_path / "package.json").write_text(json.dumps({"version": "0.1.0"}), encoding="utf-8")
    (tmp_path / "skills/social-video-agent/SKILL.md").write_text(
        '---\nmetadata:\n  version: "0.2.0"\n---\n', encoding="utf-8"
    )
    with pytest.raises(ValidationError, match="different releases"):
        validate_component_versions(tmp_path, cli_version="0.1.0")


def test_multi_artifact_editorial_fixes_are_validated_atomically(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    contract = compile_brand_contract(
        _brand_config(project), Workspace.at(project / "edit"), project_root=project
    )
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=2)])
    captions = CaptionTrack(cues=[CaptionCue(index=1, start=0, end=1, text="Old")])
    review = EditorialQA(
        status=EditorialQAStatus.CHANGES_REQUESTED,
        fixes=[
            EditorialFix(artifact="edl", path="ranges[0].end", value=1.5, reason="trim"),
            EditorialFix(artifact="captions", path="cues[0].text", value="New", reason="copy"),
            EditorialFix(
                artifact="style",
                path="brand.captions.primary_colour",
                value="#EEEEEE",
                reason="approved deviation",
            ),
        ],
    )
    changed_edl, changed_captions, changed_style, changed = apply_editorial_qa_artifacts(
        edl, review, captions=captions, style=contract
    )
    assert changed
    assert changed_edl.ranges[0].end == 1.5
    assert changed_captions and changed_captions.cues[0].text == "New"
    assert changed_style and changed_style.brand.captions.primary_colour == "#EEEEEE"
    assert edl.ranges[0].end == 2
    assert captions.cues[0].text == "Old"

    invalid = EditorialQA(
        status=EditorialQAStatus.CHANGES_REQUESTED,
        fixes=[
            EditorialFix(path="ranges[0].end", value=1.5),
            EditorialFix(artifact="captions", path="cues[9].text", value="bad"),
        ],
    )
    with pytest.raises(ValidationError, match="does not exist"):
        apply_editorial_qa_artifacts(edl, invalid, captions=captions, style=contract)
    assert edl.ranges[0].end == 2


@pytest.mark.parametrize("extension", [".json", ".srt", ".ass"])
def test_caption_qa_resolves_structured_peer(tmp_path: Path, extension: str) -> None:
    track = CaptionTrack(cues=[CaptionCue(index=1, start=0, end=1, text="Caption")])
    json_path = save_artifact(track, tmp_path / "main.json")
    source = json_path if extension == ".json" else tmp_path / f"main{extension}"
    if extension == ".srt":
        source.write_text("1\n00:00:00,000 --> 00:00:01,000\nCaption\n", encoding="utf-8")
    elif extension == ".ass":
        source.write_text(
            "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Caption\n", encoding="utf-8"
        )
    loaded, problem = resolve_caption_track(source)
    assert problem is None
    assert loaded and loaded.cues[0].text == "Caption"


def test_caption_qa_reports_missing_or_inconsistent_json(tmp_path: Path) -> None:
    _, problem = resolve_caption_track(tmp_path / "main.ass")
    assert problem and "missing" in problem
    (tmp_path / "main.json").write_text('{"schema_version":1,"cues":"bad"}', encoding="utf-8")
    (tmp_path / "main.srt").write_text("bad", encoding="utf-8")
    with pytest.raises(ValidationError, match="CaptionTrack"):
        resolve_caption_track(tmp_path / "main.srt")

    save_artifact(
        CaptionTrack(cues=[CaptionCue(index=1, start=0, end=1, text="Caption")]),
        tmp_path / "main.json",
    )
    (tmp_path / "main.srt").write_text("no cues", encoding="utf-8")
    _, inconsistency = resolve_caption_track(tmp_path / "main.srt")
    assert inconsistency and "inconsistent" in inconsistency


def test_brand_qa_blocks_sans_or_missing_background(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    contract = compile_brand_contract(
        _brand_config(project), Workspace.at(project / "edit"), project_root=project
    )

    class Video:
        display_size = (1080, 1920)

    class Info:
        video = Video()

    monkeypatch.setattr("social_video.qa.brand.probe", lambda _: Info())
    render = RenderManifest(
        output="final.mp4",
        edl="main",
        rendered_at="2026-09-17T00:00:00Z",
        duration=1,
        width=1080,
        height=1920,
        frame_rate="30/1",
        brand_contract_sha256=contract.project_config_sha256,
        caption_style={
            **contract.brand.captions.model_dump(mode="json", exclude={"schema_version"}),
            "font_family": "Sans",
            "background_style": "none",
        },
        captions_burned=True,
        brand_safe_margins=contract.safe_margins,
    )
    report = check_brand(tmp_path / "final.mp4", contract, render)
    assert report.status == "failed"
    assert {check.name for check in report.errors} >= {
        "caption font",
        "caption background present",
    }


def test_delivery_manifest_verifies_edl_and_file_hashes(tmp_path: Path) -> None:
    edl = tmp_path / "edl.json"
    video = tmp_path / "final.mp4"
    edl.write_bytes(b"edl")
    video.write_bytes(b"video")

    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    manifest = DeliveryManifest(
        workspace=str(tmp_path),
        destination=str(tmp_path),
        edl_path=str(edl),
        edl_sha256_before=digest(edl),
        edl_sha256_after=digest(edl),
        items=[
            DeliveryItem(
                kind="video",
                path=str(video),
                size_bytes=video.stat().st_size,
                format="mp4",
                sha256=digest(video),
                qa_status="passed",
            )
        ],
    )
    validate_delivery_manifest(manifest)
    video.write_bytes(b"tampered")
    with pytest.raises(ValidationError, match="hash mismatch"):
        validate_delivery_manifest(manifest)
