"""End-to-end tests against real ffmpeg and real generated media.

These are the tests that catch what unit tests cannot: whether the filter graph
we build actually runs, whether the rendered duration matches the EDL, whether
rotation and frame rate survive the round trip.
"""

from __future__ import annotations

import pytest

from social_video.edl.render import DRAFT, render_edl
from social_video.ffmpeg.probe import clear_probe_cache, probe
from social_video.qa.checks import check_render
from social_video.schemas.captions import CaptionCue, CaptionTrack
from social_video.schemas.edl import (
    EDL,
    CropKeyframe,
    EDLRange,
    ReframeMode,
    ReframePlan,
)
from social_video.sources import build_manifest
from tests.conftest import (
    make_multitrack_video,
    make_silent_video,
    make_video,
    requires_ffmpeg,
)

pytestmark = [pytest.mark.integration, requires_ffmpeg]


class TestProbe:
    def test_reads_geometry_and_streams(self, landscape):
        info = probe(landscape)
        assert info.video.display_size == (1280, 720)
        assert not info.video.is_portrait
        assert info.has_audio
        assert info.duration == pytest.approx(3.0, abs=0.2)

    def test_detects_portrait(self, portrait):
        assert probe(portrait).video.is_portrait

    def test_preserves_60fps(self, sixty_fps):
        assert probe(sixty_fps).video.fps_float == pytest.approx(60.0, abs=0.5)

    def test_reports_absent_audio(self, no_audio):
        assert not probe(no_audio).has_audio

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            probe(tmp_path / "nope.mp4")

    def test_cache_invalidates_when_the_file_changes(self, tmp_path):
        path = make_video(tmp_path / "v.mp4", width=640, height=360, duration=1.0)
        assert probe(path).video.width == 640
        clear_probe_cache()
        make_video(path, width=320, height=240, duration=1.0)
        assert probe(path).video.width == 320

    def test_counts_multiple_audio_tracks(self, tmp_path):
        path = make_multitrack_video(tmp_path / "obs.mp4")
        assert len(probe(path).audio) == 2


class TestRender:
    def _manifest_and_edl(self, source, **edl_kwargs):
        manifest = build_manifest([source])
        sid = manifest.ids[0]
        ranges = edl_kwargs.pop("ranges", None) or [
            EDLRange(source=sid, start=0.2, end=1.0),
            EDLRange(source=sid, start=1.8, end=2.6),
        ]
        return manifest, EDL(ranges=ranges, **edl_kwargs)

    def test_renders_and_duration_matches_the_edl(self, landscape, tmp_path):
        manifest, edl = self._manifest_and_edl(landscape)
        out = tmp_path / "out.mp4"
        render_edl(edl, manifest, out, quality=DRAFT)
        assert out.is_file()
        assert probe(out).duration == pytest.approx(edl.total_duration, abs=0.15)

    def test_produces_a_vertical_canvas_from_landscape_source(self, landscape, tmp_path):
        manifest, edl = self._manifest_and_edl(landscape, output_width=1080, output_height=1920)
        out = tmp_path / "vertical.mp4"
        manifest_out = render_edl(edl, manifest, out, quality=DRAFT)
        rendered = probe(out)
        assert rendered.video.is_portrait
        # Draft scales the canvas down but must not change the aspect ratio.
        assert rendered.video.display_size[0] / rendered.video.display_size[1] == (
            pytest.approx(1080 / 1920, abs=0.01)
        )
        assert manifest_out.width / manifest_out.height == pytest.approx(1080 / 1920, abs=0.01)

    def test_mixed_orientation_sources_concatenate(self, landscape, portrait, tmp_path):
        # Upstream stream-copies segments of differing resolution, which yields a
        # file whose later half will not decode. Every range is scaled onto one
        # canvas before the concat here.
        manifest = build_manifest([landscape, portrait])
        edl = EDL(
            output_width=1080,
            output_height=1920,
            ranges=[
                EDLRange(source="landscape", start=0.0, end=1.0),
                EDLRange(source="portrait", start=0.0, end=1.0),
            ],
        )
        out = tmp_path / "mixed.mp4"
        render_edl(edl, manifest, out, quality=DRAFT)
        assert probe(out).duration == pytest.approx(2.0, abs=0.2)

    def test_source_frame_rate_is_preserved_by_default(self, sixty_fps, tmp_path):
        manifest, edl = self._manifest_and_edl(
            sixty_fps, ranges=[EDLRange(source="60fps", start=0.0, end=1.5)]
        )
        out = tmp_path / "sixty.mp4"
        result = render_edl(edl, manifest, out, quality=DRAFT)
        assert result.frame_rate.startswith("60")
        assert result.frame_rate_converted_from is None

    def test_explicit_fps_override_is_recorded(self, sixty_fps, tmp_path):
        manifest, edl = self._manifest_and_edl(
            sixty_fps,
            ranges=[EDLRange(source="60fps", start=0.0, end=1.5)],
            output_fps="30/1",
        )
        result = render_edl(edl, manifest, out := tmp_path / "thirty.mp4", quality=DRAFT)
        assert out.is_file()
        assert result.frame_rate == "30/1"
        # A conversion happened, and the manifest says what it came from.
        assert result.frame_rate_converted_from is not None

    def test_source_is_never_modified(self, landscape, tmp_path):
        before = landscape.read_bytes()
        manifest, edl = self._manifest_and_edl(landscape)
        render_edl(edl, manifest, tmp_path / "out.mp4", quality=DRAFT)
        assert landscape.read_bytes() == before

    def test_renders_deterministically_twice(self, landscape, tmp_path):
        manifest, edl = self._manifest_and_edl(landscape)
        a = render_edl(edl, manifest, tmp_path / "a.mp4", quality=DRAFT)
        b = render_edl(edl, manifest, tmp_path / "b.mp4", quality=DRAFT)
        assert a.duration == pytest.approx(b.duration, abs=0.05)
        assert (a.width, a.height) == (b.width, b.height)

    def test_source_without_audio_still_renders(self, no_audio, tmp_path):
        manifest, edl = self._manifest_and_edl(
            no_audio, ranges=[EDLRange(source="silent", start=0.0, end=1.0)]
        )
        out = tmp_path / "quiet.mp4"
        render_edl(edl, manifest, out, quality=DRAFT)
        # A silent range still needs an audio stream or the concat filter fails.
        assert probe(out).has_audio

    def test_animated_crop_runs(self, landscape, tmp_path):
        manifest = build_manifest([landscape])
        plan = ReframePlan(
            mode=ReframeMode.FACE,
            crop_width=404,
            crop_height=720,
            keyframes=[
                CropKeyframe(t=0.0, x=0, y=0),
                CropKeyframe(t=0.5, x=400, y=0),
                CropKeyframe(t=1.0, x=800, y=0),
            ],
            reason="test",
        )
        edl = EDL(
            output_width=1080,
            output_height=1920,
            ranges=[EDLRange(source="landscape", start=0.0, end=1.5, reframe=plan)],
        )
        out = tmp_path / "tracked.mp4"
        render_edl(edl, manifest, out, quality=DRAFT)
        assert probe(out).duration == pytest.approx(1.5, abs=0.2)


class TestCaptionBurnIn:
    def test_polish_captions_render(self, landscape, tmp_path):
        from social_video.captions.ass import write_ass
        from social_video.ffmpeg.fonts import default_caption_font
        from social_video.schemas.brand import CaptionStyle

        track = CaptionTrack(
            language="pl",
            cues=[CaptionCue(index=1, start=0.1, end=1.4, text="Zażółć gęślą jaźń")],
        )
        font = default_caption_font()
        ass = write_ass(
            track,
            CaptionStyle(),
            tmp_path / "pl.ass",
            width=1080,
            height=1920,
            font_name=font.family if font else None,
        )
        assert "Zażółć gęślą jaźń" in ass.read_text(encoding="utf-8")

        manifest = build_manifest([landscape])
        edl = EDL(
            output_width=1080,
            output_height=1920,
            ranges=[EDLRange(source="landscape", start=0.0, end=1.5)],
        )
        out = tmp_path / "captioned.mp4"
        render_edl(edl, manifest, out, quality=DRAFT, caption_file=ass)
        assert out.is_file()

    def test_caption_file_with_an_awkward_name_burns_in(self, landscape, tmp_path):
        """The escaping path, exercised end to end."""
        from social_video.captions.ass import write_ass
        from social_video.schemas.brand import CaptionStyle

        track = CaptionTrack(cues=[CaptionCue(index=1, start=0.1, end=1.0, text="hi")])
        ass = write_ass(
            track,
            CaptionStyle(),
            tmp_path / "it's a, [weird]: name.ass",
            width=540,
            height=960,
        )
        manifest = build_manifest([landscape])
        edl = EDL(
            output_width=540,
            output_height=960,
            ranges=[EDLRange(source="landscape", start=0.0, end=1.2)],
        )
        out = tmp_path / "awkward.mp4"
        render_edl(edl, manifest, out, quality=DRAFT, caption_file=ass)
        assert out.is_file()


class TestQA:
    def test_passes_a_good_render(self, landscape, tmp_path):
        manifest = build_manifest([landscape])
        edl = EDL(ranges=[EDLRange(source="landscape", start=0.2, end=1.4)])
        out = tmp_path / "ok.mp4"
        render_edl(edl, manifest, out, quality=DRAFT)
        report = check_render(out, edl)
        assert report.passed, [c.message for c in report.errors]

    def test_reports_a_missing_output(self, tmp_path):
        report = check_render(tmp_path / "nothing.mp4")
        assert not report.passed

    def test_notices_a_duration_that_does_not_match(self, landscape, tmp_path):
        manifest = build_manifest([landscape])
        rendered = EDL(ranges=[EDLRange(source="landscape", start=0.0, end=1.0)])
        out = tmp_path / "short.mp4"
        render_edl(rendered, manifest, out, quality=DRAFT)

        claimed = EDL(ranges=[EDLRange(source="landscape", start=0.0, end=2.8)])
        report = check_render(out, claimed)
        assert not report.passed
        assert any("duration" in c.name for c in report.errors)

    def test_detects_silent_audio(self, tmp_path):
        path = make_silent_video(tmp_path / "quiet.mp4")
        report = check_render(path)
        assert any(c.name == "audio present" and not c.passed for c in report.checks)

    def test_repair_budget_is_bounded(self, landscape, tmp_path):
        manifest = build_manifest([landscape])
        edl = EDL(ranges=[EDLRange(source="landscape", start=0.0, end=1.0)])
        out = tmp_path / "x.mp4"
        render_edl(edl, manifest, out, quality=DRAFT)
        assert check_render(out, edl, attempt=3, max_attempts=3).exhausted
        assert not check_render(out, edl, attempt=1, max_attempts=3).exhausted


class TestDurationAccuracy:
    """Rendered length must not drift with the number of cuts."""

    def _edl(self, source_id, n, duration=1.5):
        step = duration / n
        return EDL(
            output_width=640,
            output_height=360,
            ranges=[
                EDLRange(
                    source=source_id,
                    start=0.2 + i * step,
                    end=0.2 + i * step + min(0.25, step * 0.7),
                )
                for i in range(n)
            ],
        )

    @pytest.mark.parametrize("cuts", [1, 4, 12])
    def test_duration_is_exact_regardless_of_cut_count(self, landscape, tmp_path, cuts):
        manifest = build_manifest([landscape])
        edl = self._edl(manifest.ids[0], cuts)
        out = tmp_path / f"cuts_{cuts}.mp4"
        render_edl(edl, manifest, out, quality=DRAFT)
        report = check_render(out, edl)
        duration_check = next(c for c in report.checks if c.name.startswith("duration"))
        assert duration_check.passed, duration_check.message


class TestQuietMaterial:
    """A range that happens to be silent must still render."""

    def test_silent_range_renders(self, tmp_path):
        source = make_silent_video(tmp_path / "quiet_source.mp4", duration=3.0)
        manifest = build_manifest([source])
        edl = EDL(
            output_width=320,
            output_height=240,
            ranges=[EDLRange(source=manifest.ids[0], start=0.5, end=1.5)],
        )
        out = tmp_path / "quiet.mp4"
        # loudnorm would produce NaN here and fail the encode outright.
        result = render_edl(edl, manifest, out, quality=DRAFT)
        assert out.is_file()
        assert result.loudness_target_lufs is None
        assert probe(out).has_audio


class TestMultiTrackAudio:
    """Multi-track recordings must render the track that was transcribed.

    OBS puts desktop audio on track 0 and the microphone on track 1, so a
    renderer that always maps 0:a:0 produces a silent video with captions
    describing audio nobody can hear.
    """

    def test_renders_the_selected_track(self, tmp_path):
        source = make_multitrack_video(tmp_path / "obs.mp4", duration=3.0)
        manifest = build_manifest([source])
        sid = manifest.ids[0]

        # Track 0 is silence, track 1 carries the tone.
        silent = EDL(
            output_width=320,
            output_height=240,
            ranges=[EDLRange(source=sid, start=0.2, end=1.5, audio_track=0)],
        )
        loud = EDL(
            output_width=320,
            output_height=240,
            ranges=[EDLRange(source=sid, start=0.2, end=1.5, audio_track=1)],
        )
        a = tmp_path / "track0.mp4"
        b = tmp_path / "track1.mp4"
        render_edl(silent, manifest, a, quality=DRAFT)
        render_edl(loud, manifest, b, quality=DRAFT)

        # The silent track is detected as such and skips normalisation; the
        # real track does not.
        assert check_render(b, loud).passed
        assert any(
            c.name == "audio present" and not c.passed for c in check_render(a, silent).checks
        )

    def test_out_of_range_track_falls_back_rather_than_failing(self, landscape, tmp_path):
        manifest = build_manifest([landscape])
        edl = EDL(
            output_width=320,
            output_height=240,
            ranges=[EDLRange(source=manifest.ids[0], start=0.0, end=1.0, audio_track=7)],
        )
        out = tmp_path / "fallback.mp4"
        render_edl(edl, manifest, out, quality=DRAFT)
        assert probe(out).has_audio
