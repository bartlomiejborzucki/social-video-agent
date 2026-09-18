"""Tests for source<->output time mapping.

Getting this wrong is what makes captions drift further out of sync with every
cut, so the interval mapping across a splice is tested explicitly.
"""

from __future__ import annotations

import pytest

from social_video.edl.timeline import Timeline
from social_video.schemas.edl import EDL, EDLRange


def edl_with(*ranges: tuple[float, float], speed: float = 1.0) -> EDL:
    return EDL(ranges=[EDLRange(source="a", start=s, end=e, speed=speed) for s, e in ranges])


class TestTimeline:
    def test_single_range_starts_at_zero(self):
        tl = Timeline(edl_with((10.0, 15.0)))
        assert tl.duration == pytest.approx(5.0)
        assert tl.slices[0].output_start == 0.0

    def test_ranges_are_laid_end_to_end(self):
        tl = Timeline(edl_with((10.0, 12.0), (30.0, 33.0)))
        assert tl.duration == pytest.approx(5.0)
        assert tl.slices[1].output_start == pytest.approx(2.0)

    def test_cut_boundaries_exclude_the_start(self):
        tl = Timeline(edl_with((0.0, 2.0), (5.0, 7.0), (9.0, 10.0)))
        assert tl.cut_boundaries() == pytest.approx([2.0, 4.0])

    def test_maps_source_time_into_output(self):
        tl = Timeline(edl_with((10.0, 12.0), (30.0, 33.0)))
        # 31s of source is 1s into the second range, which starts at output 2s.
        assert tl.map_to_output("a", 31.0) == pytest.approx([3.0])

    def test_removed_material_maps_nowhere(self):
        tl = Timeline(edl_with((10.0, 12.0), (30.0, 33.0)))
        assert tl.map_to_output("a", 20.0) == []

    def test_material_used_twice_maps_twice(self):
        tl = Timeline(edl_with((0.0, 5.0), (0.0, 5.0)))
        assert tl.map_to_output("a", 1.0) == pytest.approx([1.0, 6.0])

    def test_interval_straddling_a_cut_is_split(self):
        # A word spanning 11.5-30.5 survives only as its two kept halves.
        tl = Timeline(edl_with((10.0, 12.0), (30.0, 33.0)))
        pieces = tl.map_interval("a", 11.5, 30.5)
        assert len(pieces) == 2
        assert pieces[0] == pytest.approx((1.5, 2.0))
        assert pieces[1] == pytest.approx((2.0, 2.5))

    def test_interval_entirely_cut_yields_nothing(self):
        tl = Timeline(edl_with((10.0, 12.0), (30.0, 33.0)))
        assert tl.map_interval("a", 20.0, 25.0) == []

    def test_other_sources_are_ignored(self):
        tl = Timeline(edl_with((0.0, 5.0)))
        assert tl.map_interval("b", 1.0, 2.0) == []

    def test_speed_change_compresses_output_time(self):
        tl = Timeline(edl_with((0.0, 10.0), speed=2.0))
        assert tl.duration == pytest.approx(5.0)
        assert tl.map_to_output("a", 10.0) == pytest.approx([5.0])

    def test_round_trip_source_to_output_and_back(self):
        tl = Timeline(edl_with((10.0, 12.0), (30.0, 33.0)))
        sl = tl.slices[1]
        assert sl.to_source(sl.to_output(31.0)) == pytest.approx(31.0)


def test_frame_padding_is_expressed_in_frames_not_seconds() -> None:
    """A duration of "0.033333333" is under 1/30, and ffmpeg floors the pad.

    Ranges needing exactly one cloned frame silently got none, so the output
    came out short of its own EDL by one frame per affected cut. Padding is
    counted in frames so no rate can round it away.
    """
    from pathlib import Path

    from social_video.edl.render import RenderRange, build_filtergraph
    from social_video.ffmpeg.probe import MediaInfo, VideoStream
    from social_video.schemas.edl import EDL, EDLRange

    video = VideoStream(
        index=0,
        codec="h264",
        width=320,
        height=180,
        rotation=0,
        frame_rate="30/1",
        nominal_frame_rate="30/1",
        pix_fmt="yuv420p",
        color_transfer="",
        nb_frames=66,
        duration=2.2,
        time_base="1/15360",
    )
    info = MediaInfo(
        path=Path("talk.mp4"),
        duration=2.2,
        size_bytes=1,
        format_name="mp4",
        video=video,
        audio=(),
    )
    # 0.27s of source is 8.1 frames at 30 fps, but the range owns 9 frames of
    # output: exactly the case that needs one cloned frame.
    edl = EDL(ranges=[EDLRange(source="talk", start=0.20, end=0.47)])
    ranges = [
        RenderRange(
            video_input=0,
            audio_input=None,
            video_info=info,
            audio_info=info,
            fill_input=None,
            fill_info=None,
            target_frames=9,
            target_duration=9 / 30,
        )
    ]
    graph, _, _ = build_filtergraph(
        edl, ranges, canvas=(320, 568), fps="30/1", caption_file=None, loudnorm=None
    )
    assert "stop_duration" not in graph
    assert "tpad=stop_mode=clone:stop=1" in graph
