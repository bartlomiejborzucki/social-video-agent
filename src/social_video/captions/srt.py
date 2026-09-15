"""SRT and VTT output, for handing captions to other tools."""

from __future__ import annotations

from pathlib import Path

from social_video.schemas.captions import CaptionTrack


def _srt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    whole = int(secs)
    millis = round((secs - whole) * 1000)
    if millis == 1000:  # rounding can carry
        whole, millis = whole + 1, 0
    return f"{int(hours):02d}:{int(minutes):02d}:{whole:02d},{millis:03d}"


def render_srt(track: CaptionTrack) -> str:
    blocks = []
    for number, cue in enumerate(sorted(track.cues, key=lambda c: c.start), start=1):
        blocks.append(f"{number}\n{_srt_time(cue.start)} --> {_srt_time(cue.end)}\n{cue.text}\n")
    # SRT conventionally uses CRLF; libass and every player accept it.
    return "\r\n".join("\r\n".join(b.splitlines()) for b in blocks) + "\r\n"


def write_srt(track: CaptionTrack, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_srt(track), encoding="utf-8", newline="")
    return path


def render_vtt(track: CaptionTrack) -> str:
    lines = ["WEBVTT", ""]
    for cue in sorted(track.cues, key=lambda c: c.start):
        start = _srt_time(cue.start).replace(",", ".")
        end = _srt_time(cue.end).replace(",", ".")
        lines += [f"{start} --> {end}", cue.text, ""]
    return "\n".join(lines)


def write_vtt(track: CaptionTrack, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_vtt(track), encoding="utf-8")
    return path
