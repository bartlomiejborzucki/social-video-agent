"""Re-encoding a delivered video to fit a size limit, with its sound untouched.

Some routes to a phone refuse files over a size (30 MB through the bridge
to the computer). The picture is re-encoded in two passes at the bitrate the
limit leaves after the audio; the audio stream is copied, not re-encoded, so
its timing is the original's to the sample and A/V sync cannot move.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from social_video.errors import ValidationError
from social_video.ffmpeg.probe import probe
from social_video.ffmpeg.run import run_ffmpeg, run_ffprobe_json
from social_video.fsutil import atomic_copy

#: Share of the limit the streams may fill; the rest is container overhead
#: and the encoder's overshoot.
FILL = 0.94
#: Below this the picture is not worth delivering; say so instead.
MIN_VIDEO_KBPS = 400
ATTEMPTS = 3


@dataclass(frozen=True)
class SizeFit:
    limit_bytes: int
    before_bytes: int
    after_bytes: int
    video_kbps: int | None
    #: Sound against picture, the encode versus the file it replaced.
    av_error_s: float | None = None

    @property
    def reencoded(self) -> bool:
        return self.video_kbps is not None


def audio_bytes(path: Path) -> int:
    """Bytes of the first audio stream's packets."""
    packets = run_ffprobe_json(
        ["-select_streams", "a:0", "-show_entries", "packet=size", str(path)],
        desc=f"measure the audio of {path.name}",
    ).get("packets", [])
    return sum(int(p.get("size", 0)) for p in packets)


def video_bitrate_for(limit_bytes: int, duration: float, audio: int) -> int:
    """The video bitrate, in kbit/s, that leaves room for the audio."""
    budget = limit_bytes * FILL - audio
    return int(budget * 8 / max(duration, 0.1) / 1000)


def fit_to_size(path: Path, limit_bytes: int) -> SizeFit:
    """Replace ``path`` with a two-pass encode under ``limit_bytes``, if it is over."""
    before = path.stat().st_size
    if before <= limit_bytes:
        return SizeFit(limit_bytes, before, before, None)
    info = probe(path)
    if info.video is None:
        raise ValidationError(f"{path.name} has no video to re-encode")
    audio = audio_bytes(path)
    kbps = video_bitrate_for(limit_bytes, info.duration, audio)
    with tempfile.TemporaryDirectory(dir=path.parent, prefix=".fit-") as tmp:
        work = Path(tmp)
        for _attempt in range(ATTEMPTS):
            if kbps < MIN_VIDEO_KBPS:
                raise ValidationError(
                    f"{path.name} lasts {info.duration:.1f}s; under "
                    f"{limit_bytes / 1e6:.0f} MB the picture would get {max(kbps, 0)} kbit/s, "
                    f"below the {MIN_VIDEO_KBPS} kbit/s worth delivering. Raise --max-size-mb "
                    "or shorten the edit."
                )
            staged = _encode(path, work, kbps, info.video.nominal_frame_rate)
            after = staged.stat().st_size
            if after <= limit_bytes:
                error = _sync_error(path, staged, info.video.nominal_frame_rate)
                atomic_copy(staged, path)
                return SizeFit(limit_bytes, before, after, kbps, error)
            kbps = int(kbps * limit_bytes * FILL / after)
    raise ValidationError(
        f"{path.name} stayed over {limit_bytes / 1e6:.0f} MB after {ATTEMPTS} encodes"
    )


def _sync_error(original: Path, fitted: Path, fps: str) -> float | None:
    """Refuse an encode that moved the sound against the picture."""
    from social_video.qa.av_sync import AV_TOLERANCE, measure_sync

    error = measure_sync(original, fitted, fps=fps).av_error
    if error is not None and abs(error) > AV_TOLERANCE:
        raise ValidationError(
            f"re-encoding {original.name} to fit moved the sound {error * 1000:+.0f} ms "
            "against the picture; the delivery was not replaced"
        )
    return error


def _encode(source: Path, work: Path, kbps: int, fps: str) -> Path:
    log = work / "x264"
    common = [
        "-y",
        "-v",
        "error",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-b:v",
        f"{kbps}k",
        "-pix_fmt",
        "yuv420p",
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-r",
        fps,
        "-passlogfile",
        str(log),
    ]
    run_ffmpeg([*common, "-pass", "1", "-an", "-f", "null", "-"], desc="size fit, pass 1")
    staged = work / "fitted.mp4"
    run_ffmpeg(
        [
            *common,
            "-pass",
            "2",
            "-map",
            "0:a:0",
            "-c:a",
            "copy",
            "-tag:v",
            "avc1",
            "-movflags",
            "+faststart",
            str(staged),
        ],
        desc="size fit, pass 2",
        timeout=14400,
    )
    return staged
