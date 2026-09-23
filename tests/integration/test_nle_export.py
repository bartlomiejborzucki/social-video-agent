"""Every exported timeline reads back, through an independent reader, as the cut.

OpenTimelineIO and its adapters parse each format; the test compares what they
see with the renderer's own frame allocation, so a cut lands on the same frame
in an NLE as in the rendered file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from social_video.edl.render import allocate_range_frames
from social_video.export import build_export_timeline, write_export
from social_video.schemas.edl import EDL, EDLRange, ReframeMode, ReframePlan
from social_video.sources import build_manifest
from tests.conftest import make_video, requires_ffmpeg

otio = pytest.importorskip("opentimelineio")

pytestmark = [pytest.mark.integration, requires_ffmpeg]


@pytest.fixture
def exported(tmp_path: Path):
    interview = make_video(tmp_path / "Wywiad z Markiem.mp4", width=640, height=360, duration=4)
    broll = make_video(tmp_path / "b-roll.mp4", width=640, height=360, duration=3, audio=False)
    edl = EDL(
        output_width=1080,
        output_height=1920,
        ranges=[
            EDLRange(source="Wywiad z Markiem", start=0.5, end=1.5, reason="the hook"),
            # Picture from the B-roll, sound still from the interview.
            EDLRange(
                source="Wywiad z Markiem",
                start=2.0,
                end=3.0,
                video_source="b-roll",
                video_start=0.0,
                video_end=1.0,
                reason="cover the jump",
            ),
            EDLRange(
                source="Wywiad z Markiem",
                start=3.0,
                end=3.8,
                reframe=ReframePlan(mode=ReframeMode.CENTER, crop_width=202, crop_height=360,
                                    keyframes=[{"t": 0, "x": 219, "y": 0}]),
                zoom=1.1,
            ),
        ],
    )  # fmt: skip
    manifest = build_manifest([interview, broll])
    timeline = build_export_timeline(edl, manifest)
    paths = {fmt: write_export(timeline, fmt, tmp_path / "exports") for fmt in
             ("otio", "edl", "fcpxml", "xmeml")}  # fmt: skip
    return edl, timeline, paths


def _read(path: Path, fmt: str):
    if fmt == "edl":
        return otio.adapters.read_from_file(str(path), adapter_name="cmx_3600", rate=30)
    adapter = {"otio": "otio_json", "fcpxml": "fcpx_xml", "xmeml": "fcp_xml"}[fmt]
    return otio.adapters.read_from_file(str(path), adapter_name=adapter)


@pytest.mark.parametrize("fmt", ["otio", "edl", "fcpxml", "xmeml"])
def test_the_picture_track_reads_back_frame_for_frame(exported, fmt: str) -> None:
    edl, _, paths = exported
    read = _read(paths[fmt], fmt)
    if isinstance(read, otio.schema.SerializableCollection):
        read = next(iter(read.find_children(descended_from_type=otio.schema.Timeline)))

    # The FCPXML reader lists a connected sound clip's lane as a track of its
    # own; the picture is the track carrying the whole cut.
    picture = max(read.video_tracks(), key=lambda track: len(list(track.find_clips())))
    clips = list(picture.find_clips())
    expected = allocate_range_frames(edl, "30/1")

    assert [clip.name for clip in clips] == [
        "Wywiad z Markiem.mp4",
        "b-roll.mp4",
        "Wywiad z Markiem.mp4",
    ]
    assert [round(clip.source_range.duration.to_frames()) for clip in clips] == expected
    assert [round(clip.source_range.start_time.to_frames()) for clip in clips] == [15, 0, 90]
    record = [round(clip.range_in_parent().start_time.to_frames()) for clip in clips]
    assert record == [0, expected[0], expected[0] + expected[1]]


def test_split_sound_keeps_the_interview_under_the_b_roll(exported) -> None:
    _, _, paths = exported
    read = _read(paths["otio"], "otio")

    audio = list(read.audio_tracks()[0].find_clips())
    assert [clip.name for clip in audio] == ["Wywiad z Markiem.mp4"] * 3
    assert round(audio[1].source_range.start_time.to_frames()) == 60


@pytest.mark.parametrize("fmt", ["otio", "fcpxml", "xmeml"])
def test_media_references_point_at_the_real_files(exported, fmt: str) -> None:
    _, _, paths = exported
    read = _read(paths[fmt], fmt)

    for clip in read.find_clips():
        url = clip.media_reference.target_url
        assert url.startswith("file://")
        assert Path(url.removeprefix("file://").replace("%20", " ")).is_file()


def test_what_cannot_travel_is_named(exported) -> None:
    _, timeline, _ = exported

    assert any("range 3: center framing" in note for note in timeline.notes)
    assert any("range 3: punch-in to 1.1" in note for note in timeline.notes)


def test_the_cli_writes_every_format_into_the_workspace(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from social_video.cli import app
    from social_video.schemas.base import save_artifact
    from social_video.workspace.layout import Workspace

    source = make_video(tmp_path / "clip.mp4", duration=2)
    workspace = Workspace.at(tmp_path / "edit")
    workspace.ensure()
    save_artifact(build_manifest([source]), workspace.source_manifest)
    save_artifact(EDL(ranges=[EDLRange(source="clip", start=0.2, end=1.2)]), workspace.edl)

    result = CliRunner().invoke(app, ["export", str(workspace.root), "--json"])

    assert result.exit_code == 0, result.output
    names = sorted(p.name for p in workspace.exports.iterdir())
    assert names == ["main.edl", "main.fcpxml", "main.otio", "main.xml"]
