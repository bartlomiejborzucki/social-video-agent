"""Diagnostic images for targeted visual inspection.

Generated only where the mechanical checks point, or where the agent explicitly
asks. Extracting frames across a whole video and feeding them to a vision model
is slow, expensive, and mostly redundant with checks that are exact.

One ffmpeg invocation produces the whole sheet. Upstream spawns one ffmpeg per
frame, so a single diagnostic pass over a 20-cut video costs over 200 processes.
"""

from __future__ import annotations

from pathlib import Path

from social_video.ffmpeg.probe import probe
from social_video.ffmpeg.run import run_ffmpeg


def contact_sheet(
    video: Path,
    output: Path,
    *,
    start: float = 0.0,
    end: float | None = None,
    columns: int = 5,
    rows: int = 2,
    tile_width: int = 320,
) -> Path:
    """Render an evenly sampled grid of frames from a time range."""
    info = probe(video)
    stop = min(end if end is not None else info.duration, info.duration)
    begin = max(0.0, min(start, max(0.0, stop - 0.01)))
    span = max(stop - begin, 0.04)
    count = max(1, columns * rows)

    # Sample at a rate that yields exactly `count` frames across the span.
    rate = count / span
    output.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-y",
            "-ss",
            f"{begin:.4f}",
            "-t",
            f"{span:.4f}",
            "-i",
            str(video),
            "-vf",
            f"fps={rate:.6f},scale={tile_width}:-2,tile={columns}x{rows}:padding=4:color=black",
            "-frames:v",
            "1",
            "-update",
            "1",
            str(output),
        ],
        desc=f"contact sheet for {video.name}",
        timeout=900,
    )
    return output


def boundary_sheets(
    video: Path,
    boundaries: list[float],
    out_dir: Path,
    *,
    window: float = 0.6,
) -> list[Path]:
    """One small sheet centred on each cut, which is where splices go wrong."""
    made: list[Path] = []
    for index, at in enumerate(boundaries):
        path = out_dir / f"cut_{index:02d}_{at:07.2f}s.png"
        contact_sheet(
            video,
            path,
            start=max(0.0, at - window),
            end=at + window,
            columns=6,
            rows=1,
            tile_width=240,
        )
        made.append(path)
    return made
