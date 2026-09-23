"""faster-whisper transcription with WhisperX forced alignment of every word.

Opt-in, behind the ``align`` extra. faster-whisper still does the recognition;
WhisperX then aligns each word against the audio with a wav2vec2 model, which
places word edges more tightly than Whisper's own attention-based timings.
That matters here because every cut is placed on a word edge.

Alignment needs no Hugging Face token. The cost is PyTorch (several GB) and one
alignment model per language, downloaded on first use. A word the aligner
cannot place -- numbers and symbols often have no phonetic model -- keeps the
timing faster-whisper gave it rather than being dropped or guessed.
"""

from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path

from social_video.errors import SocialVideoError
from social_video.paths import ensure_dir, models_dir
from social_video.schemas.transcript import (
    TokenType,
    Transcript,
    TranscriptSegment,
    TranscriptToken,
)
from social_video.transcribe.base import TranscriptionOptions, register_backend
from social_video.transcribe.faster_whisper import FasterWhisperBackend
from social_video.transcribe.normalize import build_transcript, clean_word_text

log = logging.getLogger(__name__)


class WhisperXBackend(FasterWhisperBackend):
    name = "whisperx"

    def validate_setup(self) -> tuple[bool, str]:
        ok, reason = super().validate_setup()
        if not ok:
            return ok, reason
        if importlib.util.find_spec("whisperx") is None:
            return False, (
                "WhisperX is not installed. It is optional and heavy (PyTorch, several GB): "
                "install it with `pip install 'social-video-agent[align]'`, or use the "
                "default faster-whisper backend."
            )
        return True, ""

    def transcribe(
        self,
        audio: Path,
        *,
        options: TranscriptionOptions,
        source_id: str,
        source_fingerprint: str,
        duration: float,
    ) -> Transcript:
        recognised = super().transcribe(
            audio,
            options=options,
            source_id=source_id,
            source_fingerprint=source_fingerprint,
            duration=duration,
        )
        language = recognised.language or options.language
        if not language or not recognised.segments:
            return recognised
        segments, aligner = _align(recognised.segments, audio, language)
        return build_transcript(
            source_id=source_id,
            source_fingerprint=source_fingerprint,
            duration=duration,
            provider=self.name,
            provider_model=options.model,
            provider_options={**recognised.provider_options, "alignment_model": aligner},
            segments=segments,
            language=language,
            language_confidence=recognised.language_confidence,
            audio_track=options.audio_track,
        )


def _align(
    segments: list[TranscriptSegment], audio: Path, language: str
) -> tuple[list[TranscriptSegment], str]:
    import whisperx

    device = _torch_device()
    try:
        model, metadata = whisperx.load_align_model(
            language_code=language,
            device=device,
            model_dir=str(ensure_dir(models_dir() / "whisperx")),
        )
    except ValueError as exc:
        # WhisperX ships alignment models for a fixed set of languages.
        raise SocialVideoError(
            f"WhisperX has no alignment model for language {language!r}: {exc}. "
            "Use the default faster-whisper backend for this recording."
        ) from exc
    result = whisperx.align(
        [{"start": s.start, "end": s.end, "text": s.text} for s in segments],
        model,
        metadata,
        whisperx.load_audio(str(audio)),
        device,
        return_char_alignments=False,
    )
    aligned = result.get("segments", [])
    if len(aligned) != len(segments):
        # The aligner splits or drops segments it cannot place; matching words
        # back by position would then shift every timing after the first gap.
        log.warning(
            "WhisperX returned %d segments for %d; keeping faster-whisper timings",
            len(aligned),
            len(segments),
        )
        return segments, ""
    name = str(metadata.get("model_name") or metadata.get("language") or "wav2vec2")
    return [_merge(original, raw) for original, raw in zip(segments, aligned, strict=True)], name


def _merge(original: TranscriptSegment, aligned: dict) -> TranscriptSegment:
    """Aligned word times where the aligner placed a word, recognised ones elsewhere."""
    recognised = [t for t in original.tokens if t.type is TokenType.WORD]
    words = [w for w in aligned.get("words", []) if clean_word_text(str(w.get("word", "")))]
    if len(words) != len(recognised):
        return original
    tokens: list[TranscriptToken] = []
    for fallback, word in zip(recognised, words, strict=True):
        start, end = word.get("start"), word.get("end")
        if start is None or end is None:
            tokens.append(fallback)
            continue
        tokens.append(
            TranscriptToken(
                type=TokenType.WORD,
                text=fallback.text,
                start=float(start),
                end=max(float(end), float(start)),
                confidence=_score(word.get("score"), fallback.confidence),
            )
        )
    return TranscriptSegment(
        text=original.text,
        start=min((t.start for t in tokens), default=original.start),
        end=max((t.end for t in tokens), default=original.end),
        tokens=tokens,
    )


def _score(value: object, fallback: float | None) -> float | None:
    try:
        return min(1.0, max(0.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def _torch_device() -> str:
    if os.environ.get("SOCIAL_VIDEO_FORCE_CPU"):
        return "cpu"
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


register_backend("whisperx", WhisperXBackend)
