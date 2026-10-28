"""Content-first openings: the timeline starts on the scene, never on a card.

September's weakest reels lost their viewers at one second, where a cover
pasted into the timeline cut to the speaker and the first full caption arrived
seconds later; the strongest opened on the action with the situation burned in
from frame 0. This module makes that a rule:

- `timeline_violations` reads the plan, before anything renders: a still image
  or a Claude Motion segment overlaid at the start, a title card, a logo, or a
  timeline that opens on a still;
- `check_opening` measures the render: frame 0 is a moving picture, not black,
  white or a held still; the first caption starts at 0.0 s; the audio opens
  without a silence longer than the contract allows; an end card only at the
  end. It writes `analysis/opening-qa.json` and a short report beside it.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pydantic import Field

from social_video.errors import ValidationError
from social_video.ffmpeg.probe import probe
from social_video.ffmpeg.run import find_binary
from social_video.schemas.base import Artifact, save_artifact
from social_video.schemas.captions import CaptionTrack
from social_video.schemas.config import OpeningPolicy
from social_video.schemas.edl import EDL, OverlayKind, VisualFillStrategy
from social_video.schemas.motion import MotionElementType, MotionPlan
from social_video.schemas.motion_film import FilmSegment
from social_video.schemas.source import SourceManifest

#: Something that starts this close to 0.0 s is "at the start".
OPENING_WINDOW = 0.5
#: Graphics that are a card, not a caption over the scene.
OPENING_CARDS = frozenset(
    {
        MotionElementType.HOOK,
        MotionElementType.HOOK_CARD,
        MotionElementType.CHAPTER,
        MotionElementType.LOGO_REVEAL,
        MotionElementType.END_CARD,
    }
)
STILL_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"})
STILL_CODECS = frozenset({"png", "mjpeg", "bmp", "gif", "webp", "tiff"})
#: A first caption this late is not "from frame 0".
FIRST_CUE_TOLERANCE = 0.04
#: Mean change between frame 0 and ``STILL_PROBE`` seconds in, in 8-bit levels,
#: below which the opening is a held still. A pasted cover lasts at least half
#: a second; a talking head moves more than this in less.
STATIC_LEVELS = 0.5
STILL_PROBE = 0.4
SILENCE_FLOOR_DB = -40
_SILENCE_START = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class Violation:
    where: str
    what: str
    fix: str

    def line(self) -> str:
        return f"{self.where}: {self.what} -- {self.fix}"


class OpeningReport(Artifact):
    """What a viewer gets in the first seconds, measured, and whether it is ready."""

    policy: str
    video: str
    first_frame_is_content: bool
    #: One sentence on frame 0: measured, or written by the agent who looked.
    first_frame_note: str
    first_frame_path: str = ""
    first_cue_start_s: float | None = None
    first_cue_text: str = ""
    first_cue_matches_brief: bool | None = None
    leading_silence_s: float = Field(ge=0.0)
    cover_in_timeline: bool
    time_to_first_situation_s: float | None = None
    end_card_only_at_end: bool
    ready: bool
    issues: list[str] = Field(default_factory=list)
    variant: str = ""


def timeline_violations(
    edl: EDL,
    plan: MotionPlan | None,
    *,
    sources: SourceManifest | None = None,
    film_segments: list[FilmSegment] | None = None,
) -> list[Violation]:
    """Cards, covers and stills at the start of the timeline."""
    found: list[Violation] = []
    films = {s.path: s for s in film_segments or []}
    for overlay in edl.overlays:
        if overlay.start_in_output >= OPENING_WINDOW:
            continue
        name = Path(overlay.file).name
        if overlay.kind is OverlayKind.MOTION_FILM:
            scene = films.get(overlay.file)
            found.append(
                Violation(
                    f"overlay {name} at {overlay.start_in_output:.2f}s",
                    "a full-frame Claude Motion card opens the timeline"
                    + (f" ({scene.element_type.value})" if scene else ""),
                    "remove it with `motion film remove`, or move the card off the opening",
                )
            )
        elif Path(overlay.file).suffix.casefold() in STILL_SUFFIXES or _still_clip(
            Path(overlay.file)
        ):
            found.append(
                Violation(
                    f"overlay {name} at {overlay.start_in_output:.2f}s",
                    "a still image (a cover or title card) is in the timeline at the start",
                    "remove the overlay and export the image as cover.jpg with `cover`",
                )
            )
    for element in plan.elements if plan else []:
        if element.type in OPENING_CARDS and element.start < OPENING_WINDOW:
            found.append(
                Violation(
                    f"{element.type.value} at {element.start:.2f}s",
                    "a title card covers the opening",
                    "remove it; the first caption carries the situation from frame 0",
                )
            )
    first = edl.ranges[0]
    if sources is not None:
        try:
            entry = sources.by_id(first.effective_video_source)
        except KeyError:
            entry = None
        if entry is not None and (
            entry.video_codec.casefold() in STILL_CODECS
            or Path(entry.path).suffix.casefold() in STILL_SUFFIXES
        ):
            found.append(
                Violation(
                    f"range 1 ({first.effective_video_source})",
                    "the timeline opens on a still image",
                    "start on the first recorded shot of the scene",
                )
            )
    return found


def end_card_violations(
    edl: EDL, plan: MotionPlan | None, film_segments: list[FilmSegment] | None = None
) -> list[Violation]:
    """End cards anywhere but the end."""
    total = edl.total_duration
    cards = sorted(
        (e for e in (plan.elements if plan else []) if e.type is MotionElementType.END_CARD),
        key=lambda e: e.end,
        reverse=True,
    )
    # The end, and every card that runs straight into another card at the end.
    ending = total
    at_end: set[int] = set()
    for card in cards:
        if card.end >= ending - 0.1:
            at_end.add(id(card))
            ending = min(ending, card.start)
    found = [
        Violation(
            f"end_card at {e.start:.2f}s",
            f"an end card ends at {e.end:.2f}s, before the end at {total:.2f}s",
            "move it to the last seconds or remove it",
        )
        for e in cards[::-1]
        if id(e) not in at_end
    ]
    found += [
        Violation(
            f"motion film {s.scene_id}",
            f"an end card segment ends at {s.start_in_output + s.duration:.2f}s, before the end",
            "place it at the end",
        )
        for s in film_segments or []
        if s.element_type is MotionElementType.END_CARD
        and s.start_in_output + s.duration < total - 0.1
    ]
    found += [
        Violation(
            f"range {number}",
            "an end-card fill sits on a range that is not the last",
            "keep the end card on the last range",
        )
        for number, r in enumerate(edl.ranges[:-1], start=1)
        if r.visual_fill_strategy is VisualFillStrategy.END_CARD
    ]
    return found


def refuse_card_openings(
    edl: EDL,
    plan: MotionPlan | None,
    policy: OpeningPolicy,
    *,
    sources: SourceManifest | None = None,
    film_segments: list[FilmSegment] | None = None,
) -> None:
    """Stop a content-first render that opens on a card, before it renders."""
    if policy.opening_policy != "content_first":
        return
    problems = timeline_violations(edl, plan, sources=sources, film_segments=film_segments)
    problems += end_card_violations(edl, plan, film_segments)
    if problems:
        raise ValidationError(
            "opening_policy is content_first: the timeline must open on the scene. "
            + "; ".join(p.line() for p in problems)
        )


def first_frame(video: Path, still: Path | None = None) -> tuple[bool, str]:
    """Whether frame 0 is a moving picture, and one measured sentence about it."""
    info = probe(video)
    if info.video is None:
        return False, "the file has no picture"
    if still is not None:
        still.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [find_binary("ffmpeg"), "-v", "error", "-y", "-i", str(video), "-frames:v", "1",
             str(still)],
            check=False, timeout=120,
        )  # fmt: skip
    zero = _pixels(video, 0.0)
    later = _pixels(video, min(STILL_PROBE, max(0.0, info.duration - 0.05)))
    if zero is None:
        return False, "frame 0 could not be decoded"
    luma = zero @ np.array([0.299, 0.587, 0.114])
    mean, detail = float(luma.mean()), float(luma.std())
    change = float(np.abs(zero - later).mean()) if later is not None else 0.0
    measured = (
        f"mean brightness {mean:.0f}/255, detail {detail:.0f}, "
        f"change in {STILL_PROBE:g} s {change:.1f}"
    )
    if mean < 20:
        return False, f"frame 0 is black ({measured})"
    if mean > 235 and detail < 10:
        return False, f"frame 0 is white ({measured})"
    if detail < 4:
        return False, f"frame 0 is a flat colour, a card rather than a scene ({measured})"
    if change < STATIC_LEVELS:
        return False, f"the opening does not move: a held still or a card ({measured})"
    return True, f"frame 0 is a moving picture ({measured})"


def leading_silence(video: Path, *, window: float = 3.0) -> float:
    """Seconds of silence the audio opens with, below ``SILENCE_FLOOR_DB``."""
    info = probe(video)
    if not info.has_audio:
        return round(min(window, info.duration), 3)
    proc = subprocess.run(
        [find_binary("ffmpeg"), "-hide_banner", "-nostdin", "-t", f"{window:.3f}", "-i", str(video),
         "-map", "0:a:0", "-af", f"silencedetect=noise={SILENCE_FLOOR_DB}dB:d=0.05",
         "-f", "null", "-"],
        capture_output=True, text=True, check=False, timeout=120,
    )  # fmt: skip
    starts = [float(m) for m in _SILENCE_START.findall(proc.stderr)]
    ends = [float(m) for m in _SILENCE_END.findall(proc.stderr)]
    if not starts or starts[0] > 0.02:
        return 0.0
    return round(ends[0] if ends else min(window, info.duration), 3)


def check_opening(
    video: Path,
    edl: EDL,
    plan: MotionPlan | None,
    captions: CaptionTrack | None,
    policy: OpeningPolicy,
    *,
    sources: SourceManifest | None = None,
    film_segments: list[FilmSegment] | None = None,
    brief_first_text: str = "",
    first_frame_note: str = "",
    analysis_dir: Path | None = None,
) -> OpeningReport:
    """Measure the opening of a render against the content-first rule."""
    still = analysis_dir / "first-frame.png" if analysis_dir else None
    is_content, measured_note = first_frame(video, still)
    cues = sorted(captions.cues, key=lambda c: c.start) if captions else []
    first_cue = cues[0] if cues else None
    spoken = next((c for c in cues if c.words), None)
    silence = leading_silence(video)
    cards = timeline_violations(edl, plan, sources=sources, film_segments=film_segments)
    ends = end_card_violations(edl, plan, film_segments)
    matches = None
    if brief_first_text and first_cue is not None:
        matches = _words(brief_first_text) <= _words(first_cue.text) or _words(
            first_cue.text
        ) <= _words(brief_first_text)
    issues: list[str] = []
    if not is_content:
        issues.append(f"first frame: {measured_note} -- start the first range on the scene")
    if first_cue is None:
        issues.append("no caption at all -- the first cue must start at 0.0 s")
    elif first_cue.start > FIRST_CUE_TOLERANCE:
        issues.append(
            f"first caption starts at {first_cue.start:.2f}s -- rebuild captions so cue 1 "
            "starts at 0.0 s with the whole first sentence"
        )
    if silence > policy.max_leading_silence_s:
        issues.append(
            f"audio opens with {silence:.2f}s of silence, over {policy.max_leading_silence_s:g}s "
            "-- move the first range's in-point to just before the first sound"
        )
    issues += [f"cover in timeline: {v.line()}" for v in cards]
    issues += [f"end card: {v.line()}" for v in ends]
    if matches is False:
        issues.append(
            f"first caption {first_cue.text!r} is not the brief's first line "  # type: ignore[union-attr]
            f"{brief_first_text!r} -- check the brief import and the caption track"
        )
    ready = policy.opening_policy != "content_first" or not issues
    report = OpeningReport(
        policy=policy.opening_policy,
        video=str(video),
        first_frame_is_content=is_content,
        first_frame_note=" ".join(first_frame_note.split()) or measured_note,
        first_frame_path=str(still) if still and still.is_file() else "",
        first_cue_start_s=round(first_cue.start, 3) if first_cue else None,
        first_cue_text=first_cue.text if first_cue else "",
        first_cue_matches_brief=matches,
        leading_silence_s=silence,
        cover_in_timeline=bool(cards),
        time_to_first_situation_s=round(spoken.words[0].start, 3) if spoken else None,
        end_card_only_at_end=not ends,
        ready=ready,
        issues=issues,
        variant="" if ready else _variant(issues),
    )
    if analysis_dir is not None:
        save_artifact(report, analysis_dir / "opening-qa.json")
        (analysis_dir / "opening-qa.md").write_text(render_report(report), encoding="utf-8")
    return report


def render_report(report: OpeningReport) -> str:
    verdict = "ready" if report.ready else "NOT ready"
    cue_at = "-" if report.first_cue_start_s is None else f"{report.first_cue_start_s:g}"
    said_at = (
        "-" if report.time_to_first_situation_s is None else f"{report.time_to_first_situation_s:g}"
    )
    lines = [
        f"# Opening QA: {verdict} ({report.policy})",
        "",
        f"- First frame is content: {'yes' if report.first_frame_is_content else 'no'}. "
        f"{report.first_frame_note}",
        f"- First caption: {cue_at} s, {report.first_cue_text!r}",
        f"- Leading silence: {report.leading_silence_s:.2f} s",
        f"- Cover in timeline: {'yes' if report.cover_in_timeline else 'no'}",
        f"- First situation spoken at: {said_at} s",
        f"- End card only at the end: {'yes' if report.end_card_only_at_end else 'no'}",
    ]
    if report.issues:
        lines += ["", "## Fix", *[f"- {issue}" for issue in report.issues]]
    if report.variant:
        lines += ["", "## Proposed variant", report.variant]
    return "\n".join(lines) + "\n"


def manifest_fields(report: OpeningReport) -> dict:
    """The opening facts the delivery manifest carries."""
    return {
        "first_frame_is_content": report.first_frame_is_content,
        "first_frame_note": report.first_frame_note,
        "first_cue_start_s": report.first_cue_start_s,
        "first_cue_text": report.first_cue_text,
        "leading_silence_s": report.leading_silence_s,
        "cover_in_timeline": report.cover_in_timeline,
        "time_to_first_situation_s": report.time_to_first_situation_s,
        "end_card_only_at_end": report.end_card_only_at_end,
        "opening_ready": report.ready,
        "opening_issues": report.issues,
    }


def _variant(issues: list[str]) -> str:
    steps = []
    text = " ".join(issues)
    if "cover in timeline" in text or "first frame" in text:
        steps.append("start the first range on the first moving shot of the scene")
    if "cover in timeline" in text:
        steps.append("remove the title card or cover from the timeline and compose cover.jpg")
    if "first caption" in text or "no caption" in text:
        steps.append("rebuild captions so cue 1 holds the whole first sentence from 0.0 s")
    if "silence" in text:
        steps.append("trim the in-point to just before the first sound")
    if "end card" in text:
        steps.append("keep the end card in the last seconds only")
    return "Variant: " + "; ".join(steps) + "." if steps else ""


def _pixels(video: Path, at: float) -> np.ndarray | None:
    proc = subprocess.run(
        [find_binary("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{at:.3f}",
         "-i", str(video), "-frames:v", "1", "-vf", "scale=96:-2:flags=area",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=False, timeout=120,
    )  # fmt: skip
    if proc.returncode != 0 or not proc.stdout:
        return None
    return np.frombuffer(proc.stdout, dtype=np.uint8).reshape(-1, 3).astype(float)


def _still_clip(path: Path) -> bool:
    """A video that holds one picture: a cover exported as a clip."""
    if not path.is_file():
        return False
    try:
        info = probe(path)
    except Exception:  # an unreadable overlay is reported by the render itself
        return False
    if info.video is None:
        return False
    if info.video.nb_frames is not None and info.video.nb_frames <= 1:
        return True
    first = _pixels(path, 0.0)
    later = _pixels(path, min(STILL_PROBE, max(0.0, info.duration - 0.05)))
    if first is None or later is None:
        return False
    return float(np.abs(first - later).mean()) < STATIC_LEVELS


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", text.casefold())}
