"""An end card's own words must be drawn over its plate, not under it.

The plate is an absolutely positioned background image; the text is in-flow.
Without an explicit stacking position the image paints over the text, and the
end card renders as a wordless gradient -- which is exactly the failure the
"image tools draw backgrounds, Remotion draws every word" rule exists to
prevent. A pixel check is the only honest test for it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image

from social_video.ffmpeg.fonts import default_caption_font
from social_video.ffmpeg.run import run_ffmpeg
from social_video.imagegen import register_visual
from social_video.pipeline import stage_render
from social_video.schemas.base import save_artifact
from social_video.schemas.brand import BrandProfile, CaptionStyle
from social_video.schemas.config import BrandContract
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import MotionElement, MotionElementType, MotionPlan
from social_video.schemas.visuals import VisualKind
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


@pytest.mark.slow
def test_end_card_text_is_drawn_over_a_registered_plate(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    workspace = Workspace.at(project / "edit")
    workspace.ensure()
    font = default_caption_font()
    assert font is not None
    save_artifact(
        BrandContract(
            project_config_path="c.yaml",
            project_config_sha256="a" * 64,
            project_root=str(project),
            brand=BrandProfile(captions=CaptionStyle(font_family=font.family)),
            output_width=360,
            output_height=640,
            output_fps="30/1",
            image_generation_enabled=True,
        ),
        workspace.brand_contract,
    )
    # A dark, featureless plate: any variance in the finished frame is glyphs.
    plate = tmp_path / "plate.png"
    Image.new("RGB", (1080, 1920), (10, 14, 20)).save(plate)
    visual = register_visual(
        workspace,
        VisualKind.END_CARD_PLATE,
        plate,
        prompt="Create a background plate. Absolute requirements: no text. Subject: dark field",
        purpose="end card background",
    )

    source = make_video(project / "clip.mp4", width=360, height=640, duration=2.0)
    manifest = build_manifest([source])
    save_artifact(manifest, workspace.source_manifest)
    edl = EDL(
        output_width=360,
        output_height=640,
        output_fps="30/1",
        brand_profile="a" * 64,
        ranges=[EDLRange(source=manifest.ids[0], start=0, end=1.5, max_visual_source_time=1.5)],
    )
    save_artifact(edl, workspace.edl)
    plan = MotionPlan(
        font_family=font.family,
        font_path=str(font.path),
        rationale="The plate carries the end card; the CTA itself is drawn locally.",
        elements=[
            MotionElement(
                type=MotionElementType.END_CARD,
                start=0.5,
                end=1.5,
                text="Zażółć gęślą jaźń",
                reason="Close on the call to action.",
                image_asset=visual.path,
                image_dim_pct=45,
            )
        ],
    )
    save_artifact(plan, workspace.motion_plan)

    output = stage_render(
        edl,
        manifest,
        workspace,
        quality="final",
        renderer=Renderer.REMOTION,
        motion_plan=plan,
        remotion_license_attestation=RemotionLicenseAttestation.FREE_LICENSE_ELIGIBLE,
    )

    frame = tmp_path / "end-card.png"
    run_ffmpeg(
        ["-y", "-i", str(output), "-vf", "select=eq(n\\,30)", "-frames:v", "1", str(frame)],
        desc="extract the end-card frame",
    )
    with Image.open(frame) as image:
        band = image.convert("L").crop((0, 200, 360, 440))
    pixels = [band.getpixel((x, y)) for y in range(band.height) for x in range(band.width)]
    brightest = max(pixels)
    darkest = min(pixels)

    # White type on a near-black plate. If the plate covered the text the band
    # would be uniformly dark, so the contrast is the assertion.
    assert brightest > 200, f"no bright glyphs in the end card band (max {brightest})"
    assert brightest - darkest > 150, "the end-card band has no contrast: text is hidden"
