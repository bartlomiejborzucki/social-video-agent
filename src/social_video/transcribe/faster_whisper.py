"""Local transcription with faster-whisper. The default backend.

Runs offline, needs no account, no API key, and no gated model. This is what
makes the project usable without configuring a paid transcription service.

Word timestamps are produced by passing ``word_timestamps=True`` and reading
``segment.words``. That sounds obvious, and it is: the widely-circulated fork
of the upstream project instead splits each segment evenly across its tokens
and ships a comment claiming the library cannot do better. It can, and for a
tool whose premise is cutting on word boundaries the difference is everything.
"""

from __future__ import annotations

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
from social_video.transcribe.normalize import build_transcript, clean_word_text

#: Model sizes worth offering. `small` is the default: it is the smallest model
#: that handles accented European languages well, and it runs comfortably on CPU.
MODELS = ("tiny", "base", "small", "medium", "large-v3", "large-v3-turbo")

log = logging.getLogger(__name__)

#: Fragments that identify a GPU-stack problem rather than a genuine bug.
_CUDA_FAILURE_MARKERS = ("cublas", "cudnn", "cuda", "libcu", "gpu")


class FasterWhisperBackend:
    name = "faster-whisper"

    def __init__(self) -> None:
        self._model = None
        self._model_key: tuple[str, str, str] | None = None

    # -- lifecycle ---------------------------------------------------------

    def validate_setup(self) -> tuple[bool, str]:
        """Cheap check. Does not download a model."""
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False, (
                "faster-whisper is not installed. It is a required dependency, so this "
                "usually means a broken environment: reinstall with `uv sync` or "
                "`pip install social-video-agent`."
            )
        return True, ""

    def _resolve_device(self, options: TranscriptionOptions) -> tuple[str, str]:
        """Pick device and compute type.

        ``auto`` prefers CUDA when it is genuinely usable. CTranslate2 needs a
        matching cuDNN/cuBLAS, and a mismatched CUDA install fails at model load
        rather than at import, so we fall back to CPU on any error instead of
        letting a GPU misconfiguration block transcription entirely.
        """
        device = options.device
        compute = options.compute_type
        if device == "auto":
            device = "cuda" if _cuda_looks_usable() else "cpu"
        if compute == "auto":
            compute = "float16" if device == "cuda" else "int8"
        return device, compute

    def _load(self, options: TranscriptionOptions):
        from faster_whisper import WhisperModel

        device, compute = self._resolve_device(options)
        key = (options.model, device, compute)
        if self._model is not None and self._model_key == key:
            return self._model

        cache = ensure_dir(models_dir() / "faster-whisper")
        try:
            model = WhisperModel(
                options.model, device=device, compute_type=compute, download_root=str(cache)
            )
        except Exception as exc:
            if device == "cuda":
                log.warning("CUDA model load failed (%s); falling back to CPU", exc)
                model = WhisperModel(
                    options.model, device="cpu", compute_type="int8", download_root=str(cache)
                )
                key = (options.model, "cpu", "int8")
            else:
                raise SocialVideoError(
                    f"could not load the {options.model!r} Whisper model: {exc}"
                ) from exc
        self._model, self._model_key = model, key
        return model

    def _force_cpu(self, options: TranscriptionOptions):
        """Drop any CUDA model and reload on CPU."""
        from faster_whisper import WhisperModel

        cache = ensure_dir(models_dir() / "faster-whisper")
        model = WhisperModel(
            options.model, device="cpu", compute_type="int8", download_root=str(cache)
        )
        self._model, self._model_key = model, (options.model, "cpu", "int8")
        return model

    @property
    def _is_cpu(self) -> bool:
        return bool(self._model_key and self._model_key[1] == "cpu")

    def _decode(self, model, audio: Path, options: TranscriptionOptions):
        """Run the model and drain the segment generator.

        faster-whisper returns a lazy generator, so errors surface during
        iteration rather than at the call. Draining it here means the caller
        sees a list and the retry logic has a single place to sit.
        """
        segments_iter, info = model.transcribe(
            str(audio),
            language=options.language,
            # The whole point. Without this there are no word boundaries to cut on.
            word_timestamps=True,
            vad_filter=options.vad,
            hotwords=" ".join(options.hotwords) or None,
            beam_size=5,
        )
        return list(segments_iter), info

    # -- transcription -----------------------------------------------------

    def transcribe(
        self,
        audio: Path,
        *,
        options: TranscriptionOptions,
        source_id: str,
        source_fingerprint: str,
        duration: float,
    ) -> Transcript:
        model = self._load(options)
        try:
            raw_segments, info = self._decode(model, audio, options)
        except RuntimeError as exc:
            # CTranslate2 loads a CUDA model happily and only discovers a
            # missing or mismatched cuBLAS/cuDNN when it runs the encoder, so
            # this has to be caught here and not just around model construction.
            if not _is_cuda_runtime_failure(exc) or self._is_cpu:
                raise
            log.warning(
                "CUDA transcription failed (%s); retrying on CPU. Install a cuBLAS/cuDNN "
                "matching your CTranslate2 build, or set SOCIAL_VIDEO_FORCE_CPU=1 to skip "
                "the GPU attempt.",
                exc,
            )
            model = self._force_cpu(options)
            raw_segments, info = self._decode(model, audio, options)

        segments: list[TranscriptSegment] = []
        for seg in raw_segments:
            tokens: list[TranscriptToken] = []
            for word in seg.words or []:
                text = clean_word_text(word.word)
                if not text:
                    continue
                start = float(word.start)
                end = float(word.end)
                tokens.append(
                    TranscriptToken(
                        type=TokenType.WORD,
                        text=text,
                        start=start,
                        # Guard against the occasional zero-or-inverted span the
                        # DTW alignment can emit on very short words.
                        end=max(end, start),
                        confidence=_probability(word),
                    )
                )
            segments.append(
                TranscriptSegment(
                    text=seg.text.strip(),
                    start=float(seg.start),
                    end=max(float(seg.end), float(seg.start)),
                    tokens=tokens,
                )
            )

        return build_transcript(
            source_id=source_id,
            source_fingerprint=source_fingerprint,
            duration=duration,
            provider=self.name,
            provider_model=options.model,
            provider_options={
                "vad": str(options.vad),
                "device": self._model_key[1] if self._model_key else "unknown",
                "compute_type": self._model_key[2] if self._model_key else "unknown",
            },
            segments=segments,
            language=getattr(info, "language", None) or options.language,
            language_confidence=_clamp_probability(getattr(info, "language_probability", None)),
            audio_track=options.audio_track,
        )


def _probability(word: object) -> float | None:
    value = getattr(word, "probability", None)
    return _clamp_probability(value)


def _clamp_probability(value: object) -> float | None:
    """Coerce a provider confidence into the 0..1 the schema promises."""
    if value is None:
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return min(1.0, max(0.0, number))


def _is_cuda_runtime_failure(exc: Exception) -> bool:
    """Whether an exception is a missing/mismatched CUDA library rather than a bug."""
    message = str(exc).lower()
    return any(marker in message for marker in _CUDA_FAILURE_MARKERS)


def _cuda_looks_usable() -> bool:
    """Best-effort CUDA probe that never raises and never imports torch."""
    if os.environ.get("SOCIAL_VIDEO_FORCE_CPU"):
        return False
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


register_backend("faster-whisper", FasterWhisperBackend)
register_backend("faster_whisper", FasterWhisperBackend)
