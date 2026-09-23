"""The transcription provider interface.

Two design points, both learned from auditing what went wrong elsewhere:

* ``validate_setup`` is separate from ``transcribe``, and is checked *before*
  any audio is extracted. A missing model or an absent API key should cost a
  millisecond, not a full ffmpeg decode. (This lifecycle split is the one good
  idea in the parleyw/video-use fork; the implementation here is our own.)
* Backends are registered, not hard-coded in an if/elif chain, and their heavy
  imports are deferred until the backend is actually constructed. Importing
  this module must never require torch, requests, or a model download.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from social_video.errors import SocialVideoError
from social_video.schemas.transcript import Transcript


@dataclass(frozen=True)
class TranscriptionOptions:
    """Everything that can change a transcription result.

    Every field here participates in the cache key. Adding a field that affects
    output without adding it to the key is the classic staleness bug.
    """

    language: str | None = None
    model: str = "small"
    #: Voice-activity detection trims silence before decoding; it makes long
    #: recordings much faster and reduces hallucinated text in quiet passages.
    vad: bool = True
    audio_track: int = 0
    num_speakers: int | None = None
    diarize: bool = False
    #: Vocabulary bias: names, jargon, product terms the model will not guess.
    hotwords: tuple[str, ...] = field(default_factory=tuple)
    device: str = "auto"
    compute_type: str = "auto"

    def cache_fields(self) -> dict[str, object]:
        return {
            "language": self.language,
            "model": self.model,
            "vad": self.vad,
            "audio_track": self.audio_track,
            "num_speakers": self.num_speakers,
            "diarize": self.diarize,
            "hotwords": list(self.hotwords),
        }


@runtime_checkable
class TranscriptionBackend(Protocol):
    """What every provider must offer."""

    name: str

    def validate_setup(self) -> tuple[bool, str]:
        """Whether this backend can run right now.

        Returns ``(True, "")`` when usable, or ``(False, reason)`` where the
        reason tells the user exactly what to install, set, or accept. Must be
        cheap and must not download anything.
        """
        ...

    def transcribe(
        self,
        audio: Path,
        *,
        options: TranscriptionOptions,
        source_id: str,
        source_fingerprint: str,
        duration: float,
    ) -> Transcript:
        """Transcribe a prepared mono WAV into a canonical transcript."""
        ...


class BackendNotAvailableError(SocialVideoError):
    """A backend was requested but cannot run, with the reason attached."""


_REGISTRY: dict[str, Callable[[], TranscriptionBackend]] = {}


def register_backend(name: str, factory: Callable[[], TranscriptionBackend]) -> None:
    """Register a backend factory. The factory is not called until needed."""
    _REGISTRY[name] = factory


def available_backends() -> list[str]:
    return sorted(_REGISTRY)


def get_backend(name: str | None = None) -> TranscriptionBackend:
    """Construct a backend by name.

    Defaults to local transcription. The public project must work with no API
    key and no account, so the default is never a cloud provider.
    """
    import os

    chosen = name or os.environ.get("SOCIAL_VIDEO_TRANSCRIBER") or "faster-whisper"
    chosen = chosen.strip().lower()
    _load_builtin_backends()
    if chosen not in _REGISTRY:
        known = ", ".join(available_backends()) or "<none>"
        raise BackendNotAvailableError(
            f"unknown transcription backend {chosen!r}. Available: {known}"
        )
    return _REGISTRY[chosen]()


def _load_builtin_backends() -> None:
    """Import the built-in backend modules, which self-register.

    Import errors are swallowed deliberately: an optional backend whose extra
    is not installed must not prevent the others from being listed. The reason
    it is unusable surfaces from ``validate_setup`` instead.
    """
    from importlib import import_module

    for module in ("social_video.transcribe.faster_whisper",):
        try:
            import_module(module)
        except ImportError:
            continue
