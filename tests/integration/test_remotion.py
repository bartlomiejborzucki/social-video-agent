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
from social_video.schemas.motion import (
    MotionElement,
    MotionElementType,
    MotionPlan,
    Transition,
    TransitionStyle,
)
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


def test_a_held_end_card_lasts_to_the_final_frame(tmp_path: Path) -> None:
    import numpy as np

    from social_video.pipeline import stage_qa
    from social_video.schemas.base import save_artifact

    source = make_video(tmp_path / "kamera.mp4", width=360, height=640, fps=30, duration=2.0,
                        audio_channels=2)  # fmt: skip
    font = default_caption_font()
    assert font is not None
    plan = MotionPlan(
        style="editorial_clean",
        rationale="A link card after the last word.",
        font_family=font.family,
        font_path=str(font.path),
        background_color="#101114",
        elements=[
            MotionElement(
                type=MotionElementType.END_CARD,
                start=0.0,
                end=1.5,
                hold=True,
                text="Nowy poradnik\nprzyklad-marki.example/strona-z-zapisami/",
                secondary_text="link także w bio",
                reason="The waiting-list link, after the last word.",
            )
        ],
    )
    manifest = build_manifest([source])
    ws = Workspace.at(tmp_path / "edit")
    ws.ensure()
    edl = EDL(
        output_width=360,
        output_height=640,
        output_fps="30/1",
        normalize_audio=False,
        ranges=[EDLRange(source=manifest.ids[0], start=0, end=2)],
    )
    save_artifact(edl, ws.edl)
    save_artifact(plan, ws.motion_plan)
    output = ws.final / "final.mp4"
    stage_render(
        edl,
        manifest,
        ws,
        quality="final",
        renderer=Renderer.REMOTION,
        motion_plan=plan,
        remotion_license_attestation=RemotionLicenseAttestation.FREE_LICENSE_ELIGIBLE,
    )
    info = probe(output)
    assert info.video is not None and info.video.nb_frames == 105
    last = subprocess.run(
        ["ffmpeg", "-v", "error", "-sseof", "-0.04", "-i", str(output), "-frames:v", "1",
         "-vf", "scale=36:64,format=gray", "-f", "rawvideo", "-"],
        check=True, capture_output=True,
    ).stdout  # fmt: skip
    pixels = np.frombuffer(last, dtype=np.uint8).astype(float)
    # The card's dark ground, not the colour bars underneath.
    assert pixels.mean() < 60
    from social_video.schemas.base import load_artifact

    saved = load_artifact(EDL, ws.edl)
    assert saved.end_hold == pytest.approx(1.5)
    report = stage_qa(output, saved, ws, sheets=False)
    names = {c.name: c for c in report.checks}
    assert names["duration matches EDL"].passed
    assert names["ending visual continuity"].passed
    assert names["audio/video sync against base"].passed


def test_a_light_leak_washes_over_its_cut_only(tmp_path: Path) -> None:
    import numpy as np

    source = make_video(tmp_path / "kamera.mp4", width=360, height=640, fps=30, duration=2.0,
                        audio_channels=2)  # fmt: skip
    font = default_caption_font()
    assert font is not None
    plan = MotionPlan(
        style="editorial_clean",
        rationale="One warm transition across the cut.",
        font_family=font.family,
        font_path=str(font.path),
        elements=[],
        transitions=[
            Transition(at=1.0, style=TransitionStyle.LIGHT_LEAK, duration=0.6, reason="cut")
        ],
    )
    manifest = build_manifest([source])
    edl = EDL(
        output_width=360,
        output_height=640,
        output_fps="30/1",
        normalize_audio=False,
        ranges=[EDLRange(source=manifest.ids[0], start=0, end=2)],
    )
    output = tmp_path / "przejscie.mp4"
    stage_render(
        edl,
        manifest,
        Workspace.at(tmp_path / "edit"),
        quality="final",
        output=output,
        renderer=Renderer.REMOTION,
        motion_plan=plan,
        remotion_license_attestation=RemotionLicenseAttestation.FREE_LICENSE_ELIGIBLE,
    )

    def difference(at: float) -> float:
        frames = [
            np.frombuffer(
                subprocess.run(
                    ["ffmpeg", "-v", "error", "-ss", f"{at}", "-i", str(path), "-frames:v", "1",
                     "-vf", "scale=36:64,format=gray", "-f", "rawvideo", "-"],
                    check=True, capture_output=True,
                ).stdout,
                dtype=np.uint8,
            ).astype(float)
            for path in (source, output)
        ]  # fmt: skip
        return float(np.abs(frames[0] - frames[1]).mean())

    # Away from the cut the picture is the source; on it, the leak covers it.
    assert difference(0.3) < 6
    assert difference(1.0) > 15


def test_text_variants_share_the_audio_and_leave_the_edit_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from social_video.motion.variant_service import VariantRequest, make_variants
    from social_video.schemas.base import save_artifact

    source = make_video(tmp_path / "kamera.mp4", duration=5.0, width=360, height=640)
    font = default_caption_font()
    assert font is not None
    manifest = build_manifest([source])
    ws = Workspace.at(tmp_path / "edit").ensure()
    save_artifact(manifest, ws.source_manifest)
    save_artifact(
        EDL(
            output_width=360, output_height=640, output_fps="30/1", normalize_audio=False,
            ranges=[EDLRange(source=manifest.ids[0], start=0, end=5)],
        ),
        ws.edl,
    )  # fmt: skip
    save_artifact(
        MotionPlan(rationale="r", font_family=font.family, font_path=str(font.path)),
        ws.motion_plan,
    )
    main_base = ws.cache / "remotion" / "base-preview.mp4"
    main_base.parent.mkdir(parents=True, exist_ok=True)
    main_base.write_bytes(b"main edit base")
    edl_before, plan_before = ws.edl.read_bytes(), ws.motion_plan.read_bytes()
    monkeypatch.setattr(
        "social_video.workflow.load_workflow",
        lambda _ws: SimpleNamespace(
            renderer=Renderer.REMOTION,
            remotion_license_attestation=RemotionLicenseAttestation.FREE_LICENSE_ELIGIBLE,
        ),
    )

    result, _ = make_variants(
        ws,
        VariantRequest(
            texts=["Pierwsza wersja", "Druga wersja"],
            hypotheses=["a question", "a statement"],
            seconds=2.0,
        ),
    )

    assert [v.name for v in result.variants] == ["a", "b"]
    hashes = {v.audio_sha256 for v in result.variants}
    assert len(hashes) == 1 and None not in hashes
    assert all(Path(v.preview).is_file() for v in result.variants)
    assert ws.edl.read_bytes() == edl_before
    assert ws.motion_plan.read_bytes() == plan_before
    assert main_base.read_bytes() == b"main edit base"


def test_a_first_shot_variant_previews_renders_full_and_delivers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from social_video.delivery import deliver_workspace
    from social_video.motion.variant_service import VariantRequest, make_variants
    from social_video.schemas.base import load_artifact, save_artifact

    source = make_video(tmp_path / "kamera.mp4", duration=6.0, width=360, height=640)
    font = default_caption_font()
    assert font is not None
    manifest = build_manifest([source])
    sid = manifest.ids[0]
    ws = Workspace.at(tmp_path / "edit").ensure()
    save_artifact(manifest, ws.source_manifest)
    save_artifact(
        EDL(
            output_width=360, output_height=640, output_fps="30/1", normalize_audio=False,
            ranges=[EDLRange(source=sid, start=0, end=3), EDLRange(source=sid, start=3, end=6)],
        ),
        ws.edl,
    )  # fmt: skip
    save_artifact(
        MotionPlan(rationale="r", font_family=font.family, font_path=str(font.path)),
        ws.motion_plan,
    )
    edl_before = ws.edl.read_bytes()
    state = SimpleNamespace(
        renderer=Renderer.REMOTION,
        remotion_license_attestation=RemotionLicenseAttestation.FREE_LICENSE_ELIGIBLE,
    )
    monkeypatch.setattr("social_video.workflow.load_workflow", lambda _ws: state)
    monkeypatch.setattr("social_video.delivery.load_workflow", lambda _ws: state, raising=False)

    previews, _ = make_variants(
        ws,
        VariantRequest(
            first_shots=[f"{sid}:4.0-5.0"],
            pickups=["a close-up of the hands"],
            hypotheses=["movement first", "a detail first"],
            seconds=2.0,
        ),
    )
    shot, pickup = previews.variants
    assert previews.axis.value == "first_shot"
    assert Path(shot.preview).is_file()
    assert any("repeats footage used in range 2" in w for w in shot.warnings)
    assert pickup.needs_pickup and not pickup.preview
    variant_edl = load_artifact(EDL, Path(shot.edl or ""))
    assert variant_edl.ranges[0].start == 4.0
    assert variant_edl.ranges[1:] == load_artifact(EDL, ws.edl).ranges[1:]

    whole, _ = make_variants(ws, VariantRequest(only=["a"], seconds=None))
    assert whole.chosen == "a"
    assert Path(whole.variants[0].full).is_file()

    delivered = deliver_workspace(
        ws, tmp_path / "delivery", with_captions=False, no_captions=False, srt=False,
        vtt=False, poster=False, hook_variants=True, allow_temporary=True,
    )  # fmt: skip
    (item,) = [i for i in delivered.items if i.variant == "a"]
    assert item.variant_axis == "first_shot"
    assert item.variant_hypothesis == "movement first"
    assert delivered.variant_comparison_caveat
    assert ws.edl.read_bytes() == edl_before
