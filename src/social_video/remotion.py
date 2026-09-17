"""Safe bridge to the repository's pinned Remotion compositor."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from social_video.errors import RemotionError, ToolNotFoundError, ValidationError
from social_video.ffmpeg.probe import probe
from social_video.ffmpeg.run import run_ffmpeg
from social_video.schemas.brand import CaptionStyle
from social_video.schemas.captions import CaptionTrack
from social_video.schemas.motion import MotionPlan


def render_motion_design(
    base_video: Path,
    output: Path,
    plan: MotionPlan,
    *,
    duration_in_frames: int,
    fps: float,
    width: int,
    height: int,
    staging_root: Path,
    captions: CaptionTrack | None = None,
    caption_style: CaptionStyle | None = None,
    logo_path: Path | None = None,
    logo_usage: str = "none",
    safe_margins: dict[str, float] | None = None,
) -> Path:
    if base_video.resolve() == output.resolve():
        raise ValidationError("Remotion output must not overwrite its technical base video")
    for element in plan.elements:
        if element.end * fps > duration_in_frames + 1:
            raise ValidationError(
                f"motion element {element.type.value!r} ends after the video timeline"
            )
    node = shutil.which("node")
    if node is None:
        raise ToolNotFoundError(
            "Node.js was not found inside the WSL/Linux environment. Remotion is the "
            "default renderer; run scripts/wsl/bootstrap.sh and retry."
        )
    project_root = Path(__file__).resolve().parents[2]
    script = project_root / "scripts" / "remotion" / "render.mjs"
    entry = project_root / "remotion" / "index.ts"
    if not (project_root / "node_modules" / "remotion").is_dir():
        raise ToolNotFoundError(
            "Remotion dependencies are not installed in this WSL checkout. Run "
            "`npm ci`, then `npx remotion browser ensure`, and retry."
        )
    if not script.is_file() or not entry.is_file():
        raise ValidationError("the repository Remotion compositor is incomplete")
    font: Path | None = None
    font_source = None
    if plan.font_path:
        font = Path(plan.font_path).expanduser().resolve()
        allowed_font_types = {".ttf", ".otf", ".woff", ".woff2"}
        if not font.is_file() or font.suffix.casefold() not in allowed_font_types:
            raise ValidationError(
                "motion-plan font_path must be an existing .ttf, .otf, .woff, or .woff2 file"
            )
        if font.stat().st_size > 20 * 1024 * 1024:
            raise ValidationError("motion-plan font_path exceeds the 20 MB safety limit")
        font_source = f"brand-font{font.suffix.casefold()}"
    logo_source = None
    if logo_path is not None:
        logo_path = logo_path.expanduser().resolve()
        if not logo_path.is_file():
            raise ValidationError(f"configured logo does not exist: {logo_path}")
        logo_source = f"brand-logo{logo_path.suffix.casefold()}"
    work = staging_root / f"remotion-{uuid4().hex}"
    public = work / "public"
    try:
        public.mkdir(parents=True, exist_ok=False)
        # Remotion's bundler deliberately does not carry symlinks from publicDir
        # into the served bundle. Copy into the Linux-side staging directory;
        # this also keeps mounted Windows sources read-only and avoids rendering
        # directly across /mnt/c.
        shutil.copy2(base_video, public / "base.mp4")
        if font is not None and font_source is not None:
            shutil.copy2(font, public / font_source)
        if logo_path is not None and logo_source is not None:
            shutil.copy2(logo_path, public / logo_source)
        props = {
            "source": "base.mp4",
            "durationInFrames": duration_in_frames,
            "fps": fps,
            "width": width,
            "height": height,
            "accentColor": plan.accent_color,
            "textColor": plan.text_color,
            "backgroundColor": plan.background_color,
            "fontFamily": plan.font_family,
            "fontSource": font_source,
            "elements": [
                item.model_dump(mode="json", exclude={"schema_version"}) for item in plan.elements
            ],
            "captions": [
                cue.model_dump(mode="json", exclude={"schema_version", "words"})
                for cue in (captions.cues if captions else [])
            ],
            "captionStyle": (
                caption_style.model_dump(mode="json", exclude={"schema_version"})
                if caption_style
                else None
            ),
            "logoSource": logo_source,
            "logoUsage": logo_usage,
            "safeMargins": safe_margins or {"top": 6, "right": 6, "bottom": 12, "left": 6},
        }
        props_path = work / "props.json"
        props_path.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
        staged = work / "rendered.mp4"
        proc = subprocess.run(
            [node, str(script), str(entry), str(public), str(props_path), str(staged)],
            cwd=project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=14400,
            check=False,
        )
        if proc.returncode != 0 or not staged.is_file():
            detail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-30:])
            raise RemotionError(f"Remotion render failed (exit {proc.returncode}):\n{detail}")
        _verify_staged_output(
            staged,
            duration_in_frames=duration_in_frames,
            fps=fps,
            width=width,
            height=height,
        )
        _publish(staged, output)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return output


def _verify_staged_output(
    staged: Path,
    *,
    duration_in_frames: int,
    fps: float,
    width: int,
    height: int,
) -> None:
    """Reject an incomplete compositor result before it gets its final name."""
    info = probe(staged)
    expected_duration = duration_in_frames / fps
    if info.video is None or info.video.codec != "h264":
        raise RemotionError("Remotion staging output does not contain H.264 video")
    if info.video.display_size != (width, height):
        raise RemotionError(
            f"Remotion staging output is {info.video.display_size}, expected {(width, height)}"
        )
    if info.video.nb_frames != duration_in_frames:
        raise RemotionError(
            f"Remotion staging output has {info.video.nb_frames} frames, "
            f"expected {duration_in_frames}"
        )
    if abs(info.duration - expected_duration) > max(2 / fps, 2 * 1024 / 48000):
        raise RemotionError(
            f"Remotion staging output duration is {info.duration:.3f}s, "
            f"expected {expected_duration:.3f}s"
        )
    if not info.audio:
        raise RemotionError("Remotion staging output has no audio stream")
    audio = info.audio[0]
    if audio.codec != "aac" or audio.sample_rate != 48000 or audio.channels != 2:
        raise RemotionError(
            "Remotion staging audio must be AAC-LC stereo at 48 kHz; "
            f"got {audio.codec}, {audio.channels} channel(s), {audio.sample_rate} Hz"
        )
    run_ffmpeg(
        [
            "-v",
            "error",
            "-i",
            str(staged),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-f",
            "null",
            "-",
        ],
        desc="fully decode Remotion staging output",
        timeout=3600,
    )


def _publish(staged: Path, output: Path) -> None:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(f".{output.name}.{uuid4().hex}.partial")
    try:
        shutil.copy2(staged, partial)
        with partial.open("rb") as handle:
            os.fsync(handle.fileno())
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
