"""1.2/1.3 motion on real renders: graphics, transitions, b-roll, review sheet."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from social_video.edl.render import PREVIEW, render_edl
from social_video.motion.broll import accept_broll, find_broll
from social_video.motion.review import motion_sheet
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import MotionElement, MotionPlan, Transition
from social_video.schemas.transcript import Transcript, TranscriptToken
from social_video.sources import build_manifest
from social_video.transcribe.normalize import synthesize_spacing
from tests.conftest import ffmpeg, make_video, requires_ffmpeg

ROOT = Path(__file__).resolve().parents[2]
HAS_REMOTION = (
    shutil.which("node") is not None
    and (ROOT / "node_modules/remotion").is_dir()
    and (ROOT / "node_modules/.remotion").is_dir()
)
pytestmark = [pytest.mark.integration, requires_ffmpeg]
W, H = 540, 960


def _frame(video: Path, at: float, tmp: Path) -> np.ndarray:
    png = tmp / f"f-{at:.3f}.png"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.3f}", "-i", str(video), "-frames:v", "1",
         str(png)],
        check=True,
    )  # fmt: skip
    with Image.open(png) as image:
        return np.asarray(image.convert("L")).astype(float)


def _sharpness(pixels: np.ndarray) -> float:
    lap = (
        pixels[1:-1, 1:-1] * 4
        - pixels[:-2, 1:-1]
        - pixels[2:, 1:-1]
        - pixels[1:-1, :-2]
        - pixels[1:-1, 2:]
    )
    return float(lap.var())


@pytest.mark.skipif(not HAS_REMOTION, reason="Remotion dependencies/browser not installed")
def test_graphics_transitions_and_style_pack_render(tmp_path: Path) -> None:
    from social_video.remotion import render_motion_design

    base = tmp_path / "base.mp4"
    ffmpeg(
        "-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate=30:duration=4",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "4",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(base),
    )  # fmt: skip
    plan = MotionPlan(
        rationale="1.3 render check",
        style="tech-minimal",
        elements=[
            MotionElement(type="hook_card", start=0, end=1.2, text="Trzy błędy", reason="hook"),
            MotionElement(type="chart", start=2.2, end=3.0, items=["A: 1", "B: 3"], reason="d"),
            MotionElement(type="compare", start=3.0, end=3.5, items=["A: 3", "B: 1"], reason="c"),
            MotionElement(type="steps", start=3.5, end=4.0, items=["Jeden", "Dwa"], reason="s"),
        ],
        transitions=[Transition(at=1.6, style="zoom", duration=0.6, reason="cut")],
    )  # fmt: skip
    output, features, _ = render_motion_design(
        base, tmp_path / "out.mp4", plan, duration_in_frames=120, fps=30, width=W, height=H,
        staging_root=tmp_path / "stage",
    )  # fmt: skip

    assert "transitions" in features
    # The zoom transition blurs the picture at its peak, and only there.
    assert _sharpness(_frame(output, 1.6, tmp_path)) < 0.5 * _sharpness(
        _frame(output, 1.25, tmp_path)
    )
    # Each graphic changes the picture while it is on screen.
    source = {at: _frame(base, at, tmp_path) for at in (0.8, 2.7, 3.3, 3.8)}
    for at, before in source.items():
        after = _frame(output, at, tmp_path)
        assert np.abs(after - before).mean() > 8, f"nothing drawn at {at}s"

    sheet = motion_sheet(output, plan, tmp_path / "motion-sheet.png", tile_width=200)
    with Image.open(sheet) as image:
        assert image.width == 4 * 200 + 3 * 4  # five moments, four to a row
        assert image.height > 300


def test_broll_from_the_library_is_matched_and_cut_in(tmp_path: Path) -> None:
    speaker = tmp_path / "rozmowa.mp4"
    ffmpeg(
        "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r=30:d=8",
        "-f", "lavfi", "-i", "sine=d=8", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(speaker),
    )  # fmt: skip
    library = tmp_path / "b-roll"
    make_video(library / "samochod-elektryczny.mp4", width=W, height=H, duration=3)
    make_video(library / "biuro.mp4", width=W, height=H, duration=3)
    (library / "biuro.mp4.txt").write_text("office, praca", encoding="utf-8")
    words = [("Nowy", 1.0, 1.3), ("samochodu", 1.4, 2.0), ("nie", 2.1, 2.3), ("kupię.", 2.35, 2.8)]
    transcript = Transcript(
        source_id="rozmowa", source_fingerprint="f" * 16, duration=8.0, provider="test",
        tokens=synthesize_spacing([TranscriptToken(text=t, start=s, end=e) for t, s, e in words]),
    )  # fmt: skip
    edl = EDL(
        output_width=W, output_height=H, ranges=[EDLRange(source="rozmowa", start=0, end=7.5)]
    )

    found = find_broll(transcript, edl, library)

    (candidate,) = found.candidates
    assert Path(candidate.file).name == "samochod-elektryczny.mp4"
    assert candidate.confidence == "medium"  # "samochodu" matched by its stem
    assert candidate.at == pytest.approx(1.4)
    updated, (overlay,) = accept_broll(edl, found, [candidate.id])
    assert overlay.scale_width == W

    output = tmp_path / "out.mp4"
    render_edl(updated, build_manifest([speaker]), output, quality=PREVIEW)
    assert _frame(output, 2.5, tmp_path).mean() > 30, "the b-roll is on screen"
    assert _frame(output, 0.5, tmp_path).mean() < 5, "before it, the black source"
