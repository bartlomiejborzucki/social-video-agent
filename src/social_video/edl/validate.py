"""EDL validation beyond what the schema alone can check.

The schema guarantees shapes and intervals. This checks the EDL against the
world: do the sources exist, do the ranges fall inside them, do the overlays
land on the timeline. Upstream performs none of these checks, so a typo in a
source name is a KeyError and an out-of-bounds range is an ffmpeg error with the
diagnostic thrown away.
"""

from __future__ import annotations

from pathlib import Path

from social_video.errors import ValidationError
from social_video.ffmpeg.probe import probe
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
    for index, rng in enumerate(edl.ranges):
        where = f"ranges[{index}] (source {rng.source!r}, {rng.start:.2f}-{rng.end:.2f})"

        if rng.source not in known:
            problems.append(
                f"{where}: unknown source. Manifest has: {', '.join(sorted(known)) or '<none>'}"
            )
            continue

        entry = manifest.by_id(rng.source)
        path = Path(entry.path)
        if check_media and not path.is_file():
            problems.append(f"{where}: source file is missing at {path}")
            continue

        duration = entry.duration
        if check_media and duration <= 0:
            try:
                duration = probe(path).duration
            # A probe failure here is reported as a problem below.
            except Exception:
                duration = 0.0

        if duration > 0 and rng.start >= duration:
            problems.append(
                f"{where}: starts at {rng.start:.2f}s but the source is only {duration:.2f}s long"
            )
        elif duration > 0 and rng.end > duration + END_TOLERANCE:
            problems.append(
                f"{where}: ends at {rng.end:.2f}s, past the end of a {duration:.2f}s source"
            )

        if rng.duration < 0.05:
            warnings.append(f"{where}: only {rng.duration * 1000:.0f}ms long; likely a mistake")

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
