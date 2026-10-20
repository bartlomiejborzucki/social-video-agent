"""Real Remotion smoke coverage with synthetic, offline media."""

from __future__ import annotations

import shutil
import subprocess
from itertools import pairwise
from pathlib import Path

import pytest

from social_video.ffmpeg.fonts import default_caption_font
from social_video.ffmpeg.probe import probe
from social_video.ffmpeg.run import run_ffprobe_json
from social_video.pipeline import stage_render
from social_video.qa.checks import check_render
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import MotionElement, MotionElementType, MotionPlan
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


@pytest.mark.parametrize("quality", ["preview", "final"])
def test_remotion_renders_social_mp4_with_unicode_motion_graphics(
    tmp_path: Path, quality: str
) -> None:
    base = make_video(
        tmp_path / "Mój techniczny montaż.mp4",
        width=360,
        height=640,
        fps=30,
        duration=2.0,
        audio_channels=2,
    )
    output = tmp_path / f"gotowy Reel {quality}.mp4"
    font = default_caption_font()
    assert font is not None
    plan = MotionPlan(
        style="editorial_clean",
        rationale="An intentional opening card reinforces the approved hook.",
        font_family=font.family,
        font_path=str(font.path),
        elements=[
            MotionElement(
                type=MotionElementType.HOOK,
                start=0.1,
                end=1.4,
                text="Zażółć gęślą jaźń",
                secondary_text="Profesjonalny Reel",
                reason="Make the approved hook scannable without covering captions.",
            )
        ],
    )

    manifest = build_manifest([base])
    source_id = manifest.ids[0]
    edl = EDL(
        output_width=360,
        output_height=640,
        output_fps="30/1",
        normalize_audio=False,
        ranges=[EDLRange(source=source_id, start=0, end=2)],
    )
    stage_render(
        edl,
        manifest,
        Workspace.at(tmp_path / "edit"),
        quality=quality,
        output=output,
        renderer=Renderer.REMOTION,
        motion_plan=plan,
        remotion_license_attestation=RemotionLicenseAttestation.FREE_LICENSE_ELIGIBLE,
    )

    info = probe(output)
    assert info.video is not None
    assert info.video.codec == "h264"
    assert info.video.nominal_frame_rate == "30/1"
    assert info.video.nb_frames == 60
    assert info.video.display_size == (360, 640)
    assert info.audio[0].codec == "aac"
    assert info.audio[0].sample_rate == 48000
    assert info.audio[0].channels == 2

    packets = run_ffprobe_json(
        [
            "-select_streams",
            "a:0",
            "-show_packets",
            "-show_entries",
            "packet=pts_time,duration_time",
            str(output),
        ],
        desc="probe Remotion AAC cadence",
    )["packets"]
    pts = [float(packet["pts_time"]) for packet in packets]
    assert all(right > left for left, right in pairwise(pts))
    assert pts[1] - pts[0] == pytest.approx(1024 / 48000, abs=0.0001)
    audio_end = max(
        float(packet["pts_time"]) + float(packet["duration_time"]) for packet in packets
    )
    assert audio_end == pytest.approx(2.0, abs=2 * 1024 / 48000)

    report = check_render(output, edl)
    assert report.passed, [check.message for check in report.errors]
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(output),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
    )


def test_remotion_render_keeps_the_base_audio_in_sync(tmp_path: Path) -> None:
    """The motion layer must not move the sound against the picture."""
    source = tmp_path / "pulses.mp4"
    # A flash and a click on the same irregular beat, so both the picture and
    # the sound have something to correlate.
    beat = "lt(mod({t}*7.3,1.9),0.25)"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=360x640:rate=30:duration=12,format=yuv420p,"
            f"geq=lum='lum(X,Y)*(0.4+0.6*{beat.format(t='T')})'"
            ":cb='cb(X,Y)':cr='cr(X,Y)'",
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc='0.5*sin(2*PI*660*t)*{beat.format(t='t')}':s=48000:d=12",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ac",
            "2",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    font = default_caption_font()
    assert font is not None
    plan = MotionPlan(
        style="editorial_clean",
        rationale="A label over the whole edit, so the compositor draws something.",
        font_family=font.family,
        font_path=str(font.path),
        elements=[
            MotionElement(
                type=MotionElementType.LABEL,
                start=0.0,
                end=12.0,
                text="Synchronizacja",
                reason="Exercise the compositor across the full timeline.",
            )
        ],
    )
    manifest = build_manifest([source])
    edl = EDL(
        output_width=360,
        output_height=640,
        output_fps="30/1",
        normalize_audio=False,
        ranges=[EDLRange(source=manifest.ids[0], start=0, end=12)],
    )
    ws = Workspace.at(tmp_path / "edit")
    output = tmp_path / "final.mp4"
    stage_render(
        edl,
        manifest,
        ws,
        quality="final",
        output=output,
        renderer=Renderer.REMOTION,
        motion_plan=plan,
        remotion_license_attestation=RemotionLicenseAttestation.FREE_LICENSE_ELIGIBLE,
    )
    from social_video.pipeline import _sync_against_base

    check = _sync_against_base(output, ws)
    assert check is not None
    assert check.passed, check.message
    assert abs(check.measured or 0.0) <= 0.020
