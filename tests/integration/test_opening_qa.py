"""2.1 on real renders: a September opening is refused, an October one is ready."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from social_video.captions.ass import write_ass
from social_video.cover import CoverStyle, compose_cover
from social_video.delivery import deliver_workspace, validate_delivery_manifest
from social_video.editorial.brief import load_brief
from social_video.edl.render import PREVIEW, render_edl
from social_video.errors import ValidationError
from social_video.pipeline import stage_render
from social_video.project_config import apply_contract_to_edl
from social_video.qa.opening import check_opening, leading_silence
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.brand import CaptionStyle
from social_video.schemas.captions import CaptionCue, CaptionTrack
from social_video.schemas.config import BrandContract, OpeningPolicy
from social_video.schemas.delivery import DeliveryManifest
from social_video.schemas.edl import EDL, EDLRange, Overlay
from social_video.schemas.workflow import Renderer
from social_video.sources import build_manifest
from social_video.workflow import create_workflow
from social_video.workspace.layout import Workspace
from tests.conftest import ffmpeg, make_video, requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]
W, H = 360, 640
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "brief-2026-10-13.txt"
FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def _cover_png(path: Path) -> Path:
    ffmpeg("-f", "lavfi", "-i", f"testsrc=size={W}x{H}:rate=1:duration=1", "-frames:v", "1",
           str(path))  # fmt: skip
    return path


def _cover_clip(path: Path) -> Path:
    """The September pattern: the cover image exported as a one-second clip."""
    still = _cover_png(path.with_suffix(".png"))
    ffmpeg("-loop", "1", "-i", str(still), "-t", "1", "-r", "30", "-c:v", "libx264",
           "-pix_fmt", "yuv420p", str(path))  # fmt: skip
    return path


def test_a_september_opening_with_a_cover_in_the_timeline_is_refused(tmp_path: Path) -> None:
    """The brief's own pattern, before 2.1: cover pasted at 0-1 s, captions late."""
    source = make_video(tmp_path / "ubieranie.mp4", width=W, height=H, duration=4.0)
    cover = _cover_clip(tmp_path / "okladka.mp4")
    edl = EDL(
        output_width=W, output_height=H, output_fps="30",
        ranges=[EDLRange(source="ubieranie", start=0, end=4.0)],
        overlays=[Overlay(file=str(cover), start_in_output=0.0, duration=1.0, x="0", y="0",
                          scale_width=W)],
    )  # fmt: skip
    output = tmp_path / "wrzesien.mp4"
    render_edl(edl, build_manifest([source]), output, quality=PREVIEW)
    late = CaptionTrack(
        cues=[CaptionCue(index=1, start=1.5, end=2.5, text="Dziesięć stopni rano,")]
    )

    report = check_opening(output, edl, None, late, OpeningPolicy(), analysis_dir=tmp_path / "a")

    assert not report.ready
    assert report.cover_in_timeline is True
    assert report.first_frame_is_content is False
    assert "does not move" in report.first_frame_note
    assert report.first_cue_start_s == 1.5
    assert any("cover.jpg" in issue for issue in report.issues)
    assert report.variant.startswith("Variant:")
    assert (
        (tmp_path / "a" / "opening-qa.md")
        .read_text(encoding="utf-8")
        .startswith("# Opening QA: NOT ready")
    )
    assert (tmp_path / "a" / "first-frame.png").is_file()


def test_a_silent_start_is_measured(tmp_path: Path) -> None:
    clip = tmp_path / "cisza.mp4"
    ffmpeg(
        "-f", "lavfi", "-i", f"testsrc=size={W}x{H}:rate=30:duration=3",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=1",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-filter_complex", "[1:a][2:a]concat=n=2:v=0:a=1[a]", "-map", "0:v", "-map", "[a]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip),
    )  # fmt: skip

    assert leading_silence(clip) == pytest.approx(1.0, abs=0.08)
    assert leading_silence(make_video(tmp_path / "ton.mp4", width=W, height=H)) == 0.0


@pytest.mark.skipif(not FONT.is_file(), reason="deterministic test font is unavailable")
def test_an_october_edit_renders_content_first_and_delivers_ready(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "assets").mkdir(parents=True)
    shutil.copy2(FONT, project / "assets" / "Lato.ttf")
    (project / ".social-video").mkdir()
    (project / ".social-video/config.yaml").write_text(
        "schema_version: 1\nbrand_name: Co robić, kiedy dziecko\nfont: Lato\n"
        'font_file: assets/Lato.ttf\nbrand_colors: ["#28BCA5", "#394463"]\n'
        f'default_resolution: "{W * 3}x{H * 3}"\ndefault_fps_policy: "30"\n',
        encoding="utf-8",
    )
    source = make_video(project / "rolka.mp4", width=W, height=H, duration=3.0)
    ws = Workspace.at(project / "edit")
    create_workflow([source], ws, project_root=project, renderer=Renderer.FFMPEG)
    contract = load_artifact(BrandContract, ws.brand_contract)
    assert contract.opening.opening_policy == "content_first"
    manifest = build_manifest([source])
    save_artifact(manifest, ws.source_manifest)
    save_artifact(load_brief(FIXTURE), ws.brief)
    track = CaptionTrack(cues=[CaptionCue(index=1, start=0.0, end=2.4, text="Mamo, pobaw się")])
    save_artifact(track, ws.captions / "main.json")
    style = CaptionStyle(font_family="Lato")
    ass = write_ass(track, style, ws.captions / "main.ass", width=W * 3, height=H * 3)
    edl = apply_contract_to_edl(
        EDL(ranges=[EDLRange(source=manifest.ids[0], start=0, end=2.5)], captions=str(ass)),
        contract,
    )
    save_artifact(edl, ws.edl)
    carded = edl.model_copy(
        update={
            "overlays": [
                Overlay(
                    file=str(_cover_png(tmp_path / "okladka.png")),
                    start_in_output=0.0,
                    duration=1.0,
                )
            ]
        }
    )

    with pytest.raises(ValidationError, match="must open on the scene"):
        stage_render(carded, manifest, ws, quality="final", captions=ass)
    final = stage_render(edl, manifest, ws, quality="final", captions=ass)
    frame = tmp_path / "frame.png"
    ffmpeg("-ss", "1", "-i", str(final), "-frames:v", "1", str(frame))
    brief = load_brief(FIXTURE)
    compose_cover(ws.cover, title=brief.cover_title, subtitle=brief.cover_subtitle,
                  style=CoverStyle.from_contract(contract), frame=frame)  # fmt: skip
    delivered = deliver_workspace(
        ws, tmp_path / "delivery", with_captions=True, no_captions=False, srt=False, vtt=False,
        poster=False, allow_temporary=True, first_frame_note="Pattern moving, captions at 0 s.",
    )  # fmt: skip

    assert delivered.opening_ready is True and delivered.opening_issues == []
    assert delivered.first_frame_is_content is True
    assert delivered.first_frame_note == "Pattern moving, captions at 0 s."
    assert delivered.first_cue_start_s == 0.0
    assert delivered.cover_in_timeline is False and delivered.end_card_only_at_end is True
    assert delivered.cover_path and Path(delivered.cover_path).name == "cover.jpg"
    assert delivered.leading_silence_s == 0.0
    assert delivered.reel_check and "/" in delivered.reel_check, "advisory, recorded"
    assert (ws.analysis / "reel-check.md").is_file()
    on_disk = load_artifact(DeliveryManifest, tmp_path / "delivery" / "delivery-manifest.json")
    validate_delivery_manifest(on_disk)
    assert ws.opening_qa.is_file()
