"""Cover, publishing metadata and platform checks on the FFmpeg-only route."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from social_video.cover import CoverStyle, compose_cover, extract_frame
from social_video.delivery import deliver_workspace, delivery_name, final_name, posting_notes
from social_video.errors import ValidationError
from social_video.pipeline import stage_qa, stage_render
from social_video.schemas.base import save_artifact
from social_video.schemas.delivery import DeliveryItem
from social_video.schemas.edl import EDL, AudioBed, EDLRange
from social_video.schemas.publish import PublishMetadata
from social_video.sources import build_manifest
from social_video.workspace.layout import Workspace
from tests.conftest import ffmpeg, make_video, requires_ffmpeg


@pytest.mark.integration
@pytest.mark.slow
@requires_ffmpeg
def test_cover_publish_and_platform_checks_reach_the_delivery_manifest(tmp_path: Path) -> None:
    project = tmp_path / "project"
    # Over the three-second minimum Reels enforces, so delivery QA can pass.
    source = make_video(project / "media" / "talk.mp4", width=1280, height=720, duration=5.0)
    workspace = Workspace.at(project / "edit").ensure()
    manifest = build_manifest([source])
    save_artifact(manifest, workspace.source_manifest)
    edl = EDL(
        name="main",
        output_width=1080,
        output_height=1920,
        ranges=[EDLRange(source=manifest.ids[0], start=0.0, end=4.0)],
    )
    save_artifact(edl, workspace.edl)
    final = stage_render(edl, manifest, workspace, quality="final")

    report = stage_qa(final, edl, workspace, platforms=["reels"])
    names = {check.name for check in report.checks}
    assert "opens on an image" in names
    assert "reels duration limit" in names
    assert "reels aspect ratio" in names
    assert (workspace.qa / "opening-contact-sheet.png").is_file()

    frame = extract_frame(final, 0.5, workspace.cache / "cover-frame.jpg")
    design = compose_cover(
        workspace.cover,
        title="Zażółć gęślą jaźń",
        subtitle="Odcinek testowy",
        style=CoverStyle(),
        frame=frame,
        frame_at=0.5,
    )
    save_artifact(design, workspace.cover_design)
    save_artifact(
        PublishMetadata(
            platform="reels",
            language="pl",
            title="Zażółć gęślą jaźń",
            description="Krótki test dostawy.",
            hashtags=["montaż", "#test"],
            alt_text="Plansza testowa z napisem.",
        ),
        workspace.publish_metadata,
    )

    delivered = deliver_workspace(
        workspace,
        project / "delivery",
        with_captions=True,
        no_captions=False,
        srt=False,
        vtt=False,
        poster=False,
        cover=True,
        publish=True,
        platforms=["reels"],
        allow_temporary=True,
    )
    kinds = {item.kind for item in delivered.items}
    assert {"video", "cover", "publish_metadata"} <= kinds
    for item in delivered.items:
        path = Path(item.path)
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item.sha256


@pytest.mark.integration
@requires_ffmpeg
def test_delivering_a_cover_that_was_never_composed_names_the_command(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source = make_video(project / "media" / "talk.mp4", duration=1.0)
    workspace = Workspace.at(project / "edit").ensure()
    manifest = build_manifest([source])
    save_artifact(manifest, workspace.source_manifest)
    edl = EDL(name="main", ranges=[EDLRange(source=manifest.ids[0], start=0.0, end=0.8)])
    save_artifact(edl, workspace.edl)
    stage_render(edl, manifest, workspace, quality="final")

    with pytest.raises(ValidationError, match="social-video-agent cover"):
        deliver_workspace(
            workspace,
            project / "delivery",
            with_captions=False,
            no_captions=False,
            srt=False,
            vtt=False,
            poster=False,
            cover=True,
            allow_temporary=True,
        )


def _delivered(tmp_path: Path, *, bed: bool, **options):
    project = tmp_path / "project"
    source = make_video(project / "media" / "kamera.mp4", duration=4.0)
    workspace = Workspace.at(project / "edit").ensure()
    manifest = build_manifest([source])
    save_artifact(manifest, workspace.source_manifest)
    music = None
    if bed:
        track = project / "audio" / "podklad.m4a"
        track.parent.mkdir(parents=True)
        ffmpeg("-f", "lavfi", "-i", "sine=frequency=330:duration=6", "-c:a", "aac", str(track))
        music = AudioBed(path=str(track), gain_db=-12.0, reason="Podkład pod całą rolkę.")
    edl = EDL(
        name="main", ranges=[EDLRange(source=manifest.ids[0], start=0.0, end=3.5)], audio_bed=music
    )
    save_artifact(edl, workspace.edl)
    stage_render(edl, manifest, workspace, quality="final")
    before = workspace.edl.read_bytes()
    delivered = deliver_workspace(
        workspace, project / "delivery", with_captions=True, no_captions=False, srt=False,
        vtt=False, poster=False, allow_temporary=True, **options,
    )  # fmt: skip
    assert workspace.edl.read_bytes() == before, "a variant never changes the edit"
    return delivered, project / "delivery"


@pytest.mark.integration
@pytest.mark.slow
@requires_ffmpeg
def test_an_edit_with_a_bed_is_delivered_with_and_without_its_music(tmp_path: Path) -> None:
    from social_video.ffmpeg.probe import probe
    from social_video.motion.hook_variants import audio_sha256

    delivered, folder = _delivered(tmp_path, bed=True)

    videos = sorted(Path(i.path).name for i in delivered.items if i.kind == "video")
    assert videos == ["kamera-FINAL-no-music.mp4", "kamera-FINAL.mp4"]
    with_music, without = folder / "kamera-FINAL.mp4", folder / "kamera-FINAL-no-music.mp4"
    assert audio_sha256(with_music) != audio_sha256(without)
    assert probe(with_music).duration == pytest.approx(probe(without).duration, abs=0.05)
    assert all(i.qa_status.startswith("passed") for i in delivered.items if i.kind == "video")
    reels, others, commercial = delivered.posting_notes
    assert "Reels" in reels and "kamera-FINAL-no-music.mp4" in reels
    assert "TikTok" in others and "Shorts" in others and "kamera-FINAL.mp4" in others
    assert "not licensed" in commercial


@pytest.mark.integration
@requires_ffmpeg
def test_one_audio_delivers_the_approved_mix_alone_under_the_name_asked_for(
    tmp_path: Path,
) -> None:
    delivered, folder = _delivered(
        tmp_path, bed=True, music_variants=False, name="Rolka 12: trzy błędy"
    )

    videos = [Path(i.path).name for i in delivered.items if i.kind == "video"]
    assert videos == ["Rolka-12-trzy-błędy-FINAL.mp4"]
    assert (folder / "Rolka-12-trzy-błędy-FINAL.qa.json").is_file()
    assert "not asked for" in delivered.posting_notes[0]


@pytest.mark.integration
@requires_ffmpeg
def test_an_edit_without_a_bed_has_one_final_and_says_it_has_no_music(tmp_path: Path) -> None:
    delivered, _folder = _delivered(tmp_path, bed=False)

    videos = [Path(i.path).name for i in delivered.items if i.kind == "video"]
    assert videos == ["kamera-FINAL.mp4"]
    assert "has no music" in delivered.posting_notes[0]
    assert "not licensed" in delivered.posting_notes[-1]


def test_a_delivery_is_named_after_what_was_asked_then_the_edit_then_the_recording(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    sources = SimpleNamespace(sources=[SimpleNamespace(id="kamera")])
    unnamed = EDL(ranges=[EDLRange(source="kamera", start=0, end=1)])
    named = EDL(name="odcinek-7", ranges=[EDLRange(source="kamera", start=0, end=1)])

    assert delivery_name(unnamed, sources) == "kamera"
    assert delivery_name(named, sources) == "odcinek-7"
    assert delivery_name(named, sources, " Jak zacząć? / część 2 ") == "Jak-zacząć-część-2"
    assert delivery_name(unnamed, SimpleNamespace(sources=[])) == "video"
    with pytest.raises(ValidationError, match="nothing usable"):
        delivery_name(unnamed, sources, "///")
    assert final_name("kamera") == "kamera-FINAL.mp4"
    assert final_name("kamera", "1080x1350") == "kamera-FINAL-1080x1350.mp4"


def test_posting_notes_are_only_written_for_a_delivered_main_video(tmp_path: Path) -> None:
    main = tmp_path / "kamera-FINAL.mp4"
    sidecar = DeliveryItem(
        kind="captions", path=str(tmp_path / "captions.srt"), size_bytes=1, format="srt",
        sha256="0" * 64, qa_status="not_applicable",
    )  # fmt: skip

    assert posting_notes([sidecar], main, has_bed=True) == []
