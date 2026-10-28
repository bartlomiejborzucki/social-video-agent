"""A graphic written for one sentence: a Remotion component the agent authors.

When no element of the vocabulary says what a sentence means, the agent may
write its own animation for it: `motion/custom/<id>.tsx` in the edit
workspace, placed by a `custom` element. The component receives only the
brand's tokens (colours, font), the size of its zone and of the frame, the
safe margins and the times of the words in its range. It may import only
`react` and a small set of `remotion` names: no network, no files, no other
packages.

Before it is drawn, every component is checked: its imports and a list of
forbidden calls, then `tsc --noEmit` against the props it is given. A
component that fails is left out with the reason, recorded in the render
manifest as `custom_rejected`; the rest of the reel renders as planned. The
compositor clips each component to its zone, and motion QA measures that zone
against faces and captions like any other graphic.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from social_video.schemas.motion import MotionElementType, MotionPlan

#: The only modules a component may import.
ALLOWED_MODULES = frozenset({"react", "remotion"})
#: What a component may take from `remotion`: drawing and timing, never media
#: or files (`Img`, `Video`, `Audio`, `staticFile`), never render control.
REMOTION_NAMES = frozenset(
    {
        "AbsoluteFill",
        "Easing",
        "Freeze",
        "Loop",
        "Sequence",
        "Series",
        "interpolate",
        "interpolateColors",
        "measureSpring",
        "random",
        "spring",
        "useCurrentFrame",
        "useVideoConfig",
    }
)
#: Calls and strings that reach the network, other code or the page.
FORBIDDEN = (
    (re.compile(r"\bfetch\s*\("), "fetch()"),
    (re.compile(r"\bXMLHttpRequest\b"), "XMLHttpRequest"),
    (re.compile(r"\bWebSocket\b"), "WebSocket"),
    (re.compile(r"\bEventSource\b"), "EventSource"),
    (re.compile(r"\bsendBeacon\b"), "navigator.sendBeacon"),
    (re.compile(r"\beval\s*\("), "eval()"),
    (re.compile(r"\bFunction\s*\("), "Function()"),
    (re.compile(r"\bimport\s*\("), "a dynamic import()"),
    (re.compile(r"\brequire\s*\("), "require()"),
    (re.compile(r"\bimportScripts\b"), "importScripts"),
    (re.compile(r"\bstaticFile\b"), "staticFile (a component draws; it loads no files)"),
    (re.compile(r"\b(localStorage|sessionStorage|indexedDB)\b"), "browser storage"),
    (re.compile(r"\bdangerouslySetInnerHTML\b"), "dangerouslySetInnerHTML"),
    (re.compile(r"https?:|//[a-z0-9.-]+\.[a-z]{2,}/", re.IGNORECASE), "a URL"),
)
_IMPORT = re.compile(
    r"^\s*import\s+(?P<type>type\s+)?(?P<what>[^'\";]+?)\s+from\s+['\"](?P<module>[^'\"]+)['\"]",
    re.MULTILINE,
)
_BARE_IMPORT = re.compile(r"^\s*import\s+['\"]([^'\"]+)['\"]", re.MULTILINE)
_REEXPORT = re.compile(r"^\s*export\s+(?:\*|\{[^}]*\})\s+from\s+['\"]", re.MULTILINE)
#: Largest component source accepted.
MAX_BYTES = 200_000

TEMPLATE = """\
import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';

// What the compositor passes. Keep this type as it is; it is checked.
type CustomGraphicProps = {
  /** The brand's tokens: draw only in these colours and this font. */
  brand: {
    accent: string;
    secondary: string;
    text: string;
    background: string;
    colors: string[];
    font: string;
  };
  /** The zone this component draws in, in pixels; it is clipped to it. */
  width: number;
  height: number;
  /** The whole frame and its safe margins (percent), for proportions only. */
  frame: {width: number; height: number};
  safeMargins: {top: number; right: number; bottom: number; left: number};
  /** The words said while it is on screen, in seconds from its start. */
  words: {text: string; start: number; end: number}[];
};

export default function Graphic({brand, width, height, words}: CustomGraphicProps) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const now = frame / fps;
  const enter = spring({frame, fps, config: {damping: 14, stiffness: 180}});
  const said = words.filter((word) => word.start <= now).length;
  return (
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', fontFamily: brand.font}}>
      <div
        style={{
          fontSize: height * 0.3,
          fontWeight: 900,
          color: brand.accent,
          transform: `scale(${interpolate(enter, [0, 1], [0.6, 1])})`,
          maxWidth: width,
        }}
      >
        {said}
      </div>
    </AbsoluteFill>
  );
}
"""


def component_path(workspace_root: Path, component: str) -> Path:
    return workspace_root / "motion" / "custom" / f"{component}.tsx"


def scan_source(text: str) -> list[str]:
    """Every rule the source breaks: imports, forbidden calls, size."""
    problems: list[str] = []
    if len(text.encode("utf-8")) > MAX_BYTES:
        problems.append(f"the component is over {MAX_BYTES // 1000} kB")
    if _BARE_IMPORT.search(text):
        problems.append("a side-effect import (import '...') is not allowed")
    if _REEXPORT.search(text):
        problems.append("re-exporting another module is not allowed")
    for match in _IMPORT.finditer(text):
        module = match.group("module")
        if module not in ALLOWED_MODULES:
            allowed = ", ".join(sorted(ALLOWED_MODULES))
            problems.append(f"imports {module!r}; a component may import only {allowed}")
            continue
        if module == "remotion" and not match.group("type"):
            names = _imported_names(match.group("what"))
            if names is None:
                problems.append("import remotion by name: import {spring, ...} from 'remotion'")
            elif refused := sorted(n for n in names if n not in REMOTION_NAMES):
                problems.append(
                    f"takes {', '.join(refused)} from remotion; allowed: "
                    + ", ".join(sorted(REMOTION_NAMES))
                )
    for pattern, what in FORBIDDEN:
        if pattern.search(text):
            problems.append(f"uses {what}")
    if not re.search(r"^\s*export\s+default\b", text, re.MULTILINE):
        problems.append("the component is the file's default export (export default ...)")
    return problems


def _imported_names(what: str) -> set[str] | None:
    """Names a value import takes, or None for a namespace import."""
    if "*" in what:
        return None
    braces = re.search(r"\{([^}]*)\}", what)
    if braces is None:
        return set()
    names = set()
    for part in braces.group(1).split(","):
        part = part.strip()
        if not part or part.startswith("type "):
            continue
        names.add(part.split(" as ")[0].strip())
    return names


@dataclass
class CustomCheck:
    """What the checks found for each component a plan uses."""

    files: dict[str, Path] = field(default_factory=dict)
    problems: dict[str, list[str]] = field(default_factory=dict)

    def accepted(self) -> dict[str, Path]:
        return {c: p for c, p in self.files.items() if not self.problems.get(c)}

    def evidence(self) -> tuple[list[dict], list[dict]]:
        applied = [
            {"component": c, "file": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for c, p in sorted(self.accepted().items())
        ]
        rejected = [
            {"component": c, "problems": problems}
            for c, problems in sorted(self.problems.items())
            if problems
        ]
        return applied, rejected


def check_components(
    plan: MotionPlan, workspace_root: Path, *, typecheck: bool = True
) -> CustomCheck:
    """Check every component the plan names: the file, its source, its types."""
    result = CustomCheck()
    for element in plan.elements:
        if element.type is not MotionElementType.CUSTOM or element.component is None:
            continue
        name = element.component
        if name in result.files or name in result.problems:
            continue
        path = component_path(workspace_root, name)
        if not path.is_file():
            result.problems[name] = [f"no component at {path}"]
            continue
        result.files[name] = path
        result.problems[name] = scan_source(path.read_text(encoding="utf-8"))
    if typecheck:
        clean = {c: p for c, p in result.files.items() if not result.problems.get(c)}
        for name, errors in typecheck_components(clean).items():
            result.problems.setdefault(name, []).extend(errors)
    return result


def typecheck_components(files: dict[str, Path]) -> dict[str, list[str]]:
    """`tsc --noEmit` on the components, against the props the compositor passes."""
    from uuid import uuid4

    from social_video.remotion_runtime import locate_runtime

    if not files:
        return {}
    runtime = locate_runtime()
    tsc = runtime.root / "node_modules" / ".bin" / "tsc" if runtime else None
    if runtime is None or tsc is None or not tsc.is_file():
        reason = "TypeScript is not installed with the compositor, so it could not be checked"
        return {name: [reason] for name in files}
    from social_video.paths import app_home

    work = app_home() / "custom-check" / uuid4().hex
    try:
        (work / "custom").mkdir(parents=True)
        types = json.dumps(str(runtime.root / "remotion" / "types"))
        lines = [
            "import type {FC} from 'react';",
            f"import type {{CustomGraphicProps}} from {types};",
        ]
        for index, (name, path) in enumerate(sorted(files.items())):
            shutil.copy2(path, work / "custom" / f"{name}.tsx")
            lines.append(f"import C{index} from './custom/{name}';")
        lines.append(
            "export const checks: FC<CustomGraphicProps>[] = ["
            + ", ".join(f"C{i}" for i in range(len(files)))
            + "];"
        )
        (work / "check.ts").write_text("\n".join(lines) + "\n", encoding="utf-8")
        modules = runtime.root / "node_modules"
        config = {
            "compilerOptions": {
                "target": "ES2022", "lib": ["DOM", "ES2022"], "jsx": "react-jsx",
                "module": "ESNext", "moduleResolution": "Bundler", "strict": True,
                "noEmit": True, "skipLibCheck": True, "types": [],
                "paths": {
                    "react": [str(modules / "@types" / "react")],
                    "react/*": [str(modules / "@types" / "react" / "*")],
                    "remotion": [str(modules / "remotion")],
                },
            },
            "files": ["check.ts"],
        }  # fmt: skip
        (work / "tsconfig.json").write_text(json.dumps(config), encoding="utf-8")
        proc = subprocess.run(
            [str(tsc), "-p", str(work / "tsconfig.json")],
            cwd=work,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if proc.returncode == 0:
        return {}
    found: dict[str, list[str]] = {}
    for line in (proc.stdout + proc.stderr).splitlines():
        match = re.match(r"custom/([a-z0-9-]+)\.tsx\((\d+),(\d+)\): (.*)", line.strip())
        if match:
            found.setdefault(match.group(1), []).append(
                f"line {match.group(2)}: {match.group(4).strip()}"
            )
        elif line.strip().startswith("check.ts"):
            # The component does not fit the props it is given; say so on each.
            for name in files:
                found.setdefault(name, []).append(line.strip().split(": ", 1)[-1])
    if not found:
        detail = (proc.stdout or proc.stderr).strip().splitlines()[-1:] or ["tsc failed"]
        found = {name: detail for name in files}
    return found


def without_rejected(plan: MotionPlan, check: CustomCheck) -> MotionPlan:
    """The plan with every custom element whose component failed left out."""
    accepted = check.accepted()
    kept = [
        e
        for e in plan.elements
        if e.type is not MotionElementType.CUSTOM or (e.component or "") in accepted
    ]
    return plan.model_copy(update={"elements": kept})


#: A preview opens this long before the component, as the reel would.
PREVIEW_LEAD_S = 0.3


def preview_component(workspace, plan: MotionPlan, element, *, video: Path | None = None) -> Path:
    """Render the component's range over the edit, to `qa/custom-<id>.mp4`."""
    from fractions import Fraction

    from social_video.errors import ValidationError
    from social_video.ffmpeg.probe import probe
    from social_video.ffmpeg.run import run_ffmpeg
    from social_video.remotion import render_motion_design
    from social_video.schemas.base import load_artifact
    from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord
    from social_video.schemas.config import BrandContract
    from social_video.schemas.edl import EDL

    base = workspace.cache / "remotion" / "base-preview.mp4"
    source = video or (base if base.is_file() else workspace.previews / "preview.mp4")
    if not source.is_file():
        raise ValidationError(f"no render to preview over at {source}; render a preview first")
    begin = max(0.0, element.start - PREVIEW_LEAD_S)
    clip = workspace.cache / "remotion" / f"custom-{element.component}-base.mp4"
    clip.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        ["-y", "-v", "error", "-ss", f"{begin:.3f}", "-to", f"{element.end:.3f}",
         "-i", str(source), "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-ar", "48000", "-ac", "2", str(clip)],
        desc="cut the custom element's range",
    )  # fmt: skip
    info = probe(clip)
    if info.video is None:
        raise ValidationError(f"{source} has no video stream")
    fps = float(Fraction(info.video.frame_rate or "30/1"))
    frames = info.video.nb_frames or round(info.duration * fps)
    words: list[CaptionWord] = []
    edl = load_artifact(EDL, workspace.edl) if workspace.edl.is_file() else None
    if edl is not None and edl.captions and Path(edl.captions).with_suffix(".json").is_file():
        track = load_artifact(CaptionTrack, Path(edl.captions).with_suffix(".json"))
        words = [
            CaptionWord(text=w.text, start=round(w.start - begin, 3), end=round(w.end - begin, 3))
            for cue in track.cues
            for w in cue.words
            if element.start <= w.start < element.end
        ]
    heard = (
        CaptionTrack(cues=[CaptionCue(index=1, start=words[0].start, end=words[-1].end,
                                      text=" ".join(w.text for w in words), words=words)])
        if words
        else None
    )  # fmt: skip
    shifted = element.model_copy(
        update={"start": element.start - begin, "end": element.end - begin, "at_word": None}
    )
    preview_plan = MotionPlan(rationale="Preview of one custom element.", elements=[shifted])
    options: dict = {}
    if workspace.brand_contract.is_file():
        contract = load_artifact(BrandContract, workspace.brand_contract)
        preview_plan = preview_plan.model_copy(
            update={
                "accent_color": contract.brand.accent_colour,
                "text_color": contract.brand.captions.primary_colour,
                "background_color": contract.brand.background_colour,
                "font_family": contract.brand.captions.font_family,
                "font_path": contract.resolved_font_file,
            }
        )
        options = {
            "safe_margins": contract.safe_margins,
            "secondary_colour": contract.brand.secondary_colour,
            "brand_colours": contract.brand.brand_colours,
        }
    output = workspace.qa / f"custom-{element.component}.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    assert element.component is not None
    render_motion_design(
        clip, output, preview_plan, duration_in_frames=frames, fps=fps,
        width=info.video.width, height=info.video.height,
        staging_root=workspace.cache / "remotion", captions=heard,
        custom_components={element.component: component_path(workspace.root, element.component)},
        **options,
    )  # fmt: skip
    return output
