"""Claude Motion segments: specified here, authored in Claude, imported back.

The CLI never talks to Motion. It writes a spec a Claude session can author a
film from -- text, timing, the brand's colours and font, pixel geometry, and
nothing of the recording. The user exports the film from its page; `import`
cuts that one file into a segment per scene, places each as a full-frame
overlay in place of the graphic it stands for, and records hashes and brand
facts so the render and brand QA can check what was composited.
"""

from __future__ import annotations

import json
import re
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Literal, cast

import numpy as np

from social_video.errors import ValidationError
from social_video.ffmpeg.probe import probe
from social_video.ffmpeg.run import find_binary, run_ffmpeg
from social_video.fsutil import atomic_target, atomic_write_bytes, utc_timestamp
from social_video.imaging import sha256_file
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.config import BrandContract
from social_video.schemas.edl import EDL, Overlay, OverlayKind
from social_video.schemas.motion import MotionElementType, MotionPlan
from social_video.schemas.motion_film import (
    FILM_FPS,
    FILM_TYPES,
    MIN_SCENE_SECONDS,
    WESTERN_EUROPEAN,
    FilmPalette,
    FilmRecord,
    FilmRegistry,
    FilmScene,
    FilmSegment,
    FilmSpec,
)
from social_video.schemas.visuals import CapabilityState
from social_video.workspace.layout import Workspace

NAMES = {
    MotionElementType.HOOK_CARD: "Hook",
    MotionElementType.CHAPTER: "Chapter",
    MotionElementType.CTA: "Call to action",
    MotionElementType.END_CARD: "End card",
    MotionElementType.QUOTE: "Quote",
}
#: What a built-in face stands in with when a Google family cannot be fetched.
FALLBACK_FACE = "plus-jakarta-sans"


# -- the spec -----------------------------------------------------------------


def build_film_spec(
    edl: EDL,
    plan: MotionPlan,
    contract: BrandContract | None,
    *,
    types: list[str] | None = None,
    film_id: str | None = None,
    title: str | None = None,
    allow_brand_upload: bool = False,
    claude_motion: CapabilityState = CapabilityState.UNKNOWN_TO_CLI,
) -> FilmSpec:
    """A film of the plan's full-frame graphics, in the brand's terms."""
    wanted = _wanted_types(types)
    chosen = sorted(
        (e for e in plan.elements if e.type in wanted), key=lambda e: (e.start, e.type.value)
    )
    if not chosen:
        names = ", ".join(sorted(t.value for t in wanted))
        raise ValidationError(f"the motion plan has no {names} for a Motion film to stand in for")
    short = [e for e in chosen if e.end - e.start < MIN_SCENE_SECONDS]
    if short:
        listed = ", ".join(f"{e.type.value} at {e.start:.2f}s" for e in short)
        raise ValidationError(
            f"Motion refuses a scene under {MIN_SCENE_SECONDS:.0f} s; lengthen or leave out: "
            f"{listed}"
        )
    counts: dict[MotionElementType, int] = {}
    scenes = []
    for element in chosen:
        counts[element.type] = counts.get(element.type, 0) + 1
        number = counts[element.type]
        label = NAMES[element.type]
        scenes.append(
            FilmScene(
                id=f"{element.type.value.replace('_', '-')}-{number}",
                name=label if number == 1 else f"{label} {number}",
                element_type=element.type,
                start_in_output=round(element.start, 3),
                duration=round(element.end - element.start, 3),
                text=element.text,
                secondary_text=element.secondary_text,
                items=list(element.items),
                reason=element.reason,
            )
        )
    fps, conform = _film_rate(edl, contract)
    upload: Literal["none", "project_config", "explicit_flag"] = (
        "explicit_flag"
        if allow_brand_upload
        else "project_config"
        if contract is not None and contract.brand_asset_upload == "allowed"
        else "none"
    )
    letters = sorted(
        {
            ch
            for scene in scenes
            for ch in " ".join([scene.text, scene.secondary_text or "", *scene.items])
            if ch not in WESTERN_EUROPEAN
        }
    )
    return FilmSpec(
        film_id=film_id or _slug(f"{edl.name}-film"),
        title=title or f"{edl.name}: designed segments",
        edl=edl.name,
        brand_contract_sha256=contract.project_config_sha256 if contract else None,
        width=edl.output_width,
        height=edl.output_height,
        fps=cast(Literal[24, 30, 60], fps),
        conform_to_fps=conform,
        palette=_palette(plan, contract),
        font_family=_font_family(plan, contract),
        extended_letters="".join(letters),
        scenes=scenes,
        safe_margins_px=_margins_px(edl, contract),
        reserved_zones_px=_reserved_px(edl, contract),
        brand_upload=upload,
        logo_file=(contract.resolved_logo_file if contract and upload != "none" else None),
        font_file=(contract.resolved_font_file if contract and upload != "none" else None),
        claude_motion=claude_motion,
        created_at=utc_timestamp(),
    )


def write_film_spec(workspace: Workspace, spec: FilmSpec, *, force: bool = False) -> Path:
    """Write the spec, Motion's own `scenes.json` and `base.css`, and register it."""
    registry = load_registry(workspace)
    imported = [s for s in registry.segments if s.film_id == spec.film_id]
    if imported and not force:
        raise ValidationError(
            f"film {spec.film_id!r} already has imported segments; remove them with "
            "`motion film remove` or pass --force to specify it again"
        )
    folder = workspace.motion_film_exports / spec.film_id
    folder.mkdir(parents=True, exist_ok=True)
    spec_path = folder / "film-spec.json"
    save_artifact(spec, spec_path)
    atomic_write_bytes(
        folder / "scenes.json",
        (json.dumps(motion_scenes(spec), indent=2, ensure_ascii=False) + "\n").encode(),
    )
    atomic_write_bytes(folder / "base.css", motion_base_css(spec).encode())
    record = FilmRecord(
        film_id=spec.film_id,
        spec_path=str(spec_path),
        spec_sha256=spec.digest(),
        scenes=[scene.id for scene in spec.scenes],
        written_at=spec.created_at,
    )
    registry.films = [r for r in registry.films if r.film_id != spec.film_id] + [record]
    save_artifact(registry, workspace.motion_films)
    return spec_path


def motion_scenes(spec: FilmSpec) -> dict:
    """The film's `modules/scenes.json`, in the shape the Motion player reads."""
    family = spec.font_family.strip()
    fonts = {"sans": {"family": family, "or": FALLBACK_FACE}} if family else {}
    return {
        "v": 1,
        "stage": "rough",
        "look": f"The brand's own: {spec.title}, in its colours and typeface",
        "palettes": [spec.palette.colours()],
        "theirs": 1,
        "width": spec.width,
        "height": spec.height,
        "fps": spec.fps,
        "background": spec.palette.ground,
        "fonts": fonts,
        "scenes": [
            {"id": s.id, "name": s.name, "dur": s.duration, "desc": _describe(s)}
            for s in spec.scenes
        ],
    }


def motion_base_css(spec: FilmSpec) -> str:
    """The film's `modules/base.css`: the brand's colours and safe margins."""
    p = spec.palette
    m = spec.safe_margins_px
    return (
        f"#stage {{ --ground:{p.ground}; --main:{p.main}; --second:{p.second}; "
        f"--accent:{p.accent}; color:var(--second); "
        "font-family:var(--sans, system-ui, sans-serif) }\n"
        ".ground { position:absolute; inset:0; background:var(--ground) }\n"
        f".safe {{ position:absolute; top:{m.get('top', 0)}px; right:{m.get('right', 0)}px; "
        f"bottom:{m.get('bottom', 0)}px; left:{m.get('left', 0)}px }}\n"
        ".words { position:absolute; margin:0; display:flex; flex-direction:column; gap:24px } "
        ".words > * { margin:0 }\n"
    )


# -- import -------------------------------------------------------------------


def import_film(
    workspace: Workspace,
    export: Path,
    *,
    film_id: str,
    font_used: str,
    scene_ids: list[str] | None = None,
    tolerance_frames: float = 1.0,
) -> list[FilmSegment]:
    """Cut the user's export into one segment per scene and place each one."""
    registry = load_registry(workspace)
    try:
        record = registry.film(film_id)
    except KeyError as exc:
        raise ValidationError(str(exc.args[0])) from exc
    spec = load_artifact(FilmSpec, Path(record.spec_path))
    if spec.digest() != record.spec_sha256:
        raise ValidationError(
            f"{record.spec_path} changed after it was written; write it again with "
            "`motion film spec`"
        )
    if not export.is_file():
        raise ValidationError(f"no exported film at {export}")
    info = probe(export)
    if info.video is None:
        raise ValidationError(f"{export} has no video stream")
    size = info.video.display_size
    if size != (spec.width, spec.height):
        raise ValidationError(
            f"{export} is {size[0]}x{size[1]}; film {film_id!r} was specified at "
            f"{spec.width}x{spec.height}. Another size is another film."
        )
    frame = 1.0 / spec.fps
    if abs(info.duration - spec.duration) > tolerance_frames * frame + 1e-3:
        raise ValidationError(
            f"{export} runs {info.duration:.3f} s; the spec's scenes add up to "
            f"{spec.duration:.3f} s. Export the whole film, unchanged."
        )
    wanted = scene_ids or [scene.id for scene in spec.scenes]
    unknown = [s for s in wanted if s not in {scene.id for scene in spec.scenes}]
    if unknown:
        raise ValidationError(f"film {film_id!r} has no scene {', '.join(unknown)}")
    if not workspace.edl.is_file():
        raise ValidationError(f"no EDL at {workspace.edl}")
    edl = load_artifact(EDL, workspace.edl)
    plan = (
        load_artifact(MotionPlan, workspace.motion_plan)
        if workspace.motion_plan.is_file()
        else None
    )
    contract = (
        load_artifact(BrandContract, workspace.brand_contract)
        if workspace.brand_contract.is_file()
        else None
    )
    rate = edl.output_fps or (contract.output_fps if contract else None) or str(spec.fps)
    source_sha = sha256_file(export)
    workspace.motion_assets.mkdir(parents=True, exist_ok=True)
    overlays = list(edl.overlays)
    elements = list(plan.elements) if plan else []
    imported: list[FilmSegment] = []
    for scene in (s for s in spec.scenes if s.id in wanted):
        target = workspace.motion_assets / f"{film_id}-{scene.id}.mp4"
        offset = spec.offset(scene.id)
        with atomic_target(target) as temporary:
            run_ffmpeg(
                ["-y", "-v", "error", "-ss", f"{offset:.6f}", "-i", str(export),
                 "-t", f"{scene.duration:.6f}", "-map", "0:v:0", "-an",
                 "-vf", f"fps={rate},format=yuv420p", "-c:v", "libx264", "-crf", "16",
                 "-preset", "medium", "-movflags", "+faststart", "-f", "mp4", str(temporary)],
                desc=f"cut Motion scene {scene.id}",
            )  # fmt: skip
        cut = probe(target)
        if cut.video is None or cut.duration + frame < scene.duration:
            raise ValidationError(
                f"scene {scene.id} came out {cut.duration:.3f} s long; expected "
                f"{scene.duration:.3f} s"
            )
        replaced = next(
            (
                e
                for e in elements
                if e.type is scene.element_type and abs(e.start - scene.start_in_output) < 0.01
            ),
            None,
        )
        if replaced is not None:
            elements.remove(replaced)
        previous = next(
            (s for s in registry.segments if (s.film_id, s.scene_id) == (film_id, scene.id)),
            None,
        )
        overlays = [o for o in overlays if o.file != str(target)]
        overlays.append(
            Overlay(
                file=str(target), kind=OverlayKind.MOTION_FILM,
                start_in_output=scene.start_in_output, duration=scene.duration,
                x="0", y="0", scale_width=edl.output_width,
                reason=f"Claude Motion {film_id}/{scene.id}: {scene.reason}",
            )
        )  # fmt: skip
        imported.append(
            FilmSegment(
                film_id=film_id,
                scene_id=scene.id,
                element_type=scene.element_type,
                spec_sha256=record.spec_sha256,
                source_path=str(export.resolve()),
                source_sha256=source_sha,
                path=str(target),
                sha256=sha256_file(target),
                width=cut.video.display_size[0],
                height=cut.video.display_size[1],
                fps=cut.video.nominal_frame_rate,
                duration=round(cut.duration, 3),
                start_in_output=scene.start_in_output,
                offset_in_film=round(offset, 3),
                imported_at=utc_timestamp(),
                font_used=" ".join(font_used.split()),
                font_expected=spec.font_family,
                brand_contract_sha256=spec.brand_contract_sha256,
                brand_upload=spec.brand_upload,
                replaced_element=replaced or (previous.replaced_element if previous else None),
            )
        )
    updated = EDL.model_validate(edl.model_copy(update={"overlays": overlays}).model_dump())
    save_artifact(updated, workspace.edl)
    if plan is not None:
        save_artifact(
            MotionPlan.model_validate(plan.model_copy(update={"elements": elements}).model_dump()),
            workspace.motion_plan,
        )
    done = {(s.film_id, s.scene_id) for s in imported}
    registry.segments = [
        s for s in registry.segments if (s.film_id, s.scene_id) not in done
    ] + imported
    save_artifact(registry, workspace.motion_films)
    return imported


def remove_film_segment(workspace: Workspace, film_id: str, scene_id: str) -> FilmSegment:
    """Take a segment out of the edit and put back the graphic it replaced."""
    registry = load_registry(workspace)
    segment = next(
        (s for s in registry.segments if (s.film_id, s.scene_id) == (film_id, scene_id)), None
    )
    if segment is None:
        raise ValidationError(f"no imported segment {film_id}/{scene_id}")
    edl = load_artifact(EDL, workspace.edl)
    overlays = [o for o in edl.overlays if o.file != segment.path]
    save_artifact(
        EDL.model_validate(edl.model_copy(update={"overlays": overlays}).model_dump()),
        workspace.edl,
    )
    if segment.replaced_element is not None:
        plan = (
            load_artifact(MotionPlan, workspace.motion_plan)
            if workspace.motion_plan.is_file()
            else MotionPlan(rationale="Graphics restored after removing a Claude Motion segment.")
        )
        elements = list(plan.elements)
        if not any(e.model_dump() == segment.replaced_element.model_dump() for e in elements):
            elements.append(segment.replaced_element)
        restored = plan.model_copy(update={"elements": sorted(elements, key=lambda e: e.start)})
        save_artifact(MotionPlan.model_validate(restored.model_dump()), workspace.motion_plan)
    registry.segments = [s for s in registry.segments if s is not segment]
    save_artifact(registry, workspace.motion_films)
    return segment


# -- evidence -----------------------------------------------------------------


def load_registry(workspace: Workspace) -> FilmRegistry:
    path = workspace.motion_films
    return load_artifact(FilmRegistry, path) if path.is_file() else FilmRegistry()


def segment_evidence(workspace: Workspace, edl: EDL) -> list[dict]:
    """What the render will composite from Motion, checked against the registry.

    A segment that is missing or changed since import fails the render: the
    export cannot be reproduced, so silently dropping or trusting it would
    ship something nobody approved.
    """
    films = [o for o in edl.overlays if o.kind is OverlayKind.MOTION_FILM]
    if not films:
        return []
    by_path = {s.path: s for s in load_registry(workspace).segments}
    evidence = []
    for overlay in films:
        segment = by_path.get(overlay.file)
        if segment is None:
            raise ValidationError(
                f"overlay {overlay.file} is marked as a Motion film segment but no import "
                f"records it in {workspace.motion_films}"
            )
        where = f"{segment.film_id}/{segment.scene_id}"
        path = Path(segment.path)
        if not path.is_file():
            raise ValidationError(
                f"Motion film segment {where} is missing at {path}; import the user's export "
                f"again ({segment.source_path}) with `motion film import`"
            )
        actual = sha256_file(path)
        if actual != segment.sha256:
            raise ValidationError(
                f"Motion film segment {where} changed after import (sha256 {actual[:12]}, "
                f"recorded {segment.sha256[:12]}); import it again"
            )
        evidence.append(
            {
                "film_id": segment.film_id,
                "scene_id": segment.scene_id,
                "element_type": segment.element_type.value,
                "path": segment.path,
                "sha256": actual,
                "recorded_sha256": segment.sha256,
                "width": segment.width,
                "height": segment.height,
                "fps": segment.fps,
                "start_in_output": overlay.start_in_output,
                "duration": overlay.duration,
                "font_used": segment.font_used,
                "font_expected": segment.font_expected,
                "brand_contract_sha256": segment.brand_contract_sha256,
                "brand_upload": segment.brand_upload,
            }
        )
    return evidence


def palette_share(
    path: Path, colours: list[str], *, samples: int = 3, tolerance: int = 48
) -> float:
    """Fraction of sampled pixels within ``tolerance`` of one of ``colours``.

    A designed card in the brand's colours scores high; a film drawn in
    someone else's palette scores low. Text and logos lower it a little, which
    is why brand QA reads it as a warning, never as an error.
    """
    info = probe(path)
    if info.video is None or not colours:
        return 0.0
    palette = np.array([[int(c[i : i + 2], 16) for i in (1, 3, 5)] for c in colours], dtype=float)
    shares = []
    for index in range(samples):
        at = info.duration * (index + 0.5) / samples
        proc = subprocess.run(
            [find_binary("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error",
             "-ss", f"{at:.3f}", "-i", str(path), "-frames:v", "1",
             "-vf", "scale=64:-2:flags=area", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True, check=False, timeout=120,
        )  # fmt: skip
        if proc.returncode != 0 or not proc.stdout:
            continue
        pixels = np.frombuffer(proc.stdout, dtype=np.uint8).reshape(-1, 3).astype(float)
        nearest = np.min(np.linalg.norm(pixels[:, None, :] - palette[None, :, :], axis=2), axis=1)
        shares.append(float(np.mean(nearest <= tolerance)))
    return round(float(np.mean(shares)), 3) if shares else 0.0


# -- helpers ------------------------------------------------------------------


def _wanted_types(types: list[str] | None) -> frozenset[MotionElementType]:
    if not types:
        return FILM_TYPES
    wanted = set()
    for name in types:
        try:
            kind = MotionElementType(name.strip().casefold())
        except ValueError as exc:
            raise ValidationError(f"unknown graphic type {name!r}") from exc
        if kind not in FILM_TYPES:
            allowed = ", ".join(sorted(t.value for t in FILM_TYPES))
            raise ValidationError(
                f"a {kind.value} sits over the picture, and an exported film is opaque and "
                f"full frame; a film can stand in for: {allowed}"
            )
        wanted.add(kind)
    return frozenset(wanted)


def _film_rate(edl: EDL, contract: BrandContract | None) -> tuple[int, str | None]:
    declared = edl.output_fps or (contract.output_fps if contract else None)
    if declared is None:
        return 60, None
    rate = Fraction(declared)
    for fps in FILM_FPS:
        if rate == fps:
            return fps, None
    return 60, declared


def _palette(plan: MotionPlan, contract: BrandContract | None) -> FilmPalette:
    if contract is not None:
        brand = contract.brand
        ground, main, second = (
            brand.background_colour,
            brand.accent_colour,
            brand.captions.primary_colour,
        )
        options = [brand.captions.emphasis_colour, brand.captions.highlight_colour,
                   brand.captions.outline_colour]  # fmt: skip
    else:
        ground, main, second = plan.background_color, plan.accent_color, plan.text_color
        options = []
    used = {ground.casefold(), main.casefold(), second.casefold()}
    accent = next((c for c in options if c and c.casefold() not in used), main)
    return FilmPalette(ground=ground, main=main, second=second, accent=accent)


def _font_family(plan: MotionPlan, contract: BrandContract | None) -> str:
    if contract is not None:
        brand = contract.brand
        return (brand.title_font_family or brand.captions.font_family or "").strip()
    return plan.font_family


def _margins_px(edl: EDL, contract: BrandContract | None) -> dict[str, int]:
    margins = contract.safe_margins if contract else {}
    return {
        edge: round((margins.get(edge, 6.0) / 100.0) * size)
        for edge, size in (
            ("top", edl.output_height),
            ("bottom", edl.output_height),
            ("left", edl.output_width),
            ("right", edl.output_width),
        )
    }


def _reserved_px(edl: EDL, contract: BrandContract | None) -> dict[str, dict[str, int]]:
    from social_video.profiles.registry import load_platform

    zones: dict[str, dict[str, int]] = {}
    for name in contract.target_platforms if contract else []:
        try:
            spec = load_platform(name)
        except Exception:  # an unknown platform is reported by platform QA
            continue
        zones[spec.name] = {
            "top": round(spec.reserved_top_pct / 100.0 * edl.output_height),
            "bottom": round(spec.reserved_bottom_pct / 100.0 * edl.output_height),
            "left": round(spec.reserved_left_pct / 100.0 * edl.output_width),
            "right": round(spec.reserved_right_pct / 100.0 * edl.output_width),
        }
    return zones


def _describe(scene: FilmScene) -> str:
    words = scene.text or "; ".join(scene.items) or scene.name
    return f"{NAMES[scene.element_type]}: {words}"[:200]


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", text.casefold()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug or not slug[0].isalpha():
        slug = f"film-{slug}".strip("-")
    return slug[:48].rstrip("-")
