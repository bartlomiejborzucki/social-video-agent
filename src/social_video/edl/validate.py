"""EDL validation beyond what the schema alone can check.

The schema guarantees shapes and intervals. This checks the EDL against the
world: do the sources exist, do the ranges fall inside them, do the overlays
land on the timeline. Upstream performs none of these checks, so a typo in a
source name is a KeyError and an out-of-bounds range is an ffmpeg error with the
diagnostic thrown away.
"""

from __future__ import annotations

from pathlib import Path

from social_video.errors import FFmpegError, ValidationError
from social_video.ffmpeg.probe import MediaInfo, probe
from social_video.schemas.edl import EDL
from social_video.schemas.source import SourceManifest

#: How far past the end of a source a range may reach before we complain.
#: Container durations are approximate, and an EDL derived from a transcript can
#: legitimately land a few frames beyond the reported end.
END_TOLERANCE = 0.25


def validate_edl(
    edl: EDL,
    manifest: SourceManifest,
    *,
    check_media: bool = True,
) -> list[str]:
    """Validate an EDL. Returns warnings; raises on anything unrenderable."""
    problems: list[str] = []
    warnings: list[str] = []

    known = set(manifest.ids)
    probed: dict[Path, MediaInfo | FFmpegError] = {}

    def probe_once(path: Path) -> MediaInfo | FFmpegError:
        # One probe per file, however many ranges use it. A file ffprobe cannot
        # read is a problem with this EDL's input, reported as one; a missing
        # ffprobe is not caught here and surfaces as the tool error it is.
        if path not in probed:
            try:
                probed[path] = probe(path)
            except FFmpegError as exc:
                probed[path] = exc
        return probed[path]

    for index, rng in enumerate(edl.ranges):
        where = f"ranges[{index}]"
        uses = (
            (
                "video",
                rng.effective_video_source,
                rng.effective_video_start,
                rng.visual_content_end,
            ),
            (
                "audio",
                rng.effective_audio_source,
                rng.effective_audio_start,
                rng.effective_audio_end,
            ),
        )
        optional_uses: list[tuple[str, str, float, float]] = []
        if rng.secondary_video_source is not None:
            optional_uses.append(
                (
                    "secondary video",
                    rng.secondary_video_source,
                    rng.secondary_video_start or 0.0,
                    rng.secondary_video_end or 0.0,
                )
            )
        if rng.end_card_source is not None:
            optional_uses.append(
                (
                    "end card",
                    rng.end_card_source,
                    rng.end_card_start or 0.0,
                    rng.end_card_end or 0.0,
                )
            )
        for kind, source_id, start, end in (*uses, *optional_uses):
            detail = f"{where} ({kind} source {source_id!r}, {start:.2f}-{end:.2f})"
            if source_id not in known:
                problems.append(
                    f"{detail}: unknown source. Manifest has: "
                    f"{', '.join(sorted(known)) or '<none>'}"
                )
                continue
            entry = manifest.by_id(source_id)
            path = Path(entry.path)
            if check_media and not path.is_file():
                problems.append(f"{detail}: source file is missing at {path}")
                continue
            info = probe_once(path) if check_media else None
            if isinstance(info, FFmpegError):
                problems.append(f"{detail}: source could not be probed: {info}")
                continue
            duration = entry.duration
            if info is not None and duration <= 0:
                duration = info.duration
            if duration > 0 and start >= duration:
                problems.append(
                    f"{detail}: starts at {start:.2f}s but the source is only {duration:.2f}s long"
                )
            elif duration > 0 and end > duration + END_TOLERANCE:
                problems.append(
                    f"{detail}: ends at {end:.2f}s, past the end of a {duration:.2f}s source"
                )
            if info is not None:
                if kind in {"video", "secondary video", "end card"} and info.video is None:
                    problems.append(f"{detail}: source has no video stream")
                if kind == "audio" and rng.audio_source is not None and not info.has_audio:
                    problems.append(f"{detail}: explicit audio_source has no audio stream")

        if rng.output_duration < 0.05:
            warnings.append(
                f"{where}: only {rng.output_duration * 1000:.0f}ms long; likely a mistake"
            )

    total = edl.total_duration
    for index, overlay in enumerate(edl.overlays):
        where = f"overlays[{index}] ({overlay.file})"
        if check_media and not Path(overlay.file).is_file():
            problems.append(f"{where}: file not found")
        if overlay.start_in_output >= total:
            problems.append(
                f"{where}: starts at {overlay.start_in_output:.2f}s, past the end of a "
                f"{total:.2f}s timeline"
            )
        elif overlay.end_in_output > total + 0.05:
            warnings.append(
                f"{where}: runs {overlay.end_in_output - total:.2f}s past the end of the "
                f"timeline and will be truncated"
            )

    if edl.captions and check_media and not Path(edl.captions).is_file():
        problems.append(f"captions: file not found at {edl.captions}")

    if problems:
        raise ValidationError(
            "This EDL cannot be rendered:\n" + "\n".join(f"  - {p}" for p in problems)
        )
    return warnings
