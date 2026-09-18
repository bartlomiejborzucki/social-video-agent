"""Cover, publishing metadata and platform checks on the FFmpeg-only route."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from social_video.cover import CoverStyle, compose_cover, extract_frame
from social_video.delivery import deliver_workspace
from social_video.errors import ValidationError
from social_video.pipeline import stage_qa, stage_render
from social_video.schemas.base import save_artifact
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.publish import PublishMetadata
from social_video.sources import build_manifest
from social_video.workspace.layout import Workspace
from tests.conftest import make_video, requires_ffmpeg


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
