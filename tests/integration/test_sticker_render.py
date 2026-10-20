"""A sticker on a word and a shake under it, on both renderers."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from social_video.ffmpeg.fonts import default_caption_font
from social_video.pipeline import stage_render
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import MotionElement, MotionElementType, MotionPlan, Shake
from social_video.schemas.workflow import RemotionLicenseAttestation, Renderer
from social_video.sources import build_manifest
from social_video.workspace.layout import Workspace
from tests.conftest import make_video, requires_ffmpeg

ROOT = Path(__file__).resolve().parents[2]
HAS_REMOTION = shutil.which("node") is not None and (ROOT / "node_modules/.remotion").is_dir()

pytestmark = [pytest.mark.integration, requires_ffmpeg]


def _frame(video: Path, at: float, size=(90, 160)) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{at}", "-i", str(video), "-frames:v", "1",
         "-vf", f"scale={size[0]}:{size[1]}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True, capture_output=True,
    ).stdout  # fmt: skip
    return np.frombuffer(raw, dtype=np.uint8).reshape(size[1], size[0], 3).astype(float)


def _setup(tmp_path: Path) -> tuple[Path, EDL, object, Workspace, MotionPlan]:
    source = make_video(tmp_path / "plac.mp4", width=360, height=640, duration=3.0,
                        audio_channels=2)  # fmt: skip
    red = tmp_path / "wstrzas.png"
    Image.new("RGBA", (64, 64), (255, 0, 0, 255)).save(red)
    font = default_caption_font()
    assert font is not None
    plan = MotionPlan(
        rationale="Shock at the promise.",
        font_family=font.family,
        font_path=str(font.path),
        elements=[
            MotionElement(type=MotionElementType.STICKER, start=1.0, end=2.0,
                          image_asset=str(red), animation="pop", size_pct=15,
                          x_pct=0.75, y_pct=0.25, reason="Shock at 'Zgodziłeś!'.")
        ],
        shakes=[Shake(start=1.0, end=1.4, amplitude_pct=2.0, reason="The promise shakes.")],
    )  # fmt: skip
    manifest = build_manifest([source])
    edl = EDL(output_width=360, output_height=640, output_fps="30/1", normalize_audio=False,
              ranges=[EDLRange(source=manifest.ids[0], start=0, end=3)])  # fmt: skip
    ws = Workspace.at(tmp_path / "edit")
    ws.ensure()
    return source, edl, manifest, ws, plan


def test_ffmpeg_route_shakes_the_picture_inside_the_window_only(tmp_path: Path) -> None:
    from social_video.schemas.base import save_artifact

    _source, edl, manifest, ws, plan = _setup(tmp_path)
    save_artifact(plan, ws.motion_plan)
    plain = tmp_path / "plain.mp4"
    shaken = tmp_path / "shaken.mp4"
    stage_render(edl, manifest, ws, quality="draft", output=plain, renderer=Renderer.FFMPEG)
    ws.motion_plan.unlink()
    stage_render(edl, manifest, ws, quality="draft", output=tmp_path / "steady.mp4",
                 renderer=Renderer.FFMPEG)  # fmt: skip
    save_artifact(plan, ws.motion_plan)
    stage_render(edl, manifest, ws, quality="draft", output=shaken, renderer=Renderer.FFMPEG)
    steady = tmp_path / "steady.mp4"
    assert np.abs(_frame(shaken, 1.2) - _frame(steady, 1.2)).mean() > 3
    assert np.abs(_frame(shaken, 2.5) - _frame(steady, 2.5)).mean() < 2


@pytest.mark.skipif(not HAS_REMOTION, reason="Remotion dependencies/browser not installed")
def test_remotion_draws_the_sticker_and_the_shake(tmp_path: Path) -> None:
    _source, edl, manifest, ws, plan = _setup(tmp_path)
    output = tmp_path / "final.mp4"
    stage_render(
        edl, manifest, ws, quality="preview", output=output, renderer=Renderer.REMOTION,
        motion_plan=plan,
        remotion_license_attestation=RemotionLicenseAttestation.FREE_LICENSE_ELIGIBLE,
    )  # fmt: skip
    shown = _frame(output, 1.6)
    # The sticker's box (centre 0.75, 0.25 of a 90x160 frame) is red.
    patch = shown[36:44, 64:72]
    assert patch[..., 0].mean() > 200 and patch[..., 1].mean() < 60
    before = _frame(output, 0.5)
    assert not (before[36:44, 64:72, 0].mean() > 200 and before[36:44, 64:72, 1].mean() < 60)
    from social_video.schemas.base import load_artifact
    from social_video.schemas.qa import RenderManifest

    evidence = load_artifact(RenderManifest, ws.renders / "final.manifest.json")
    assert evidence.stickers_applied and "image" in evidence.stickers_applied[0]
