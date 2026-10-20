"""Transcription as a cached, resumable stage."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from social_video.errors import ValidationError
from social_video.ffmpeg.probe import probe
from social_video.fingerprint import file_fingerprint, options_fingerprint
from social_video.paths import normalize_user_path
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.transcript import TokenType, Transcript, TranscriptToken
from social_video.transcribe.audio import extract_audio, guard_not_silent
from social_video.transcribe.base import (
    DEFAULT_BACKEND,
    BackendNotAvailableError,
    TranscriptionOptions,
    get_backend,
)
from social_video.transcribe.diarize import diarize, label_speakers, validate_diarization
from social_video.transcribe.normalize import synthesize_spacing
from social_video.transcribe.quality import assess_transcript
from social_video.workspace.layout import Workspace

log = logging.getLogger(__name__)


def source_id_for(path: str | Path, workspace: Workspace | None = None) -> str:
    """Stable, readable handle for a source file.

    The id the workspace's source manifest gives the file, so a recording
    added with `sources add --id` is transcribed under the name plans use;
    otherwise its file stem.
    """
    if workspace is not None and workspace.source_manifest.is_file():
        from social_video.schemas.source import SourceManifest
        from social_video.sources import id_for_path

        try:
            known = id_for_path(load_artifact(SourceManifest, workspace.source_manifest), path)
        except ValidationError:
            known = None
        if known is not None:
            return known
    return Path(path).stem


def transcribe_source(
    source: str | Path,
    workspace: Workspace,
    *,
    options: TranscriptionOptions | None = None,
    backend_name: str | None = None,
    force: bool = False,
) -> Transcript:
    """Transcribe one source, reusing a cached result when it is still valid.

    The cache is keyed on the source's content fingerprint *and* every option
    that could change the result, so changing the model, the language, or the
    audio track re-transcribes, while merely re-running does not.
    """
    src = normalize_user_path(source, must_exist=True)
    opts = options or TranscriptionOptions()
    workspace.ensure()

    info = probe(src)
    sid = source_id_for(src, workspace)
    fingerprint = file_fingerprint(src)
    out_path = workspace.transcript_for(sid, opts.audio_track)
    # Constructing a backend is cheap; heavy imports wait for transcribe().
    backend = get_backend(backend_name)

    # The cache is content-addressed on (source content, options, backend), so
    # switching model, language or backend and switching back does not
    # re-transcribe. The default backend keeps the name it always had, so
    # existing caches stay valid. The path in `transcripts/` is the readable
    # "current" view, published from the cache.
    key = options_fingerprint(**opts.cache_fields())
    suffix = "" if backend.name == DEFAULT_BACKEND else f".{backend.name}"
    cache_path = workspace.cache / "transcripts" / f"{sid}.{fingerprint[:16]}.{key}{suffix}.json"

    if not force:
        # The workspace copy is the one people correct (`captions fix`, a
        # refined passage, a hand edit), so it wins over the cache whenever it
        # still describes this file with these options.
        current = _load_if_valid(out_path, fingerprint, opts, provider=backend.name)
        if current is not None:
            log.info("using the workspace transcript %s", out_path.name)
            return current
        cached = _load_if_valid(cache_path, fingerprint, opts, provider=backend.name)
        if cached is not None:
            log.info("transcript cache hit: %s", cache_path.name)
            _publish(cached, out_path)
            return cached
        log.info("transcript cache miss: %s", src.name)

    ok, reason = backend.validate_setup()
    if not ok:
        raise BackendNotAvailableError(f"transcription backend {backend.name!r}: {reason}")
    if opts.diarize:
        ok, reason = validate_diarization()
        if not ok:
            raise BackendNotAvailableError(reason)

    # Temp audio lives inside the workspace cache, not the system temp dir: a
    # two-hour take is a few hundred megabytes of PCM, and the workspace is the
    # place the user already expects to find (and be able to clear) our scratch.
    with tempfile.TemporaryDirectory(dir=workspace.cache) as tmp:
        audio = extract_audio(src, Path(tmp) / f"{sid}.wav", audio_track=opts.audio_track)
        guard_not_silent(audio, source_name=src.name, audio_track=opts.audio_track)
        log.info("transcribing %s with %s/%s", src.name, backend.name, opts.model)
        transcript = backend.transcribe(
            audio,
            options=opts,
            source_id=sid,
            source_fingerprint=fingerprint,
            duration=info.duration,
        )
        if opts.diarize:
            log.info("diarizing %s", src.name)
            transcript = label_speakers(transcript, diarize(audio, num_speakers=opts.num_speakers))

    if not transcript.words:
        log.warning("%s produced no words; the track may not contain speech", src.name)
    elif not transcript.has_word_timestamps:
        # Cutting on word boundaries is the premise. Say so loudly rather than
        # silently producing an edit whose cuts land mid-word.
        log.warning(
            "%s returned word timings that look evenly distributed rather than aligned; "
            "cuts placed from this transcript may not land on real word boundaries",
            backend.name,
        )
    for warning in assess_transcript(transcript, requested_language=opts.language).warnings:
        log.warning("%s: %s", src.name, warning)

    save_artifact(transcript, cache_path)
    _publish(transcript, out_path)
    return transcript


def workspace_transcript(
    source: str | Path, workspace: Workspace, *, audio_track: int = 0, source_id: str | None = None
) -> Transcript | None:
    """The workspace transcript of ``source``, if it still describes that file.

    Whatever model made it: a corrected transcript is not worth less because
    a later command asked for a different default model.
    """
    src = normalize_user_path(source, must_exist=True)
    path = workspace.transcript_for(source_id or source_id_for(src, workspace), audio_track)
    if not path.is_file():
        return None
    try:
        transcript = load_artifact(Transcript, path)
    except ValidationError as exc:
        log.warning("ignoring unreadable workspace transcript %s: %s", path.name, exc)
        return None
    if transcript.audio_track != audio_track:
        return None
    if transcript.source_fingerprint != file_fingerprint(src):
        log.warning("%s was made from a different version of %s", path.name, src.name)
        return None
    return transcript


@dataclass(frozen=True)
class Refinement:
    transcript: Transcript
    path: Path
    removed: list[TranscriptToken]
    added: list[TranscriptToken]


def parse_span(text: str) -> tuple[float, float]:
    """``"51.0-56.5"`` as seconds."""
    try:
        start_text, end_text = text.split("-", 1)
        start, end = float(start_text), float(end_text)
    except ValueError:
        raise ValidationError(
            f"expected START-END in seconds, e.g. 51.0-56.5; got {text!r}"
        ) from None
    if start < 0 or end <= start:
        raise ValidationError(f"the span {text!r} must run forward from 0 or later")
    return start, end


def refine_transcript(
    source: str | Path,
    workspace: Workspace,
    start: float,
    end: float,
    *,
    options: TranscriptionOptions,
    backend_name: str | None = None,
) -> Refinement:
    """Re-transcribe one passage, usually with a larger model, and splice it in.

    The words whose middle falls inside ``[start, end]`` are replaced by the
    passage's own words, shifted onto the recording's clock; gaps are then
    re-synthesised over the whole stream, so the result is the same shape a
    full transcription would have. Only the workspace transcript changes: it is
    the copy every later stage reads.
    """
    src = normalize_user_path(source, must_exist=True)
    current = workspace_transcript(src, workspace, audio_track=options.audio_track)
    if current is None:
        raise ValidationError(
            f"{src.name} has no transcript in {workspace.transcripts} to refine; "
            "transcribe it first"
        )
    end = min(end, current.duration or end)
    if end - start < 0.2:
        raise ValidationError(f"the span {start:.2f}-{end:.2f}s is too short to transcribe")
    backend = get_backend(backend_name)
    ok, reason = backend.validate_setup()
    if not ok:
        raise BackendNotAvailableError(f"transcription backend {backend.name!r}: {reason}")
    opts = replace(options, language=options.language or current.language)
    with tempfile.TemporaryDirectory(dir=workspace.ensure().cache) as tmp:
        audio = extract_audio(
            src, Path(tmp) / "passage.wav", audio_track=opts.audio_track, start=start, end=end
        )
        log.info(
            "refining %s %.2f-%.2fs with %s/%s", src.name, start, end, backend.name, opts.model
        )
        passage = backend.transcribe(
            audio,
            options=opts,
            source_id=current.source_id,
            source_fingerprint=current.source_fingerprint,
            duration=end - start,
        )

    def inside(token: TranscriptToken) -> bool:
        # Only words wholly inside are replaced: a word the span's edge cuts
        # through is heard only in part by the passage, so it is kept as it was.
        return start - 1e-6 <= token.start and token.end <= end + 1e-6

    added = [
        token.model_copy(
            update={
                "start": round(min(end, token.start + start), 3),
                "end": round(min(end, token.end + start), 3),
            }
        )
        for token in passage.tokens
        if token.type is not TokenType.SPACING
    ]
    kept = [t for t in current.tokens if t.type is not TokenType.SPACING and not inside(t)]
    added = [t for t in added if inside(t) and not any(_overlaps(t, k) for k in kept)]
    added = _drop_repeats_at_edges(added, kept, start, end)
    added = _join_sentence(added, kept, end)
    removed = [t for t in current.tokens if t.type is not TokenType.SPACING and inside(t)]
    segments = [
        segment
        for segment in current.segments
        if not (start <= segment.start and segment.end <= end)
    ]
    segments += [
        segment.model_copy(
            update={
                "start": round(segment.start + start, 3),
                "end": round(min(end, segment.end + start), 3),
                "tokens": [],
            }
        )
        for segment in passage.segments
    ]
    note = dict(current.provider_options)
    note[f"refined {start:.2f}-{end:.2f}"] = (
        f"{passage.provider}/{passage.provider_model or opts.model}"
    )
    refined = current.model_copy(
        update={
            "tokens": synthesize_spacing([*kept, *added]),
            "segments": sorted(segments, key=lambda seg: seg.start),
            "provider_options": note,
        }
    )
    refined = Transcript.model_validate(refined.model_dump())
    path = workspace.transcript_for(current.source_id, current.audio_track)
    save_artifact(refined, path)
    return Refinement(transcript=refined, path=path, removed=removed, added=added)


def _overlaps(token: TranscriptToken, other: TranscriptToken) -> bool:
    """More than half of ``token`` lies under ``other``."""
    shared = min(token.end, other.end) - max(token.start, other.start)
    return shared > 0.5 * max(token.duration, 1e-3)


def _drop_repeats_at_edges(
    added: list[TranscriptToken], kept: list[TranscriptToken], start: float, end: float
) -> list[TranscriptToken]:
    """A passage word that repeats the kept word right across its edge is one word.

    The passage hears the edge word whole while the transcript keeps the
    copy that straddles the edge; both would caption "długo długo".
    """

    def key(token: TranscriptToken) -> str:
        return "".join(ch for ch in token.text.casefold() if ch.isalnum())

    words = [t for t in added if t.type is TokenType.WORD]
    if not words:
        return added
    first, last = words[0], words[-1]
    # Only a kept word cut by the span's edge can be the same word heard twice;
    # a repeat the speaker made (a false start) lies wholly outside.
    before = [k for k in kept if k.type is TokenType.WORD and k.start < start < k.end]
    after = [k for k in kept if k.type is TokenType.WORD and k.start < end < k.end]
    drop: set[int] = set()
    if before and key(before[-1]) == key(first) and first.start - before[-1].end < 0.3:
        drop.add(id(first))
    if after and key(after[0]) == key(last) and after[0].start - last.end < 0.3:
        drop.add(id(last))
    return [t for t in added if id(t) not in drop]


def _join_sentence(
    added: list[TranscriptToken], kept: list[TranscriptToken], end: float
) -> list[TranscriptToken]:
    """Drop the full stop a passage puts on its last word when the sentence goes on.

    A passage cut mid-sentence is transcribed as if it ended there; the word
    after it, starting lower case, says it did not.
    """
    words = [t for t in added if t.type is TokenType.WORD]
    following = [t for t in kept if t.type is TokenType.WORD and t.start >= end - 1e-6]
    if not words or not following or not following[0].text[:1].islower():
        return added
    last = words[-1]
    trimmed = last.text.rstrip(".!?…")
    if trimmed == last.text or not trimmed:
        return added
    return [t.model_copy(update={"text": trimmed}) if t is last else t for t in added]


def _publish(transcript: Transcript, out_path: Path) -> None:
    """Write the current transcript to its readable workspace path."""
    save_artifact(transcript, out_path)


def _load_if_valid(
    path: Path, fingerprint: str, options: TranscriptionOptions, *, provider: str
) -> Transcript | None:
    """Return the cached transcript only if it was produced from these inputs."""
    if not path.is_file():
        return None
    try:
        cached = load_artifact(Transcript, path)
    except ValidationError as exc:
        log.info("ignoring unreadable cached transcript %s: %s", path.name, exc)
        return None

    if cached.source_fingerprint != fingerprint:
        return None
    if cached.provider != provider:
        return None
    if cached.audio_track != options.audio_track:
        return None
    if options.language and cached.language != options.language:
        return None
    if cached.provider_model and cached.provider_model != options.model:
        return None
    return cached
