"""1.4: a transcript that finished is not necessarily one fit to cut on."""

from __future__ import annotations

import json

from social_video.schemas.transcript import Transcript, TranscriptToken
from social_video.transcribe.quality import _next_model, assess_transcript, find_loops, is_junk


def _transcript(
    texts: list[str],
    *,
    model: str = "small",
    confidence: float | None = 0.9,
    language: str = "pl",
    language_confidence: float | None = 0.98,
) -> Transcript:
    tokens = [
        TranscriptToken(text=text, start=i * 0.4, end=i * 0.4 + 0.3, confidence=confidence)
        for i, text in enumerate(texts)
    ]
    return Transcript(
        source_id="clip",
        source_fingerprint="f" * 16,
        duration=len(texts) * 0.4 + 1,
        provider="faster-whisper",
        provider_model=model,
        language=language,
        language_confidence=language_confidence,
        tokens=tokens,
    )


SPEECH = [
    "dzisiaj",
    "pokażę",
    "wam",
    "jak",
    "skrócić",
    "nagranie",
    "do",
    "jednej",
    "minuty",
    "bez",
    "utraty",
    "sensu",
]


def test_clean_speech_passes():
    quality = assess_transcript(_transcript(SPEECH))
    assert quality.ok
    assert quality.suggested_model is None
    assert json.loads(json.dumps(quality.to_dict()))["ok"] is True


def test_junk_tokens():
    assert is_junk("♪")
    assert is_junk("[Music]")
    assert is_junk("(muzyka)")
    assert is_junk("��")
    assert is_junk("...")
    assert not is_junk("minuty,")
    assert not is_junk("3%")


def test_music_under_voice_suggests_a_larger_model():
    texts = SPEECH[:6] + ["♪"] * 4
    quality = assess_transcript(_transcript(texts, model="small"))
    assert not quality.ok
    assert quality.junk_ratio == 0.4
    assert quality.suggested_model == "medium"
    assert "music" in quality.warnings[0]


def test_low_confidence_is_reported():
    quality = assess_transcript(_transcript(SPEECH, confidence=0.2, model="base"))
    assert quality.low_confidence_ratio == 1.0
    assert quality.suggested_model == "small"


def test_missing_confidence_is_not_a_failure():
    assert assess_transcript(_transcript(SPEECH, confidence=None)).low_confidence_ratio is None


def test_decoding_loop_is_found():
    texts = SPEECH[:3] + ["dziękuję", "za", "uwagę"] * 5 + SPEECH[3:6]
    transcript = _transcript(texts)
    loops = find_loops(transcript.words)
    assert loops == [transcript.words[3].start]
    assert assess_transcript(transcript).suggested_model == "medium"


def test_emphasis_is_not_a_loop():
    assert find_loops(_transcript(["nie", "nie", "nie", "tak"]).words) == []


def test_english_only_model_with_another_language():
    quality = assess_transcript(
        _transcript(SPEECH, model="medium.en", language="en"), requested_language="pl"
    )
    assert quality.suggested_model == "medium"
    assert "translates pl speech" in quality.warnings[0]


def test_uncertain_language_asks_for_a_hint():
    quality = assess_transcript(_transcript(SPEECH, language_confidence=0.3))
    assert any("--language" in w for w in quality.warnings)
    assert quality.suggested_model is None
    named = assess_transcript(_transcript(SPEECH, language_confidence=0.3), requested_language="pl")
    assert named.ok


def test_model_ladder():
    assert _next_model("tiny") == "base"
    assert _next_model("small.en") == "medium.en"
    assert _next_model("medium.en") == "large-v3"
    assert _next_model("large-v3-turbo") == "large-v3"
    assert _next_model("large-v3") is None
    assert _next_model("custom-model") is None


def test_largest_model_explains_the_next_step():
    quality = assess_transcript(_transcript(["♪"] * 8, model="large-v3"))
    assert quality.suggested_model is None
    assert any("--audio-track" in w for w in quality.warnings)


def test_a_false_start_glued_into_one_word_is_flagged_with_a_refine_span() -> None:
    from social_video.schemas.transcript import TokenType, Transcript, TranscriptToken
    from social_video.transcribe.normalize import synthesize_spacing
    from social_video.transcribe.quality import suspect_words

    words = [("To", 50.8, 51.1), ("zawsze", 51.4, 55.3), ("być", 55.4, 55.7), ("tak.", 56.0, 56.3)]
    tokens = [TranscriptToken(type=TokenType.WORD, text=t, start=s, end=e) for t, s, e in words]
    transcript = Transcript(
        source_id="kamera", source_fingerprint="x", duration=120.0, provider="faster-whisper",
        provider_model="medium", tokens=synthesize_spacing(tokens),
    )  # fmt: skip
    # The sound stops for a pause inside "być", which is short enough not to
    # be flagged for its length.
    quiet = [(55.45, 55.65)]
    assert [w.text for w in suspect_words(transcript, quiet)] == ["zawsze"]
    quality = assess_transcript(transcript, requested_language="pl", quiet=[(52.0, 54.5)])
    assert [w.text for w in quality.suspects] == ["zawsze"]
    assert "holds 2.5s of silence" in quality.suspects[0].reason
    assert quality.refine_spans == ((50.9, 55.8),)
    assert any("--refine 50.90-55.80 --model large-v3" in w for w in quality.warnings)
    assert quality.to_dict()["refine"] == ["50.90-55.80"]
