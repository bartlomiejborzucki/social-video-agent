"""Regression coverage for social-export timestamps and split A/V rendering."""

from __future__ import annotations

import subprocess
from itertools import pairwise

import pytest

from social_video.edl.render import FINAL, PREVIEW, allocate_range_frames, render_edl
from social_video.ffmpeg.probe import probe
from social_video.ffmpeg.run import run_ffprobe_json
from social_video.pipeline import stage_qa
from social_video.qa.checks import check_render
from social_video.schemas.edl import EDL, EDLRange, VisualFillStrategy
from social_video.sources import build_manifest
from social_video.workspace.layout import Workspace
from tests.conftest import ffmpeg, make_video, requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


def audio_packets(path):
    data = run_ffprobe_json(
        [
            "-select_streams",
            "a:0",
            "-show_packets",
            "-show_entries",
            "packet=pts_time,duration_time",
            str(path),
        ],
        desc="test audio timestamps",
    )
    return [
        (float(packet["pts_time"]), float(packet.get("duration_time") or 0.0))
        for packet in data.get("packets", [])
        if packet.get("pts_time") is not None
    ]


def assert_timestamp_contract(path, edl):
    info = probe(path)
    assert info.video is not None
    assert info.video.nominal_frame_rate == "30/1"
    assert info.video.frame_rate == "30/1"
    expected_frames = sum(allocate_range_frames(edl, "30/1"))
    assert info.video.nb_frames == expected_frames
    expected_duration = expected_frames / 30
    assert info.duration == pytest.approx(expected_duration, abs=1 / 30)

    packets = audio_packets(path)
    pts = [timestamp for timestamp, _ in packets]
    assert all(right > left for left, right in pairwise(pts))
    deltas = sorted(right - left for left, right in pairwise(pts))
    assert deltas[len(deltas) // 2] == pytest.approx(1024 / 48000, abs=0.0001)
    audio_end = max(timestamp + duration for timestamp, duration in packets)
    audio_duration = audio_end - min(0.0, pts[0])
    assert audio_duration == pytest.approx(expected_duration, abs=2 * 1024 / 48000)

    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(path),
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


def test_eight_ranges_multiple_sources_have_exact_audio_and_video_timeline(tmp_path):
    mono = make_video(
        tmp_path / "phone mono.mp4",
        width=320,
        height=180,
        duration=2.2,
        audio_channels=1,
    )
    stereo = make_video(
        tmp_path / "phone stereo.mp4",
        width=180,
        height=320,
        duration=2.2,
        audio_channels=2,
    )
    silent = make_video(
        tmp_path / "source without audio.mp4",
        width=320,
        height=180,
        duration=2.2,
        audio=False,
    )
    manifest = build_manifest([mono, stereo, silent])
    ranges = [
        EDLRange(source="phone mono", start=0.05, end=0.31),
        EDLRange(source="phone stereo", start=0.10, end=0.39),
        EDLRange(source="source without audio", start=0.20, end=0.47),
        EDLRange(source="phone mono", start=0.50, end=0.83, speed=1.25),
        EDLRange(source="phone stereo", start=0.65, end=0.93, speed=0.8),
        EDLRange(source="phone mono", start=1.00, end=1.22, speed=2.0),
        EDLRange(source="source without audio", start=1.20, end=1.43),
        EDLRange(source="phone stereo", start=1.50, end=1.91),
    ]
    edl = EDL(
        output_width=320,
        output_height=568,
        ranges=ranges,
        normalize_audio=False,
    )
    output = tmp_path / "eight cuts.mp4"
    render_edl(edl, manifest, output, quality=PREVIEW)

    assert_timestamp_contract(output, edl)
    report = check_render(output, edl)
    assert report.status in {"passed", "passed_with_warnings"}, [
        check.message for check in report.errors
    ]
    for name in (
        "constant standard frame rate",
        "audio PTS monotonic",
        "AAC packet cadence",
        "audio timeline duration",
        "duration matches EDL",
        "full stream decode",
    ):
        assert next(check for check in report.checks if check.name == name).passed
    ending = next(check for check in report.checks if check.name == "ending visual continuity")
    assert ending.passed
    assert ending.measured is not None and ending.measured <= 1.0


def test_split_audio_only_source_freezes_at_privacy_boundary(tmp_path):
    picture = make_video(
        tmp_path / "Justyna i dziecko.mp4",
        width=320,
        height=180,
        duration=1.5,
        audio=False,
    )
    voice = tmp_path / "5.m4a"
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=660:sample_rate=48000:duration=2",
        "-c:a",
        "aac",
        str(voice),
    )
    manifest = build_manifest([picture, voice])
    edl = EDL(
        output_width=320,
        output_height=568,
        normalize_audio=False,
        ranges=[
            EDLRange(
                source="Justyna i dziecko",
                start=0,
                end=1.5,
                video_source="Justyna i dziecko",
                video_start=0,
                video_end=1.5,
                audio_source="5",
                audio_start=0,
                audio_end=2,
                freeze_at=0.8,
                freeze_duration=1.2,
                max_visual_source_time=0.8,
                hold_last_frame_until=2,
                visual_fill_strategy=VisualFillStrategy.FREEZE,
                intentional_hold=True,
                technical_reason="Freeze before the approved privacy stop while voice continues.",
            )
        ],
    )
    output = tmp_path / "split av.mp4"
    render_edl(edl, manifest, output, quality=PREVIEW)
    assert_timestamp_contract(output, edl)
    assert probe(output).duration == pytest.approx(2.0, abs=1 / 30)


def test_preview_and_final_profiles_keep_compatible_dimensions(tmp_path):
    source = make_video(tmp_path / "short.mp4", width=320, height=180, duration=0.7)
    manifest = build_manifest([source])
    edl = EDL(ranges=[EDLRange(source="short", start=0, end=0.5)])
    preview = tmp_path / "preview.mp4"
    final = tmp_path / "final.mp4"
    render_edl(edl, manifest, preview, quality=PREVIEW)
    render_edl(edl, manifest, final, quality=FINAL)

    assert probe(preview).video.display_size == (720, 1280)
    assert probe(final).video.display_size == (1080, 1920)
    assert_timestamp_contract(preview, edl)
    assert_timestamp_contract(final, edl)


def test_qa_rejects_audio_timeline_compressed_to_a_few_milliseconds(tmp_path):
    broken = tmp_path / "compressed-audio.mp4"
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=320x180:rate=30:duration=2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:duration=2",
        "-filter:a",
        "asetpts=PTS/20",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-ac",
        "2",
        str(broken),
    )
    report = check_render(broken)
    assert report.status == "failed"
    failed = {check.name for check in report.errors}
    assert "AAC packet cadence" in failed
    assert "audio timeline duration" in failed


def test_qa_blocks_unapproved_3_76_second_dead_frame(tmp_path):
    broken = tmp_path / "old automatic freeze.mp4"
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=320x180:rate=30:duration=7.10",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:duration=10.86",
        "-filter:v",
        "tpad=stop_mode=clone:stop_duration=3.76",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-t",
        "10.86",
        str(broken),
    )
    report = check_render(broken)
    ending = next(check for check in report.checks if check.name == "ending visual continuity")
    assert not ending.passed
    assert ending.measured == pytest.approx(3.75, abs=0.3)
    assert "not explicitly approved" in ending.message


def _make_split_ending_project(tmp_path, strategy):
    primary = make_video(tmp_path / "primary.mp4", width=320, height=180, duration=0.8, audio=False)
    voice = tmp_path / "voice.m4a"
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=550:sample_rate=48000:duration=1.4",
        "-c:a",
        "aac",
        str(voice),
    )
    fill = tmp_path / ("end-card.mp4" if strategy is VisualFillStrategy.END_CARD else "broll.mp4")
    source_filter = (
        "color=c=0x245060:s=320x180:r=30:d=0.7"
        if strategy is VisualFillStrategy.END_CARD
        else "testsrc2=size=320x180:rate=30:duration=0.7"
    )
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        source_filter,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(fill),
    )
    manifest = build_manifest([primary, voice, fill])
    kwargs = {
        "source": "primary",
        "start": 0,
        "end": 1.4,
        "video_end": 0.7,
        "audio_source": "voice",
        "audio_end": 1.4,
        "max_visual_source_time": 0.7,
        "visual_fill_strategy": strategy,
        "visual_fill_reason": "Approved safe visual ending.",
    }
    if strategy is VisualFillStrategy.END_CARD:
        kwargs.update(end_card_source="end-card", end_card_start=0, end_card_end=0.7)
    else:
        kwargs.update(
            secondary_video_source="broll",
            secondary_video_start=0,
            secondary_video_end=0.7,
        )
    edl = EDL(
        output_width=320,
        output_height=568,
        normalize_audio=False,
        ranges=[EDLRange(**kwargs)],
    )
    return manifest, edl


@pytest.mark.parametrize(
    "strategy", [VisualFillStrategy.SECONDARY_VIDEO, VisualFillStrategy.END_CARD]
)
def test_explicit_visual_fill_strategies_render_and_pass_qa(tmp_path, strategy):
    manifest, edl = _make_split_ending_project(tmp_path, strategy)
    output = tmp_path / f"{strategy.value}.mp4"
    render_edl(edl, manifest, output, quality=PREVIEW)
    report = check_render(output, edl)
    ending = next(check for check in report.checks if check.name == "ending visual continuity")
    assert ending.passed, ending.message
    assert not report.errors


def test_approved_long_hold_is_reported_and_gets_ending_contact_sheet(tmp_path):
    picture = make_video(tmp_path / "safe.mp4", width=320, height=180, duration=0.8, audio=False)
    voice = tmp_path / "voice.m4a"
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=330:sample_rate=48000:duration=2",
        "-c:a",
        "aac",
        str(voice),
    )
    manifest = build_manifest([picture, voice])
    edl = EDL(
        output_width=320,
        output_height=568,
        normalize_audio=False,
        ranges=[
            EDLRange(
                source="safe",
                start=0,
                end=2,
                video_end=0.7,
                audio_source="voice",
                audio_end=2,
                freeze_at=0.7,
                freeze_duration=1.3,
                max_visual_source_time=0.7,
                visual_fill_strategy=VisualFillStrategy.FREEZE,
                intentional_hold=True,
                visual_fill_reason="A deliberate still memorial ending approved by editor.",
            )
        ],
    )
    output = tmp_path / "approved-hold.mp4"
    render_edl(edl, manifest, output, quality=PREVIEW)
    workspace = Workspace.at(tmp_path / "edit").ensure()
    report = stage_qa(output, edl, workspace)
    ending = next(check for check in report.checks if check.name == "ending visual continuity")
    assert ending.passed and ending.accepted
    assert ending.measured is not None and ending.measured > 1.0
    artifacts = [str(path) for path in report.artifacts]
    assert any(path.endswith("ending-contact-sheet.png") for path in artifacts)
    assert all((workspace.qa / "qa-report.json").is_file() for _ in [0])


def test_preview_and_final_keep_same_explicit_ending_structure(tmp_path):
    manifest, edl = _make_split_ending_project(tmp_path, VisualFillStrategy.SECONDARY_VIDEO)
    preview = tmp_path / "ending-preview.mp4"
    final = tmp_path / "ending-final.mp4"
    render_edl(edl, manifest, preview, quality=PREVIEW)
    render_edl(edl, manifest, final, quality=FINAL)
    preview_check = next(
        check
        for check in check_render(preview, edl).checks
        if check.name == "ending visual continuity"
    )
    final_check = next(
        check
        for check in check_render(final, edl).checks
        if check.name == "ending visual continuity"
    )
    assert preview_check.passed and final_check.passed
    assert probe(preview).duration == pytest.approx(probe(final).duration, abs=1 / 30)


def test_no_frame_after_privacy_stop_can_reach_output(tmp_path):
    primary = tmp_path / "privacy.mp4"
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=c=red:s=320x180:r=30:d=0.7",
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=320x180:r=30:d=0.7",
        "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map",
        "[v]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(primary),
    )
    fill = tmp_path / "safe-green.mp4"
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=c=green:s=320x180:r=30:d=0.7",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(fill),
    )
    voice = tmp_path / "privacy-voice.m4a"
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:duration=1.4",
        "-c:a",
        "aac",
        str(voice),
    )
    manifest = build_manifest([primary, fill, voice])
    edl = EDL(
        output_width=320,
        output_height=568,
        normalize_audio=False,
        ranges=[
            EDLRange(
                source="privacy",
                start=0,
                end=1.4,
                video_end=1.4,
                audio_source="privacy-voice",
                audio_end=1.4,
                max_visual_source_time=0.7,
                visual_fill_strategy=VisualFillStrategy.SECONDARY_VIDEO,
                secondary_video_source="safe-green",
                secondary_video_start=0,
                secondary_video_end=0.7,
                visual_fill_reason="Switch to approved B-roll at the privacy stop.",
            )
        ],
    )
    output = tmp_path / "privacy-result.mp4"
    render_edl(edl, manifest, output, quality=PREVIEW)

    for timestamp in (0.72, 0.85, 1.0, 1.2):
        proc = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                str(timestamp),
                "-i",
                str(output),
                "-frames:v",
                "1",
                "-vf",
                "scale=1:1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-",
            ],
            check=True,
            capture_output=True,
        )
        red, green, blue = proc.stdout[:3]
        assert blue <= max(red, green), (timestamp, red, green, blue)
