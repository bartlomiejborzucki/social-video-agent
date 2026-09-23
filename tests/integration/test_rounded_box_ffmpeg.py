"""A rounded caption box on the FFmpeg route: drawn by libass, as measured.

The box used to require Remotion. It is now drawn from the same layout the
compositor gets, so a project that cannot use Remotion keeps its brand.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from social_video.captions.srt import write_srt
from social_video.ffmpeg.run import has_libass
from social_video.pipeline import stage_render
from social_video.project_config import apply_contract_to_edl, compile_brand_contract
from social_video.qa.brand import check_brand
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.captions import CaptionCue, CaptionTrack
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.qa import RenderManifest
from social_video.schemas.workflow import Renderer
from social_video.sources import build_manifest
from social_video.workspace.layout import Workspace
from tests.conftest import ffmpeg, requires_ffmpeg

FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
pytestmark = [
    pytest.mark.integration,
    requires_ffmpeg,
    pytest.mark.skipif(not has_libass(), reason="ffmpeg built without libass"),
    pytest.mark.skipif(not FONT.is_file(), reason="deterministic test font is unavailable"),
]


def test_the_ffmpeg_route_draws_the_contracted_rounded_box(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "assets").mkdir(parents=True)
    shutil.copy2(FONT, project / "assets" / "Brand.ttf")
    config = project / "social-video.yaml"
    config.write_text(
        """schema_version: 1
font: DejaVu Sans
font_file: assets/Brand.ttf
caption_style:
  text_color: "#FFFFFF"
  background_color: "#28BCA5"
  background_style: rounded_box
  corner_radius: 40
  position: lower_safe_zone
  bottom_margin_pct: 22
""",
        encoding="utf-8",
    )
    workspace = Workspace.at(project / "edit")
    workspace.ensure()
    contract = compile_brand_contract(config, workspace, project_root=project)
    save_artifact(contract, workspace.brand_contract)
    source = project / "czarne.mp4"
    ffmpeg(
        "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=30:d=1.2",
        "-f", "lavfi", "-i", "sine=d=1.2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(source),
    )  # fmt: skip
    manifest = build_manifest([source])
    save_artifact(manifest, workspace.source_manifest)
    track = CaptionTrack(cues=[CaptionCue(index=1, start=0.1, end=1.0, text="Zażółć gęślą jaźń")])
    save_artifact(track, workspace.captions / "main.json")
    srt = write_srt(track, workspace.captions / "main.srt")
    edl = apply_contract_to_edl(
        EDL(ranges=[EDLRange(source=manifest.ids[0], start=0, end=1.1)]), contract
    )
    edl.normalize_audio = False
    save_artifact(edl, workspace.edl)

    output = stage_render(
        edl, manifest, workspace, quality="final", captions=srt, renderer=Renderer.FFMPEG
    )

    png = tmp_path / "frame.png"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", "0.5", "-i", str(output), "-frames:v", "1",
         str(png)],
        check=True,
    )  # fmt: skip
    with Image.open(png) as image:
        pixels = np.asarray(image.convert("RGB")).astype(int)
    teal = (
        (abs(pixels[..., 0] - 0x28) < 30)
        & (abs(pixels[..., 1] - 0xBC) < 30)
        & (abs(pixels[..., 2] - 0xA5) < 30)
    )
    rows, cols = np.nonzero(teal)
    top, bottom, left, right = rows.min(), rows.max(), cols.min(), cols.max()
    # A real box, low in the frame and clear of the bottom 22%.
    assert right - left > 200 and bottom - top > 50
    assert bottom < 1920 * 0.78 + 4
    # Rounded: the corner itself is not filled, a radius in from it is.
    assert not teal[top + 2, left + 2]
    assert teal[top + 2, left + 45]
    assert teal[top + 45, left + 2]
    # White text sits inside the box and nowhere else.
    white = pixels.min(axis=-1) > 230
    text_rows, text_cols = np.nonzero(white)
    assert text_rows.size > 500
    assert top <= text_rows.min() and text_rows.max() <= bottom
    assert left <= text_cols.min() and text_cols.max() <= right

    render = load_artifact(RenderManifest, workspace.renders / "final.manifest.json")
    assert "caption_layout_measured" in render.caption_features
    assert render.caption_layout["truncated_cues"] == []
    report = check_brand(output, contract, render)
    assert [check.name for check in report.errors] == []
