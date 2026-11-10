"""SRT and VTT output, for handing captions to other tools."""

from __future__ import annotations

from pathlib import Path

from social_video.fsutil import atomic_write_text
from social_video.schemas.captions import CaptionTrack


def _srt_time(seconds: float) -> str:
    # Whole milliseconds first, so rounding carries all the way up.
    total = round(max(0.0, seconds) * 1000)
    rest, millis = divmod(total, 1000)
    rest, secs = divmod(rest, 60)
    hours, minutes = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def render_srt(track: CaptionTrack) -> str:
    blocks = []
    for number, cue in enumerate(sorted(track.cues, key=lambda c: c.start), start=1):
        lines = [str(number), f"{_srt_time(cue.start)} --> {_srt_time(cue.end)}"]
        blocks.append("\r\n".join(lines + cue.text.splitlines()))
    # SRT conventionally uses CRLF; libass and every player accept it. A blank
    # line ends each block: without it platforms reject the file.
    return "".join(block + "\r\n\r\n" for block in blocks)


def write_srt(track: CaptionTrack, path: Path) -> Path:
    return atomic_write_text(path, render_srt(track), newline="")


def render_vtt(track: CaptionTrack) -> str:
    lines = ["WEBVTT", ""]
    for cue in sorted(track.cues, key=lambda c: c.start):
        start = _srt_time(cue.start).replace(",", ".")
        end = _srt_time(cue.end).replace(",", ".")
        lines += [f"{start} --> {end}", cue.text, ""]
    return "\n".join(lines)


def write_vtt(track: CaptionTrack, path: Path) -> Path:
    return atomic_write_text(path, render_vtt(track))
