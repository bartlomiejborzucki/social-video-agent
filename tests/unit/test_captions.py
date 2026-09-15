"""Caption chunking, ASS generation, and SRT output."""

from __future__ import annotations

import pytest

from social_video.captions.ass import (
    escape_text,
    format_timestamp,
    hex_to_ass_colour,
    render_ass,
)
from social_video.captions.chunk import build_caption_track
from social_video.captions.srt import render_srt
from social_video.edl.timeline import Timeline
from social_video.schemas.brand import CaptionCase, CaptionPosition, CaptionStyle
from social_video.schemas.captions import CaptionCue, CaptionTrack
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.transcript import TokenType, Transcript, TranscriptToken
from social_video.transcribe.normalize import synthesize_spacing


def make_transcript(words: list[tuple[str, float, float]], speaker: str | None = None):
    tokens = [
        TranscriptToken(type=TokenType.WORD, text=t, start=s, end=e, speaker=speaker)
        for t, s, e in words
    ]
    return Transcript(
        source_id="a",
        source_fingerprint="f",
        duration=60.0,
        provider="test",
        tokens=synthesize_spacing(tokens),
    )


class TestChunking:
    def test_breaks_on_sentence_end(self):
        tr = make_transcript([("Hello", 0.0, 0.4), ("there.", 0.4, 0.9), ("Next", 1.0, 1.4)])
        tl = Timeline(EDL(ranges=[EDLRange(source="a", start=0.0, end=10.0)]))
        track = build_caption_track(tr, tl)
        assert track.cues[0].text == "Hello there."

    def test_respects_max_words(self):
        words = [(f"w{i}", i * 0.3, i * 0.3 + 0.25) for i in range(12)]
        tr = make_transcript(words)
        tl = Timeline(EDL(ranges=[EDLRange(source="a", start=0.0, end=10.0)]))
        track = build_caption_track(tr, tl, style=CaptionStyle(max_words_per_cue=3))
        assert all(len(c.words) <= 3 for c in track.cues)

    def test_drops_words_removed_by_the_edit(self):
        tr = make_transcript([("keep", 0.0, 0.5), ("cut", 5.0, 5.5), ("keep2", 9.0, 9.5)])
        tl = Timeline(
            EDL(
                ranges=[
                    EDLRange(source="a", start=0.0, end=1.0),
                    EDLRange(source="a", start=8.5, end=10.0),
                ]
            )
        )
        track = build_caption_track(tr, tl)
        joined = " ".join(c.text for c in track.cues)
        assert "cut" not in joined
        assert "keep" in joined and "keep2" in joined

    def test_times_are_output_relative_not_source_relative(self):
        tr = make_transcript([("late", 30.0, 30.5)])
        tl = Timeline(EDL(ranges=[EDLRange(source="a", start=29.0, end=32.0)]))
        track = build_caption_track(tr, tl)
        # 30.0s of source is 1.0s into an edit that starts at 29.0s.
        assert track.cues[0].start == pytest.approx(1.0)

    def test_cues_never_overlap(self):
        words = [(f"w{i}", i * 0.2, i * 0.2 + 0.19) for i in range(40)]
        tr = make_transcript(words)
        tl = Timeline(EDL(ranges=[EDLRange(source="a", start=0.0, end=20.0)]))
        track = build_caption_track(tr, tl, style=CaptionStyle(min_cue_duration=1.5))
        assert track.overlapping() == []

    def test_case_is_configurable(self):
        tr = make_transcript([("Hello", 0.0, 0.4)])
        tl = Timeline(EDL(ranges=[EDLRange(source="a", start=0.0, end=5.0)]))
        upper = build_caption_track(tr, tl, style=CaptionStyle(case=CaptionCase.UPPER))
        spoken = build_caption_track(tr, tl, style=CaptionStyle(case=CaptionCase.AS_SPOKEN))
        assert upper.cues[0].text == "HELLO"
        assert spoken.cues[0].text == "Hello"


class TestAssColour:
    def test_rgb_is_reversed_to_bgr_with_alpha(self):
        # ASS stores &HAABBGGRR, which is easy to get backwards.
        assert hex_to_ass_colour("#FF0000") == "&H000000FF"
        assert hex_to_ass_colour("#0000FF") == "&H00FF0000"
        assert hex_to_ass_colour("#FFFFFF") == "&H00FFFFFF"

    def test_short_form(self):
        assert hex_to_ass_colour("#F00") == "&H000000FF"

    def test_rejects_nonsense(self):
        with pytest.raises(ValueError, match="colour must be"):
            hex_to_ass_colour("#12345")


class TestAssDocument:
    def test_timestamps_use_centiseconds(self):
        assert format_timestamp(0) == "0:00:00.00"
        assert format_timestamp(3661.5) == "1:01:01.50"
        assert format_timestamp(-5) == "0:00:00.00"

    def test_escapes_override_characters(self):
        assert escape_text("a{b}c") == "a\\{b\\}c"
        assert escape_text("a\nb") == "a\\Nb"

    def test_playres_matches_the_output_canvas(self):
        # This is what makes a font size mean the same thing at 1080p and 4K.
        track = CaptionTrack(cues=[CaptionCue(index=1, start=0, end=1, text="hi")])
        doc = render_ass(track, CaptionStyle(), width=1080, height=1920)
        assert "PlayResX: 1080" in doc
        assert "PlayResY: 1920" in doc

    def test_font_size_scales_with_height(self):
        track = CaptionTrack(cues=[CaptionCue(index=1, start=0, end=1, text="hi")])
        style = CaptionStyle(font_size_pct=5.0)
        small = render_ass(track, style, width=540, height=960)
        large = render_ass(track, style, width=1080, height=1920)
        assert ",48," in small  # 5% of 960
        assert ",96," in large  # 5% of 1920

    def test_wrapping_is_enabled(self):
        # WrapStyle 2 would let a long cue run off both edges of the frame.
        track = CaptionTrack(cues=[CaptionCue(index=1, start=0, end=1, text="hi")])
        doc = render_ass(track, CaptionStyle(), width=1080, height=1920)
        assert "WrapStyle: 0" in doc

    def test_position_maps_to_alignment(self):
        track = CaptionTrack(cues=[CaptionCue(index=1, start=0, end=1, text="hi")])
        bottom = render_ass(
            track, CaptionStyle(position=CaptionPosition.BOTTOM), width=100, height=100
        )
        top = render_ass(track, CaptionStyle(position=CaptionPosition.TOP), width=100, height=100)
        assert bottom.count(",2,") >= 1
        assert top.count(",8,") >= 1

    def test_polish_text_survives_verbatim(self):
        track = CaptionTrack(cues=[CaptionCue(index=1, start=0, end=1, text="Zażółć gęślą jaźń")])
        doc = render_ass(track, CaptionStyle(), width=1080, height=1920)
        assert "Zażółć gęślą jaźń" in doc


class TestSrt:
    def test_basic_shape(self):
        track = CaptionTrack(cues=[CaptionCue(index=1, start=1.5, end=2.25, text="Cześć")])
        out = render_srt(track)
        assert "00:00:01,500 --> 00:00:02,250" in out
        assert "Cześć" in out

    def test_millisecond_rounding_does_not_produce_1000(self):
        track = CaptionTrack(cues=[CaptionCue(index=1, start=0.9999, end=2.0, text="x")])
        assert "00:00:01,000" in render_srt(track)


class TestKaraokeCase:
    """Highlighting must not bypass the style's case.

    The karaoke path renders individual words rather than the cue's cased text,
    so it has to apply the case itself.
    """

    def _doc(self, case):
        from social_video.schemas.captions import CaptionWord

        track = CaptionTrack(
            cues=[
                CaptionCue(
                    index=1,
                    start=0.0,
                    end=1.0,
                    text="hello there",
                    words=[
                        CaptionWord(text="hello", start=0.0, end=0.5),
                        CaptionWord(text="there", start=0.5, end=1.0),
                    ],
                )
            ]
        )
        style = CaptionStyle(case=case, highlight_active_word=True)
        return render_ass(track, style, width=1080, height=1920)

    def test_uppercase_is_applied_when_highlighting(self):
        doc = self._doc(CaptionCase.UPPER)
        assert "HELLO" in doc
        assert "}hello " not in doc

    def test_as_spoken_is_preserved_when_highlighting(self):
        assert "hello" in self._doc(CaptionCase.AS_SPOKEN)

    def test_polish_uppercase_when_highlighting(self):
        from social_video.schemas.captions import CaptionWord

        track = CaptionTrack(
            cues=[
                CaptionCue(
                    index=1,
                    start=0.0,
                    end=1.0,
                    text="zażółć",
                    words=[CaptionWord(text="zażółć", start=0.0, end=1.0)],
                )
            ]
        )
        doc = render_ass(
            track,
            CaptionStyle(case=CaptionCase.UPPER, highlight_active_word=True),
            width=1080,
            height=1920,
        )
        assert "ZAŻÓŁĆ" in doc
