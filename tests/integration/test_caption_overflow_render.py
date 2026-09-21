"""Render long Polish captions for real and prove nothing was cut off.

The unit tests measure the layout; this renders it. It exists because the
defect was invisible to every check we had: the compositor clamped the overflow
with `-webkit-line-clamp`, so the frame looked deliberate and the last words of
`nikomu, udowadniając na siłę` were simply gone.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from social_video.captions.ass import write_ass
from social_video.ffmpeg.probe import probe
from social_video.pipeline import stage_qa, stage_render
from social_video.project_config import apply_contract_to_edl, compile_brand_contract
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.captions import CaptionCue, CaptionTrack
from social_video.schemas.config import BrandContract
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import MotionPlan
from social_video.schemas.qa import QAReport, RenderManifest
from social_video.schemas.workflow import RemotionLicenseAttestation, Renderer
from social_video.sources import build_manifest
from social_video.workspace.layout import Workspace
from tests.conftest import make_video, requires_ffmpeg

ROOT = Path(__file__).resolve().parents[2]
HAS_REMOTION = (
    shutil.which("node") is not None
    and (ROOT / "node_modules/remotion").is_dir()
    and (ROOT / "node_modules/.remotion").is_dir()
)

pytestmark = [
    pytest.mark.integration,
    requires_ffmpeg,
    pytest.mark.skipif(not HAS_REMOTION, reason="Remotion dependencies/browser not installed"),
]

#: The reported phrases, plus the four words that used to lose their endings.
CUE_TEXTS = (
    "nikomu, udowadniając",
    "na siłę wziąć",
    "odpowiedzialność za",
    "wyregulowany system",
    "doświadczać tego",
)
#: The reference project config: exactly the values the template now ships.
CONFIG = """schema_version: 1
brand_name: Caption regression
font: Lato
font_file: assets/Lato.ttf
brand_colors: ["#28BCA5"]
caption_style:
  case: as_spoken
  font_weight: bold
  text_color: "#FFFFFF"
  background_color: "#28BCA5"
  background_style: rounded_box
  corner_radius: 24
  outline_color: "#394463"
  outline_or_shadow: none
  font_size_pct: 3.6
  max_lines: 2
  max_words_per_cue: 4
  max_chars_per_cue: 24
  position: lower_safe_zone
  bottom_margin_pct: 22
safe_margins:
  top: 6
  right: 6
  bottom: 22
  left: 6
editing_profile: calm-expert
default_aspect_ratio: "9:16"
default_resolution: "1080x1920"
default_fps_policy: "30"
"""


def _project(tmp_path: Path) -> tuple[Path, Path, BrandContract, Workspace]:
    system_font = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    if not system_font.is_file():
        pytest.skip("deterministic test font is unavailable")
    project = tmp_path / "napisy"
    assets = project / "assets"
    assets.mkdir(parents=True)
    shutil.copy2(system_font, assets / "Lato.ttf")
    (project / ".social-video").mkdir()
    config = project / ".social-video/config.yaml"
    config.write_text(CONFIG, encoding="utf-8")
    workspace = Workspace.at(project / "edit")
    contract = compile_brand_contract(config, workspace, project_root=project)
    return project, assets / "Lato.ttf", contract, workspace


def _track(duration: float) -> CaptionTrack:
    span = duration / len(CUE_TEXTS)
    return CaptionTrack(
        language="pl",
        cues=[
            CaptionCue(
                index=i,
                start=round((i - 1) * span, 3),
                end=round(i * span - 0.02, 3),
                text=text,
            )
            for i, text in enumerate(CUE_TEXTS, start=1)
        ],
    )


@pytest.mark.slow
@pytest.mark.parametrize(
    ("quality", "expected_size"),
    [("final", (1080, 1920)), ("preview", (720, 1280))],
)
def test_long_polish_captions_render_without_being_shortened(
    tmp_path: Path, quality: str, expected_size: tuple[int, int]
) -> None:
    project, font, contract, workspace = _project(tmp_path)
    duration = 2.0
    source = make_video(project / "rozmowa.mp4", width=360, height=640, duration=duration + 0.3)
    manifest = build_manifest([source])
    save_artifact(manifest, workspace.source_manifest)
    track = _track(duration)
    save_artifact(track, workspace.captions / "main.json")
    ass = write_ass(
        track,
        contract.brand.captions,
        workspace.captions / "main.ass",
        width=contract.output_width,
        height=contract.output_height,
        font_name=contract.brand.captions.font_family,
    )
    edl = apply_contract_to_edl(
        EDL(
            ranges=[
                EDLRange(
                    source=manifest.ids[0], start=0, end=duration, max_visual_source_time=duration
                )
            ]
        ),
        contract,
    )
    edl.captions = str(ass)
    save_artifact(edl, workspace.edl)
    plan = MotionPlan(
        font_family=contract.brand.captions.font_family,
        font_path=str(font),
        elements=[],
        rationale="The caption contract is the whole visual layer for this regression.",
    )
    save_artifact(plan, workspace.motion_plan)

    output = stage_render(
        edl,
        manifest,
        workspace,
        quality=quality,
        captions=ass,
        renderer=Renderer.REMOTION,
        motion_plan=plan,
        remotion_license_attestation=RemotionLicenseAttestation.FREE_LICENSE_ELIGIBLE,
    )

    assert probe(output).video.display_size == expected_size
    render = load_artifact(RenderManifest, workspace.renders / f"{output.stem}.manifest.json")
    layout = render.caption_layout
    assert layout, "the Remotion route must record the caption geometry it drew"
    assert layout["truncated_cues"] == []
    assert layout["ellipsis_cues"] == []
    assert layout["over_length_cues"] == []
    assert layout["font_measured"] is True
    assert layout["max_line_width_px"] <= layout["text_box_width_px"]
    assert layout["min_font_size_px"] == layout["requested_font_size_px"], (
        "the reference contract must render every cue at its contracted size"
    )
    assert "caption_layout_measured" in render.caption_features

    technical = stage_qa(output, edl, workspace)
    assert technical.passed, [check.message for check in technical.errors]
    brand = load_artifact(QAReport, workspace.brand_qa)
    checks = {check.name: check for check in brand.checks}
    assert checks["captions are drawn in full"].passed
    assert checks["captions carry no added ellipsis"].passed
    assert checks["captions fit the caption box"].passed
    assert checks["caption cue length within the contract"].passed
    assert checks["caption size matches the contract"].passed
    if quality == "final":
        assert brand.passed, [check.message for check in brand.errors]
    else:
        # A preview is deliberately half-size, so the contract's own resolution
        # check is expected to fail here and nothing else is.
        assert {check.name for check in brand.errors} == {"brand output resolution"}
