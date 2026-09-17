from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from social_video.captions.ass import write_ass
from social_video.captions.srt import write_srt
from social_video.delivery import deliver_workspace
from social_video.ffmpeg.probe import probe
from social_video.pipeline import stage_qa, stage_render
from social_video.project_config import apply_contract_to_edl
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.captions import CaptionCue, CaptionTrack
from social_video.schemas.config import BrandContract
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import MotionPlan
from social_video.schemas.qa import QAReport, RenderManifest
from social_video.schemas.workflow import RemotionLicenseAttestation, Renderer
from social_video.sources import build_manifest
from social_video.workflow import create_workflow
from social_video.workspace.layout import Workspace
from tests.conftest import make_video, requires_ffmpeg


@pytest.mark.integration
@pytest.mark.slow
@requires_ffmpeg
def test_executable_brand_contract_and_stage_5_delivery(tmp_path: Path) -> None:
    if shutil.which("node") is None or not Path("node_modules/remotion").is_dir():
        pytest.skip("Remotion dependencies are not installed")
    system_font = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    if not system_font.is_file():
        pytest.skip("deterministic test font is unavailable")

    project = tmp_path / "brand project"
    assets = project / "assets"
    assets.mkdir(parents=True)
    shutil.copy2(system_font, assets / "Lato.ttf")
    (project / ".social-video").mkdir()
    (project / ".social-video/config.yaml").write_text(
        """schema_version: 1
brand_name: Acceptance brand
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
editing_profile: calm-expert
music_policy: none
sfx_policy: none
default_aspect_ratio: \"9:16\"
default_resolution: \"1080x1920\"
default_fps_policy: \"30\"
""",
        encoding="utf-8",
    )
    source = make_video(project / "Mój film.mp4", width=360, height=640, duration=1.2)
    workspace = Workspace.at(project / "edit")
    state = create_workflow(
        [source],
        workspace,
        project_root=project,
        renderer=Renderer.REMOTION,
        remotion_license_attestation=RemotionLicenseAttestation.FREE_LICENSE_ELIGIBLE,
    )
    contract = load_artifact(BrandContract, workspace.brand_contract)
    manifest = build_manifest([source])
    save_artifact(manifest, workspace.source_manifest)
    edl = apply_contract_to_edl(
        EDL(
            ranges=[
                EDLRange(
                    source=manifest.ids[0],
                    start=0,
                    end=1,
                    max_visual_source_time=1,
                )
            ]
        ),
        contract,
    )
    track = CaptionTrack(
        language="pl",
        cues=[CaptionCue(index=1, start=0.05, end=0.9, text="Zażółć gęślą jaźń")],
    )
    caption_json = save_artifact(track, workspace.captions / "main.json")
    write_srt(track, workspace.captions / "main.srt")
    ass = write_ass(
        track,
        contract.brand.captions,
        workspace.captions / "main.ass",
        width=1080,
        height=1920,
        font_name="Lato",
    )
    edl.captions = str(ass)
    save_artifact(edl, workspace.edl)
    plan = MotionPlan(
        font_family="Lato",
        font_path=str(assets / "Lato.ttf"),
        elements=[],
        rationale="The caption contract is sufficient; no extra motion graphics.",
    )
    save_artifact(plan, workspace.motion_plan)

    preview = stage_render(
        edl,
        manifest,
        workspace,
        quality="preview",
        captions=ass,
        renderer=Renderer.REMOTION,
        motion_plan=plan,
        remotion_license_attestation=state.remotion_license_attestation,
    )
    final = stage_render(
        edl,
        manifest,
        workspace,
        quality="final",
        captions=ass,
        renderer=Renderer.REMOTION,
        motion_plan=plan,
        remotion_license_attestation=state.remotion_license_attestation,
    )
    assert probe(preview).video.display_size == (720, 1280)
    info = probe(final)
    assert info.video.display_size == (1080, 1920)
    assert info.video.nominal_frame_rate == "30/1"
    technical = stage_qa(final, edl, workspace)
    brand = load_artifact(QAReport, workspace.brand_qa)
    assert technical.passed
    assert brand.passed
    assert caption_json.is_file()

    before = hashlib.sha256(workspace.edl.read_bytes()).hexdigest()
    delivered = deliver_workspace(
        workspace,
        project / "delivery",
        with_captions=True,
        no_captions=True,
        srt=True,
        vtt=True,
        poster=True,
        resolutions=[],
        allow_temporary=True,
    )
    after = hashlib.sha256(workspace.edl.read_bytes()).hexdigest()
    assert before == after == delivered.edl_sha256_after
    assert (project / "delivery/final.mp4").is_file()
    assert (project / "delivery/final-no-captions.mp4").is_file()
    clean_render = load_artifact(
        RenderManifest, workspace.renders / "final-no-captions.manifest.json"
    )
    assert not clean_render.captions_burned
    assert all(Path(item.path).is_file() for item in delivered.items)
    assert all(
        hashlib.sha256(Path(item.path).read_bytes()).hexdigest() == item.sha256
        for item in delivered.items
    )
