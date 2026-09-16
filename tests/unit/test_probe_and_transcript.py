"""Frame-rate parsing, rotation handling, transcript normalisation, packing."""

from __future__ import annotations

import pytest

from social_video.ffmpeg.filters import crop_position_expression
from social_video.ffmpeg.probe import _normalise_rotation, _pick_frame_rate, parse_fps
from social_video.schemas.transcript import TokenType, Transcript, TranscriptToken
from social_video.transcribe.normalize import synthesize_spacing
from social_video.transcript.pack import format_duration, group_phrases, pack_transcript


class TestParseFps:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("30", "30/1"),
            ("30000/1001", "30000/1001"),
            ("60", "60/1"),
            ("23.976", "2997/125"),
            ("25", "25/1"),
        ],
    )
    def test_canonicalises_to_exact_rationals(self, text, expected):
        assert parse_fps(text) == expected

    def test_is_idempotent(self):
        once = parse_fps("29.97")
        assert parse_fps(once) == once

    @pytest.mark.parametrize("bad", ["", "abc", "-30", "30/0", "0", "1/0", "3 0", "1e9"])
    def test_rejects_nonsense(self, bad):
        with pytest.raises(ValueError):
            parse_fps(bad)

    def test_rejects_values_beyond_avrational_range(self):
        # AVRational components are int32.
        with pytest.raises(ValueError, match="too large"):
            parse_fps("99999999999/99999999998")

    def test_rejects_absurdly_long_input(self):
        with pytest.raises(ValueError):
            parse_fps("1" * 40)


class TestRotation:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [(90, 90), (-90, 270), (180, 180), (270, 270), (0, 0), (-270, 90), (360, 0)],
    )
    def test_normalises_into_0_360(self, raw, expected):
        stream = {"side_data_list": [{"rotation": raw}]}
        assert _normalise_rotation(stream) == expected

    def test_absent_side_data_means_no_rotation(self):
        assert _normalise_rotation({}) == 0

    def test_unparseable_rotation_means_no_rotation(self):
        assert _normalise_rotation({"side_data_list": [{"rotation": "sideways"}]}) == 0


class TestPickFrameRate:
    def test_prefers_avg_over_r(self):
        # avg is correct for variable-frame-rate phone footage; r is the
        # theoretical maximum.
        assert _pick_frame_rate({"avg_frame_rate": "30/1", "r_frame_rate": "60/1"}) == "30/1"

    def test_falls_back_to_r_when_avg_is_absent(self):
        assert _pick_frame_rate({"avg_frame_rate": "0/0", "r_frame_rate": "25/1"}) == "25/1"

    def test_defaults_when_both_are_useless(self):
        assert _pick_frame_rate({}) == "30/1"


class TestSynthesizeSpacing:
    def words(self, spans):
        return [
            TranscriptToken(type=TokenType.WORD, text=f"w{i}", start=s, end=e)
            for i, (s, e) in enumerate(spans)
        ]

    def test_inserts_a_gap_token_between_words(self):
        out = synthesize_spacing(self.words([(0.0, 0.5), (1.2, 1.6)]))
        assert [t.type for t in out] == [TokenType.WORD, TokenType.SPACING, TokenType.WORD]
        assert out[1].start == 0.5
        assert out[1].end == 1.2

    def test_no_gap_token_for_contiguous_words(self):
        out = synthesize_spacing(self.words([(0.0, 0.5), (0.5, 1.0)]))
        assert all(t.type is TokenType.WORD for t in out)

    def test_empty_input(self):
        assert synthesize_spacing([]) == []

    def test_orders_by_time(self):
        out = synthesize_spacing(self.words([(2.0, 2.5), (0.0, 0.5)]))
        assert out[0].start == 0.0

    def test_gap_is_attributed_to_the_preceding_speaker(self):
        a = TranscriptToken(type=TokenType.WORD, text="a", start=0, end=0.5, speaker="s0")
        b = TranscriptToken(type=TokenType.WORD, text="b", start=2.0, end=2.5, speaker="s1")
        out = synthesize_spacing([a, b])
        assert out[1].speaker == "s0"


def make_transcript(words, duration=60.0):
    tokens = [
        TranscriptToken(type=TokenType.WORD, text=t, start=s, end=e, speaker=sp)
        for t, s, e, sp in words
    ]
    return Transcript(
        source_id="clip",
        source_fingerprint="f",
        duration=duration,
        provider="test",
        tokens=synthesize_spacing(tokens),
    )


class TestPacking:
    def test_groups_on_silence(self):
        tr = make_transcript(
            [
                ("Hello", 0.0, 0.4, None),
                ("there", 0.4, 0.8, None),
                ("and", 3.0, 3.3, None),
                ("welcome", 3.3, 3.9, None),
            ]
        )
        phrases = group_phrases(tr, silence=0.5)
        assert len(phrases) == 2
        assert phrases[0].text == "Hello there"

    def test_groups_on_speaker_change(self):
        tr = make_transcript(
            [
                ("Hi", 0.0, 0.4, "s0"),
                ("there", 0.4, 0.8, "s0"),
                ("Hello", 0.85, 1.2, "s1"),
            ]
        )
        assert len(group_phrases(tr, silence=0.5)) == 2

    def test_caps_phrase_length(self):
        # Upstream has no cap, so continuous speech collapses into one line with
        # a single unusable time range.
        words = [(f"w{i}", i * 0.2, i * 0.2 + 0.19, None) for i in range(60)]
        phrases = group_phrases(make_transcript(words), silence=0.5, max_words=10)
        assert all(len(p.words) <= 10 for p in phrases)
        assert len(phrases) >= 6

    def test_reports_media_duration_not_speech_span(self):
        # A clip with a long silent lead-in must not be described as shorter.
        tr = make_transcript([("word", 30.0, 30.5, None)], duration=90.0)
        assert "1m 30.0s" in pack_transcript(tr)

    def test_rejoins_separated_punctuation(self):
        tr = make_transcript([("Hello", 0.0, 0.4, None), (",", 0.4, 0.45, None)])
        assert "Hello," in group_phrases(tr)[0].text

    def test_format_duration(self):
        assert format_duration(9.5) == "9.5s"
        assert format_duration(90.0) == "1m 30.0s"


class TestCropExpression:
    def test_static_for_a_single_keyframe(self):
        assert crop_position_expression([(0.0, 42)], lo=0, hi=100) == "42"

    def test_clamps_to_bounds(self):
        assert crop_position_expression([(0.0, 999)], lo=0, hi=100) == "100"
        assert crop_position_expression([(0.0, -50)], lo=0, hi=100) == "0"

    def test_empty_keyframes(self):
        assert crop_position_expression([], lo=7, hi=100) == "7"

    def test_earliest_interval_is_the_outermost_condition(self):
        # Built in the wrong order, a later condition shadows every earlier one
        # and the whole animation evaluates incorrectly.
        expr = crop_position_expression([(0.0, 0), (1.0, 100), (2.0, 50)], lo=0, hi=200)
        assert expr.index("lt(t,1.0000)") < expr.index("lt(t,2.0000)")

    def test_holds_the_final_value_after_the_last_keyframe(self):
        expr = crop_position_expression([(0.0, 0), (1.0, 100)], lo=0, hi=200)
        assert expr.endswith(",100)")


class TestFrameAlignment:
    """ffmpeg rounds `-t` up to a whole frame.

    Unaligned, that adds up to one frame per cut, so the output drifts further
    from the EDL the more cuts it has. Measured at ~16ms per cut before this.
    """

    def test_rounds_to_a_whole_number_of_frames(self):
        from social_video.ffmpeg.probe import frame_aligned_duration

        # 0.35s at 30fps is 10.5 frames; it must become a whole number.
        aligned = frame_aligned_duration(0.35, "30/1")
        assert aligned * 30 == pytest.approx(round(aligned * 30))

    def test_already_aligned_duration_is_unchanged(self):
        from social_video.ffmpeg.probe import frame_aligned_duration

        assert frame_aligned_duration(1.0, "30/1") == pytest.approx(1.0)
        assert frame_aligned_duration(10 / 30, "30/1") == pytest.approx(10 / 30)

    def test_is_idempotent(self):
        from social_video.ffmpeg.probe import frame_aligned_duration

        once = frame_aligned_duration(0.35, "30/1")
        assert frame_aligned_duration(once, "30/1") == pytest.approx(once)

    def test_handles_fractional_rates(self):
        from social_video.ffmpeg.probe import frame_aligned_duration

        aligned = frame_aligned_duration(1.0, "30000/1001")
        assert aligned * (30000 / 1001) == pytest.approx(round(aligned * (30000 / 1001)))

    def test_never_collapses_a_range_to_nothing(self):
        from social_video.ffmpeg.probe import frame_aligned_duration

        # A sub-frame range must still render at least one frame.
        assert frame_aligned_duration(0.001, "30/1") == pytest.approx(1 / 30)

    def test_error_does_not_accumulate_across_many_cuts(self):
        from social_video.ffmpeg.probe import frame_aligned_duration

        total = sum(frame_aligned_duration(0.35, "30/1") for _ in range(40))
        assert total * 30 == pytest.approx(round(total * 30))
