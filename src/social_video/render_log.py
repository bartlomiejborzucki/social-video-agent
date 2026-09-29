"""How long renders take on this machine, so the next one can be estimated.

"The preview will take about four minutes" is worth more to a user waiting on
an agent than a spinner. Render time depends on the machine, the renderer, the
quality and the pixels per second of output, so every finished render appends
one line to a local log and the estimate is the median rate of comparable
earlier renders, scaled to this one.

The log is local and holds no paths, titles or transcript text: only sizes,
durations and timings. ``SOCIAL_VIDEO_RENDER_LOG`` moves it, and ``off``
disables it.
"""

from __future__ import annotations

import json
import logging
import os
import statistics
from dataclasses import dataclass
from pathlib import Path

from social_video import __version__
from social_video.fsutil import utc_timestamp
from social_video.paths import app_home

log = logging.getLogger(__name__)

ENV = "SOCIAL_VIDEO_RENDER_LOG"
#: Comparable renders the estimate looks at, newest first.
SAMPLE = 20
#: The log is trimmed to this many lines when it grows past twice as many.
KEEP = 500


@dataclass(frozen=True)
class RenderEstimate:
    seconds: float
    #: How many earlier renders it is based on.
    samples: int

    def to_dict(self) -> dict[str, object]:
        return {"seconds": round(self.seconds, 1), "samples": self.samples}

    def describe(self) -> str:
        noun = "render" if self.samples == 1 else "renders"
        return f"about {_clock(self.seconds)} (from {self.samples} earlier {noun} here)"


def log_path() -> Path | None:
    override = os.environ.get(ENV, "").strip()
    if override.casefold() in ("off", "0", "false", "none"):
        return None
    if override:
        return Path(override).expanduser()
    return app_home() / "render-log.jsonl"


def record_render(
    *,
    renderer: str,
    quality: str,
    width: int,
    height: int,
    output_seconds: float,
    elapsed_seconds: float,
    motion_elements: int = 0,
    captions: bool = False,
) -> None:
    """Append one finished render. Never fails the render it describes."""
    path = log_path()
    if path is None or output_seconds <= 0 or elapsed_seconds <= 0:
        return
    entry = {
        "at": utc_timestamp(),
        "version": __version__,
        "renderer": renderer,
        "quality": quality,
        "width": width,
        "height": height,
        "output_seconds": round(output_seconds, 3),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "motion_elements": motion_elements,
        "captions": captions,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        _trim(path)
    except OSError as exc:
        log.debug("render log not written: %s", exc)


def read_renders(path: Path | None = None) -> list[dict]:
    """Every readable entry, oldest first. Damaged lines are skipped."""
    path = path or log_path()
    if path is None or not path.is_file():
        return []
    entries: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and _usable(entry):
            entries.append(entry)
    return entries


def estimate_render(
    *,
    renderer: str,
    quality: str,
    width: int,
    height: int,
    output_seconds: float,
    entries: list[dict] | None = None,
) -> RenderEstimate | None:
    """Median seconds per output-second-megapixel of comparable renders, scaled."""
    if output_seconds <= 0:
        return None
    history = read_renders() if entries is None else [e for e in entries if _usable(e)]
    comparable = [
        e for e in reversed(history) if e["renderer"] == renderer and e["quality"] == quality
    ][:SAMPLE]
    if not comparable:
        return None
    rates = [
        e["elapsed_seconds"] / (e["output_seconds"] * _megapixels(e["width"], e["height"]))
        for e in comparable
    ]
    work = output_seconds * _megapixels(width, height)
    return RenderEstimate(seconds=statistics.median(rates) * work, samples=len(comparable))


def _usable(entry: dict) -> bool:
    try:
        return (
            isinstance(entry["renderer"], str)
            and isinstance(entry["quality"], str)
            and float(entry["output_seconds"]) > 0
            and float(entry["elapsed_seconds"]) > 0
            and int(entry["width"]) > 0
            and int(entry["height"]) > 0
        )
    except (KeyError, TypeError, ValueError):
        return False


def _megapixels(width: int, height: int) -> float:
    return max(width * height, 1) / 1_000_000


def _trim(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) > 2 * KEEP:
        path.write_text("\n".join(lines[-KEEP:]) + "\n", encoding="utf-8")


def _clock(seconds: float) -> str:
    if seconds < 60:
        return f"{max(1, round(seconds))} s"
    minutes, secs = divmod(round(seconds), 60)
    return f"{minutes} min {secs:02d} s"
