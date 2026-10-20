"""Safe bridge to the pinned Remotion compositor."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from social_video.captions.features import (
    CAPTION_LAYOUT_ESTIMATED,
    CAPTION_LAYOUT_MEASURED,
    PUNCH_IN,
    SCENE_FRAME,
    TRANSITIONS,
    caption_features,
    highlight_possible,
)
from social_video.captions.fit import CaptionLayout, layout_captions
from social_video.errors import RemotionError, ToolNotFoundError, ValidationError
from social_video.ffmpeg.probe import probe
from social_video.ffmpeg.run import run_ffmpeg
from social_video.fsutil import atomic_copy
from social_video.imaging import load_image
from social_video.motion.layout import (
    continues,
    framing_label,
    labels,
    scene_frame_geometry,
    tab_font_px,
)
from social_video.remotion_runtime import locate_runtime
from social_video.schemas.brand import CaptionCase, CaptionStyle
from social_video.schemas.captions import CaptionTrack
from social_video.schemas.motion import MotionElementType, MotionPlan


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
    label_style: str = "chip",
    secondary_colour: str = "#1F2430",
) -> tuple[Path, list[str], CaptionLayout | None]:
    if base_video.resolve() == output.resolve():
        raise ValidationError("Remotion output must not overwrite its technical base video")
    plates: dict[str, Path] = {}
    if logo_path is None and any(e.type is MotionElementType.LOGO_REVEAL for e in plan.elements):
        raise ValidationError("a logo_reveal needs a logo; set logo_file in the project config")
    for transition in plan.transitions:
        if (transition.at + transition.duration / 2) * fps > duration_in_frames + 1:
            raise ValidationError(f"transition at {transition.at:.2f}s runs past the video end")
    for punch in plan.punch_ins:
        if punch.end * fps > duration_in_frames + 1:
            raise ValidationError(f"punch-in at {punch.start:.2f}s ends after the video timeline")
    for index, element in enumerate(plan.elements):
        if element.end * fps > duration_in_frames + 1:
            raise ValidationError(
                f"motion element {element.type.value!r} ends after the video timeline"
            )
        # Validate the plan itself before the toolchain, so a bad plate is
        # reported as a plan problem rather than as a missing Node install.
        if element.image_asset:
            plate = Path(element.image_asset).expanduser().resolve()
            if plate.suffix.casefold() == ".svg":
                # A vector sticker: the browser draws it; check it is a file.
                if not plate.is_file() or plate.stat().st_size > 2 * 1024 * 1024:
                    raise ValidationError(f"sticker image {plate} is missing or over 2 MB")
            else:
                load_image(plate, label=f"motion element {index} image_asset")
            plates[element.image_asset] = plate
    plate_sources = {
        asset: f"motion-plate-{index}{path.suffix.casefold()}"
        for index, (asset, path) in enumerate(sorted(plates.items()))
    }
    emoji = None
    if any(e.type is MotionElementType.STICKER and e.emoji for e in plan.elements):
        from social_video.motion.stickers import emoji_font

        emoji = emoji_font()
        if emoji is None:
            raise ToolNotFoundError(
                "stickers draw emoji only from Noto Color Emoji (SIL OFL); install it with "
                "`sudo apt install fonts-noto-color-emoji`"
            )
    node = shutil.which("node")
    if node is None:
        raise ToolNotFoundError(
            "Node.js was not found inside the WSL/Linux environment. Remotion is the "
            "default renderer; run scripts/wsl/bootstrap.sh and retry."
        )
    runtime = locate_runtime()
    if runtime is None:
        raise ValidationError("this build does not include the Remotion compositor")
    if not runtime.dependencies_installed:
        raise ToolNotFoundError(f"Remotion dependencies are not installed. {runtime.install_hint}")
    project_root = runtime.root
    script = runtime.script
    entry = runtime.entry
    if not script.is_file() or not entry.is_file():
        raise ValidationError("the Remotion compositor is incomplete")
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
    highlight = highlight_possible(caption_style, captions)
    features = caption_features(caption_style, captions, highlight=highlight, animated=True)
    if plan.punch_ins:
        features.append(PUNCH_IN)
    if plan.transitions:
        features.append(TRANSITIONS)
    # Lay the captions out before touching the filesystem or the toolchain, so
    # a cue that cannot be drawn in full is reported as a contract problem
    # rather than discovered as clipped text in a finished render.
    layout = (
        layout_captions(
            list(captions.cues),
            caption_style,
            width=width,
            height=height,
            safe_margins=safe_margins,
            font_file=font,
        )
        if caption_style is not None and captions is not None and captions.cues
        else None
    )
    if layout is not None:
        features.append(CAPTION_LAYOUT_MEASURED if layout.measured else CAPTION_LAYOUT_ESTIMATED)
    frame = (
        scene_frame_geometry(caption_style, width=width, height=height, safe_margins=safe_margins)
        if label_style == "scene_frame" and caption_style is not None and labels(plan.elements)
        else None
    )
    if frame is not None:
        features.append(SCENE_FRAME)
    caption_payload = _caption_payload(layout, captions, caption_style, highlight=highlight)
    if frame is not None:
        for item in caption_payload:
            item["framed"] = framing_label(item["start"], item["end"], plan.elements) is not None
    # Each title gets the size that fits the tab; a title that cannot fit at a
    # readable size stops the render here, before the toolchain starts.
    tab_sizes = (
        {e.text: tab_font_px(e.text, frame, font) for e in labels(plan.elements)}
        if frame is not None
        else {}
    )
    # Node runs with the compositor as its working directory, so every path it
    # is handed must be absolute.
    work = staging_root.resolve() / f"remotion-{uuid4().hex}"
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
        for asset, name in plate_sources.items():
            shutil.copy2(plates[asset], public / name)
        if emoji is not None:
            shutil.copy2(emoji.path, public / f"emoji-font{emoji.path.suffix.casefold()}")
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
                _element_payload(
                    item,
                    plan,
                    plate_sources,
                    width=width,
                    height=height,
                    font=font,
                    tab_sizes=tab_sizes,
                )
                for item in plan.elements
            ],
            "captions": caption_payload,
            "captionStyle": (
                caption_style.model_dump(mode="json", exclude={"schema_version"})
                if caption_style
                else None
            ),
            "captionLayout": (
                {
                    "box_width_px": round(layout.box_width_px, 2),
                    "text_width_px": round(layout.text_width_px, 2),
                    "padding_x": layout.padding_x,
                    "padding_top": layout.padding_top,
                    "padding_bottom": layout.padding_bottom,
                    "line_height": layout.line_height,
                }
                if layout is not None
                else None
            ),
            "transitions": [
                item.model_dump(mode="json", exclude={"schema_version"})
                for item in plan.transitions
            ],
            "style": plan.style,
            "punchIns": [
                item.model_dump(mode="json", exclude={"schema_version"}) for item in plan.punch_ins
            ],
            "shakes": [
                item.model_dump(mode="json", exclude={"schema_version"}) for item in plan.shakes
            ],
            "emojiFontSource": (
                f"emoji-font{emoji.path.suffix.casefold()}" if emoji is not None else None
            ),
            "logoSource": logo_source,
            "logoUsage": logo_usage,
            "safeMargins": safe_margins or {"top": 6, "right": 6, "bottom": 12, "left": 6},
            "secondaryColor": secondary_colour,
            "labelStyle": label_style,
            "sceneFrame": frame.as_props() if frame is not None else None,
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
        muxed = work / "muxed.mp4"
        mux_base_audio(staged, base_video, muxed)
        _verify_staged_output(
            muxed,
            duration_in_frames=duration_in_frames,
            fps=fps,
            width=width,
            height=height,
        )
        _publish(muxed, output)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return output, features, layout


def _element_payload(
    item,
    plan: MotionPlan,
    plate_sources: dict[str, str],
    *,
    width: int = 1080,
    height: int = 1920,
    font: Path | None = None,
    tab_sizes: dict[str, float] | None = None,
) -> dict:
    """One element as the compositor reads it, its placement resolved."""
    payload = item.model_dump(mode="json", exclude={"schema_version", "image_asset"})
    payload["image_source"] = plate_sources.get(item.image_asset or "")
    payload["position"] = item.placement.value if item.placement else None
    if item.type is MotionElementType.LABEL:
        previous = continues(item, plan.elements)
        payload["continues"] = previous.text if previous is not None else None
        sizes = tab_sizes or {}
        payload["tab_font_px"] = sizes.get(item.text)
        payload["continues_font_px"] = sizes.get(previous.text) if previous is not None else None
    if item.type is MotionElementType.END_CARD:
        payload["fitted"] = end_card_text(item, width=width, height=height, font=font)
    return payload


def end_card_text(item, *, width: int, height: int, font: Path | None) -> dict:
    """The end card's lines and sizes, measured, with links kept whole."""
    from social_video.motion.text_fit import fit_text

    u = height / 1920
    max_width = min(900 * u, width - 180 * u)
    title = fit_text(
        item.text, max_width=max_width, base_px=round(72 * u), min_px=round(30 * u),
        font_file=font, max_lines=4,
    )  # fmt: skip
    fitted = {"title": title.payload(), "max_width": round(max_width, 1)}
    if item.secondary_text:
        secondary = fit_text(
            item.secondary_text, max_width=max_width, base_px=round(34 * u),
            min_px=round(20 * u), font_file=font, max_lines=6,
        )  # fmt: skip
        fitted["secondary"] = secondary.payload()
    return fitted


def _caption_payload(
    layout: CaptionLayout | None,
    captions: CaptionTrack | None,
    caption_style: CaptionStyle | None,
    *,
    highlight: bool,
) -> list[dict]:
    """Serialise cues as measured lines, so the compositor never has to wrap.

    Each cue carries the exact lines to draw and the exact size to draw them
    at. The compositor has no wrapping, clamping or ellipsis rule, which is how
    the old line-clamp defect is prevented structurally rather than by choosing
    a smaller font and hoping.

    The style's case is applied to each word here, for the same reason the ASS
    writer does it: the highlighted path renders individual words rather than
    the cue's already-cased text, so an uppercase contract would otherwise
    render as spoken whenever highlighting was enabled.
    """
    from social_video.captions.chunk import apply_case
    from social_video.captions.emphasis import emphasis_keys, is_emphasised

    if layout is None or captions is None:
        return []
    keys = emphasis_keys(caption_style.emphasis_words if caption_style else [])
    by_index = {cue.index: cue for cue in captions.cues}
    payload: list[dict] = []
    for drawn in layout.cues:
        cue = by_index[drawn.index]
        item = cue.model_dump(mode="json", exclude={"schema_version", "words"})
        item["font_size_px"] = drawn.font_size_px
        case = caption_style.case if caption_style else CaptionCase.AS_SPOKEN
        lines = []
        for line in drawn.lines:
            entry = line.payload(with_words=False)
            if highlight and line.words:
                entry["words"] = [
                    {
                        "text": apply_case(word.text, case),
                        "start": word.start,
                        "end": word.end,
                        "emphasis": is_emphasised(word.text, keys),
                    }
                    for word in line.words
                ]
            elif keys:
                # No highlight to time, so the words come from the measured
                # line itself; a start after the end means never active.
                entry["words"] = [
                    {"text": text, "start": 1.0, "end": 0.0, "emphasis": is_emphasised(text, keys)}
                    for text in line.text.split(" ")
                ]
            lines.append(entry)
        item["lines"] = lines
        payload.append(item)
    return payload


def mux_base_audio(picture: Path, base_video: Path, output: Path) -> Path:
    """Put the base render's audio, untouched, under the compositor's picture.

    The compositor only draws. Letting it carry the sound re-encoded the base
    AAC without trimming the encoder priming, so every Remotion render played
    its audio ~45 ms late. Copying the stream keeps the audio bit-identical to
    the base render, whose sync is already checked against the sources.
    """
    run_ffmpeg(
        [
            "-y",
            "-v",
            "error",
            "-i",
            str(picture),
            "-i",
            str(base_video),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output),
        ],
        desc="mux the base audio under the motion layer",
        timeout=3600,
    )
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
    atomic_copy(staged, output.resolve())
