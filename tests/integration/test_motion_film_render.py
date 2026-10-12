"""1.4 on a real render: an imported Motion segment composited on the FFmpeg route."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from social_video.errors import ValidationError
from social_video.motion.film import build_film_spec, import_film, write_film_spec
from social_video.pipeline import stage_render
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import MotionElement, MotionPlan
from social_video.schemas.qa import RenderManifest
from social_video.schemas.workflow import Renderer
from social_video.sources import build_manifest
from social_video.workspace.layout import Workspace
from tests.conftest import ffmpeg, requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]
W, H = 540, 960


def _colour_at(video: Path, at: float) -> np.ndarray:
    """The mean RGB of one output frame."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{at:.3f}", "-i", str(video), "-frames:v", "1",
         "-vf", "scale=16:-2", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    return np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).mean(axis=0)


def test_an_imported_segment_is_on_screen_where_its_graphic_was(tmp_path: Path) -> None:
    source = tmp_path / "talk.mp4"
    ffmpeg(
        "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r=30:d=6",
        "-f", "lavfi", "-i", "sine=d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(source),
    )  # fmt: skip
    ws = Workspace.at(tmp_path / "edit")
    ws.ensure()
    edl = EDL(
        output_width=W, output_height=H, output_fps="30",
        ranges=[EDLRange(source="talk", start=0, end=5.5)],
    )  # fmt: skip
    save_artifact(edl, ws.edl)
    plan = MotionPlan(
        rationale="r",
        elements=[MotionElement(type="hook_card", start=0.0, end=1.8, text="Hook", reason="r")],
    )
    save_artifact(plan, ws.motion_plan)
    write_film_spec(ws, build_film_spec(edl, plan, None))
    export = tmp_path / "film.mp4"
    ffmpeg("-f", "lavfi", "-i", f"color=c=red:s={W}x{H}:r=30:d=1.8", "-c:v", "libx264",
           "-pix_fmt", "yuv420p", str(export))  # fmt: skip
    import_film(ws, export, film_id="main-film", font_used="Inter")

    output = stage_render(
        load_artifact(EDL, ws.edl),
        build_manifest([source]),
        ws,
        quality="preview",
        renderer=Renderer.FFMPEG,
    )

    red, green, blue = _colour_at(output, 0.9)
    assert red > 200 and green < 40 and blue < 40, "the film's red card is on screen"
    assert _colour_at(output, 3.0).max() < 30, "after it, the black recording"
    manifest = load_artifact(RenderManifest, ws.renders / f"{output.stem}.manifest.json")
    (segment,) = manifest.motion_film_segments
    assert segment["scene_id"] == "hook-card-1"
    assert segment["sha256"] == segment["recorded_sha256"]

    Path(segment["path"]).unlink()
    with pytest.raises(ValidationError, match="missing at"):
        stage_render(
            load_artifact(EDL, ws.edl),
            build_manifest([source]),
            ws,
            quality="preview",
            renderer=Renderer.FFMPEG,
        )
