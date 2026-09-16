"""Tests for ffmpeg filter construction.

The escaping cases here are the ones upstream video-use gets wrong and has no
test for. ``test_escape_against_real_ffmpeg`` is the one that actually matters:
it burns each pathological filename in with a real ffmpeg.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from social_video.ffmpeg.filters import (
    audio_cut_fades,
    crop_then_scale,
    escape_filter_path,
    scale_pad_to,
)

# Names that break naive escaping. Every one of these is a real-world case:
# apostrophes in surnames, colons in timestamped exports, Polish diacritics,
# Windows backslashes, commas in descriptive filenames.
NASTY_NAMES = [
    "plain.srt",
    "with space.srt",
    "with'apostrophe.srt",
    "with,comma.srt",
    "with[bracket].srt",
    "with:colon.srt",
    "semi;colon.srt",
    "eq=uals.srt",
    "zażółć gęślą jaźń.srt",
    "both'and:nasty.srt",
    "all'the:things=here,now[ok].srt",
]


class TestEscapeFilterPath:
    def test_wraps_in_single_quotes(self):
        assert escape_filter_path("/tmp/a.srt") == "'/tmp/a.srt'"

    def test_escapes_colon(self):
        assert escape_filter_path("/a:b.srt") == "'/a\\:b.srt'"

    def test_escapes_equals(self):
        assert escape_filter_path("/a=b.srt") == "'/a\\=b.srt'"

    def test_escapes_backslash_before_anything_else(self):
        # A Windows path must not have its backslashes reinterpreted as escapes.
        out = escape_filter_path(r"C:\Users\bob\master.srt")
        assert out == "'C\\:\\\\Users\\\\bob\\\\master.srt'"

    def test_apostrophe_closes_and_reopens_the_quote(self):
        # Inside an ffmpeg single-quoted string a backslash is not special, so
        # the quote has to be closed, the apostrophe escaped, and reopened.
        assert escape_filter_path("/a'b.srt") == "'/a'\\\\\\''b.srt'"

    def test_leaves_space_and_non_ascii_alone(self):
        out = escape_filter_path("/tmp/zażółć gęślą.srt")
        assert "zażółć gęślą" in out

    def test_accepts_pathlib(self):
        from pathlib import Path

        assert escape_filter_path(Path("/tmp/a.srt")) == "'/tmp/a.srt'"


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
@pytest.mark.parametrize("name", NASTY_NAMES)
def test_escape_against_real_ffmpeg(tmp_path, name):
    """Burn a subtitle file with a pathological name in, using a real ffmpeg."""
    srt = tmp_path / name
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nZażółć gęślą jaźń\n\n", encoding="utf-8")
    video = tmp_path / "base.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=10:duration=1",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
        capture_output=True,
    )
    result = subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(video),
            "-vf",
            f"subtitles={escape_filter_path(srt)}",
            "-frames:v",
            "1",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{name!r} failed: {result.stderr[-400:]}"


class TestAudioCutFades:
    def test_normal_segment(self):
        out = audio_cut_fades(10.0)
        assert "afade=t=in:st=0:d=0.0300" in out
        assert "afade=t=out:st=9.9700:d=0.0300" in out

    def test_short_segment_does_not_overlap_its_fades(self):
        # Upstream produces overlapping in/out ramps below 60ms, ducking the
        # entire segment. The fade is clamped to a third of the duration.
        out = audio_cut_fades(0.06)
        assert "d=0.0200" in out
        assert "st=0.0400" in out

    def test_rejects_non_positive_duration(self):
        with pytest.raises(ValueError, match="must be positive"):
            audio_cut_fades(0)


class TestGeometry:
    def test_scale_pad_builds_a_centred_canvas(self):
        out = scale_pad_to(1080, 1920)
        assert "force_original_aspect_ratio=decrease" in out
        assert "pad=1080:1920:(ow-iw)/2:(oh-ih)/2" in out
        assert out.endswith("setsar=1")

    def test_scale_pad_rejects_odd_dimensions(self):
        # yuv420p needs even dimensions; failing here beats failing in ffmpeg.
        with pytest.raises(ValueError, match="even"):
            scale_pad_to(1081, 1920)

    def test_crop_then_scale(self):
        assert crop_then_scale(608, 1080, 100, 0, 1080, 1920).startswith("crop=608:1080:100:0,")

    def test_crop_rejects_non_positive(self):
        with pytest.raises(ValueError, match="crop_w must be positive"):
            crop_then_scale(0, 1080, 0, 0, 1080, 1920)


class TestLoudnessDecision:
    """loudnorm emits NaN on digital silence and the encoder then fails.

    That would kill any edit whose selected material happens to be quiet, so
    the decision to normalise is made from a measurement.
    """

    def _measurement(self, input_i: float):
        from social_video.edl.loudness import LoudnessMeasurement

        return LoudnessMeasurement(
            input_i=input_i,
            input_tp=-3.0,
            input_lra=5.0,
            input_thresh=-30.0,
            target_offset=0.0,
        )

    def test_silence_is_detected(self):
        assert self._measurement(-90.0).is_silent
        assert self._measurement(float("-inf")).is_silent
        assert self._measurement(float("nan")).is_silent

    def test_normal_speech_is_not_silent(self):
        assert not self._measurement(-18.0).is_silent

    def test_silent_material_skips_normalisation(self):
        from social_video.edl.loudness import loudnorm_filter

        assert loudnorm_filter(self._measurement(-90.0)) is None

    def test_measured_values_enable_linear_mode(self):
        from social_video.edl.loudness import loudnorm_filter

        built = loudnorm_filter(self._measurement(-18.0))
        assert "measured_I=-18.00" in built
        assert "linear=true" in built

    def test_without_a_measurement_it_still_normalises(self):
        from social_video.edl.loudness import loudnorm_filter

        built = loudnorm_filter(None)
        assert built is not None
        assert "measured_I" not in built
