"""WhisperX refines word edges; anything it cannot place keeps its first timing.

WhisperX itself is several gigabytes of PyTorch and is never installed in CI,
so these tests stand in a module with its real call signatures. They pin what
this project does with the aligner's output, not the aligner.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from social_video.errors import SocialVideoError
from social_video.schemas.transcript import Transcript, TranscriptSegment, TranscriptToken
from social_video.transcribe import whisperx_backend
from social_video.transcribe.base import TranscriptionOptions, get_backend
from social_video.transcribe.faster_whisper import FasterWhisperBackend
from social_video.transcribe.whisperx_backend import WhisperXBackend


def _recognised(language: str | None = "pl") -> Transcript:
    tokens = [
        TranscriptToken(text="Dzień", start=0.10, end=0.50, confidence=0.9),
        TranscriptToken(text="dobry", start=0.50, end=1.00, confidence=0.8),
        TranscriptToken(text="2026", start=1.00, end=1.60, confidence=0.7),
    ]
    return Transcript(
        source_id="clip",
        source_fingerprint="f" * 16,
        duration=2.0,
        language=language,
        provider="faster-whisper",
        provider_model="small",
        provider_options={"device": "cpu"},
        segments=[TranscriptSegment(text="Dzień dobry 2026", start=0.1, end=1.6, tokens=tokens)],
        tokens=tokens,
    )


@pytest.fixture
def aligner(monkeypatch: pytest.MonkeyPatch):
    calls: dict[str, object] = {}
    module = types.ModuleType("whisperx")

    def load_align_model(language_code, device, model_name=None, model_dir=None):
        if language_code == "xx":
            raise ValueError("No default align-model for language: xx")
        calls["language"] = language_code
        return object(), {"language": language_code, "model_name": "wav2vec2-pl"}

    def align(segments, model, metadata, audio, device, return_char_alignments=False):
        calls["segments"] = segments
        return {
            "segments": [
                {
                    "start": 0.12,
                    "end": 1.55,
                    "text": segments[0]["text"],
                    "words": calls.get(
                        "words",
                        [
                            {"word": "Dzień", "start": 0.12, "end": 0.41, "score": 0.97},
                            {"word": "dobry", "start": 0.46, "end": 0.93, "score": 0.95},
                            # Digits have no phonetic model; WhisperX leaves them unplaced.
                            {"word": "2026"},
                        ],
                    ),
                }
            ]
        }

    module.load_align_model = load_align_model  # type: ignore[attr-defined]
    module.align = align  # type: ignore[attr-defined]
    module.load_audio = lambda path: path  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "whisperx", module)
    monkeypatch.setattr(whisperx_backend.importlib.util, "find_spec", lambda name: object())
    return calls


def _run(monkeypatch: pytest.MonkeyPatch, recognised: Transcript) -> Transcript:
    monkeypatch.setattr(FasterWhisperBackend, "transcribe", lambda self, audio, **kw: recognised)
    return WhisperXBackend().transcribe(
        Path("audio.wav"),
        options=TranscriptionOptions(),
        source_id="clip",
        source_fingerprint="f" * 16,
        duration=2.0,
    )


def test_it_is_registered_and_reports_how_to_install_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(whisperx_backend.importlib.util, "find_spec", lambda name: None)

    backend = get_backend("whisperx")
    ok, reason = backend.validate_setup()

    assert backend.name == "whisperx"
    assert not ok
    assert "social-video-agent[align]" in reason


def test_aligned_edges_replace_recognised_ones_and_unplaced_words_keep_theirs(
    monkeypatch: pytest.MonkeyPatch, aligner
) -> None:
    transcript = _run(monkeypatch, _recognised())

    words = [(w.text, w.start, w.end, w.confidence) for w in transcript.words]
    assert words == [
        ("Dzień", 0.12, 0.41, 0.97),
        ("dobry", 0.46, 0.93, 0.95),
        ("2026", 1.00, 1.60, 0.7),
    ]
    assert transcript.provider == "whisperx"
    assert transcript.provider_options["alignment_model"] == "wav2vec2-pl"
    assert aligner["language"] == "pl"
    assert aligner["segments"] == [{"start": 0.1, "end": 1.6, "text": "Dzień dobry 2026"}]


def test_a_word_count_mismatch_keeps_the_recognised_timings(
    monkeypatch: pytest.MonkeyPatch, aligner
) -> None:
    aligner["words"] = [{"word": "Dzień", "start": 0.12, "end": 0.41}]

    transcript = _run(monkeypatch, _recognised())

    assert [(w.start, w.end) for w in transcript.words] == [(0.1, 0.5), (0.5, 1.0), (1.0, 1.6)]


def test_a_language_without_an_alignment_model_says_so(
    monkeypatch: pytest.MonkeyPatch, aligner
) -> None:
    with pytest.raises(SocialVideoError, match="no alignment model for language 'xx'"):
        _run(monkeypatch, _recognised(language="xx"))
