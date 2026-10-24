"""Material for an editorial read of a reference video, and a check of the read.

A transcript says what was said; it does not say what the viewer saw first,
what was only written on screen, or when the product appeared. The code pulls
stills where those things tend to happen -- the first frame, the opening
seconds, each cut, the middle of each shot, the last frame -- keeps the timed
transcript, and states what such a sample cannot show. The agent reads that
material in its own session and writes ``ReferenceAnalysis``; ``check_analysis``
only checks that every claim is anchored to a moment that exists and that
hypotheses cite observations. Nothing here judges the video.
"""

from __future__ import annotations

import logging
from itertools import pairwise
from pathlib import Path

import numpy as np

from social_video.analysis.reference import MIN_PAUSE, MIN_SHOT, analyze_reference
from social_video.analysis.scenes import detect_scenes, scene_cut_times
from social_video.analysis.silence import find_pauses, find_pauses_from_transcript
from social_video.ffmpeg.probe import probe
from social_video.ffmpeg.run import run_ffmpeg
from social_video.schemas.reference_analysis import (
    FrameReason,
    ReferenceAnalysis,
    ReferenceFrame,
    ReferenceMaterial,
    ReferenceMeasures,
)
from social_video.schemas.style_reference import StyleReference
from social_video.schemas.transcript import Transcript

log = logging.getLogger(__name__)

#: Stills kept by default; the first, the opening and the last are never thinned.
FRAME_LIMIT = 40
#: The opening is sampled this densely, for this long.
OPENING_STEP = 0.5
OPENING_SECONDS = 3.0
#: Moments closer than this collapse into one still.
MIN_GAP = 0.15
#: A still just after a cut, so it shows the new shot rather than the old one.
AFTER_CUT = 0.05
FRAME_WIDTH = 540


def editorial_moments(
    cuts: list[float], duration: float, *, limit: int = FRAME_LIMIT
) -> list[tuple[float, FrameReason]]:
    """Where to look: the first frame, the opening, cuts, shot middles, the last frame."""
    last = max(0.0, duration - 0.25)
    fixed: list[tuple[float, FrameReason]] = [(0.0, FrameReason.FIRST)]
    step = OPENING_STEP
    while step <= min(OPENING_SECONDS, last) + 1e-9:
        fixed.append((round(step, 3), FrameReason.OPENING))
        step += OPENING_STEP
    fixed.append((round(last, 3), FrameReason.LAST))

    inside = sorted(c for c in cuts if 0.0 < c < duration)
    optional: list[tuple[float, FrameReason]] = []
    for cut in inside:
        optional.append((round(min(cut + AFTER_CUT, last), 3), FrameReason.CUT))
    for start, end in pairwise([0.0, *inside, duration]):
        optional.append((round((start + end) / 2, 3), FrameReason.SHOT_MIDDLE))

    def far(at: float, kept: list[tuple[float, FrameReason]]) -> bool:
        return all(abs(at - other) >= MIN_GAP for other, _ in kept)

    chosen = [m for i, m in enumerate(fixed) if far(m[0], fixed[:i])]
    # Cuts first, then middles: a cut is where the picture changes.
    optional.sort(key=lambda m: (m[1] is not FrameReason.CUT, m[0]))
    candidates = [m for m in optional if far(m[0], chosen)]
    room = max(0, limit - len(chosen))
    if len(candidates) > room:
        cuts_only = [m for m in candidates if m[1] is FrameReason.CUT]
        pool = cuts_only if len(cuts_only) >= room else candidates
        picks = np.linspace(0, len(pool) - 1, room).round().astype(int) if room else []
        candidates = [pool[int(i)] for i in sorted(set(picks))]
    for moment in candidates:
        if far(moment[0], chosen):
            chosen.append(moment)
    return sorted(chosen)


def extract_frames(
    video: Path, moments: list[tuple[float, FrameReason]], directory: Path
) -> list[ReferenceFrame]:
    """One JPEG per moment; a moment ffmpeg cannot decode is dropped and logged."""
    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.glob("f*.jpg"):
        stale.unlink()
    frames: list[ReferenceFrame] = []
    for index, (at, reason) in enumerate(moments):
        frame_id = f"f{index:03d}"
        path = directory / f"{frame_id}-{at:07.2f}s.jpg"
        try:
            run_ffmpeg(
                ["-v", "error", "-y", "-ss", f"{at:.3f}", "-i", str(video),
                 "-frames:v", "1", "-vf", f"scale={FRAME_WIDTH}:-2", "-q:v", "3", str(path)],
                desc=f"reference still at {at:.2f}s", timeout=120,
            )  # fmt: skip
        except Exception as exc:
            log.warning("no still at %.2fs: %s", at, exc)
            continue
        if path.is_file() and path.stat().st_size > 0:
            frames.append(ReferenceFrame(id=frame_id, at=at, reason=reason, path=str(path)))
    return frames


def limitations(
    frames: list[ReferenceFrame], duration: float, *, transcript: Transcript | None, audio: bool
) -> list[str]:
    found = [
        f"{len(frames)} stills from {duration:.1f} s: motion, gestures and anything shown "
        "between stills are not seen",
        "on-screen text is read from the stills only; text shown briefly between them is missed",
        "cuts come from scene detection, which misses jump cuts inside one framing",
    ]
    if transcript is None:
        found.append("not transcribed: what is said was not analysed (run with --transcribe)")
    else:
        model = transcript.provider_model or transcript.provider
        found.append(f"automatic transcript ({model}): check a word before quoting it")
    if not audio:
        found.append("no audio stream: sound and voice were not analysed")
    return found


def prepare_editorial(
    video: Path,
    directory: Path,
    *,
    transcript: Transcript | None = None,
    transcript_path: Path | None = None,
    sheet: Path | None = None,
    frame_limit: int = FRAME_LIMIT,
) -> tuple[StyleReference, ReferenceMaterial]:
    """Measure ``video`` and write the stills an editorial read starts from."""
    cuts = scene_cut_times(detect_scenes(video, min_scene_len=MIN_SHOT))
    style = analyze_reference(video, transcript=transcript, sheet=sheet, cuts=cuts)
    info = probe(video)
    if transcript is not None and transcript.words:
        pauses = find_pauses_from_transcript(transcript, minimum=MIN_PAUSE)
    elif info.audio:
        pauses = find_pauses(video, minimum=MIN_PAUSE)
    else:
        pauses = []
    longest = sorted(pauses, key=lambda p: p.duration, reverse=True)[:3]

    frames = extract_frames(
        video, editorial_moments(cuts, style.duration, limit=frame_limit), directory / "frames"
    )
    measures = ReferenceMeasures(
        first_cut_seconds=style.shots.first_cut_seconds,
        first_sentence_seconds=style.speech.first_sentence_seconds if style.speech else None,
        longest_pauses=[(round(p.start, 2), round(p.end, 2)) for p in longest],
        cut_times=[round(c, 3) for c in sorted(cuts) if 0.0 < c < style.duration],
    )
    material = ReferenceMaterial(
        reference=str(video),
        reference_fingerprint=style.reference_fingerprint,
        duration=style.duration,
        frames=frames,
        transcript=str(transcript_path) if transcript_path is not None else None,
        measures=measures,
        limitations=limitations(
            frames, style.duration, transcript=transcript, audio=bool(info.audio)
        ),
    )
    return style, material


def check_analysis(analysis: ReferenceAnalysis, material: ReferenceMaterial) -> list[str]:
    """Problems that make the read untrustworthy; empty when it holds together."""
    problems: list[str] = []
    if analysis.reference_fingerprint != material.reference_fingerprint:
        problems.append("the analysis was written for a different reference file")
    frame_ids = {frame.id for frame in material.frames}
    seen: set[str] = set()
    for name, section in analysis.sections():
        if not section.observations and not section.not_found:
            problems.append(f"{name}: no observation; say 'not_found' if the video has none")
        for obs in section.observations:
            if obs.id in seen:
                problems.append(f"{name}: observation id {obs.id} is used twice")
            seen.add(obs.id)
            if obs.at is not None and obs.at > material.duration + 0.05:
                problems.append(
                    f"{name}: {obs.id} at {obs.at:.2f}s is past the end ({material.duration:.2f}s)"
                )
            if obs.frame is not None and obs.frame not in frame_ids:
                problems.append(f"{name}: {obs.id} cites frame {obs.frame}, which was not pulled")
    for name, section in analysis.sections():
        for hypothesis in section.hypotheses:
            missing = [ref for ref in hypothesis.based_on if ref not in seen]
            if missing:
                problems.append(
                    f"{name}: a hypothesis cites unknown observations {', '.join(missing)}"
                )
    for span in analysis.needs_review:
        if span.end <= span.start or span.end > material.duration + 0.05:
            problems.append(
                f"needs_review {span.start:.2f}-{span.end:.2f}s is not inside the video"
            )
    return problems


def with_material_limits(
    analysis: ReferenceAnalysis, material: ReferenceMaterial
) -> ReferenceAnalysis:
    """The analysis with every limitation of its material stated."""
    missing = [item for item in material.limitations if item not in analysis.limitations]
    if not missing:
        return analysis
    return analysis.model_copy(update={"limitations": [*missing, *analysis.limitations]})


def _anchor(obs) -> str:
    parts = []
    if obs.at is not None:
        parts.append(f"{obs.at:.2f} s")
    if obs.frame is not None:
        parts.append(obs.frame)
    return " · ".join(parts)


def analysis_markdown(analysis: ReferenceAnalysis, material: ReferenceMaterial) -> str:
    titles = {
        "opening_attention": "Opening: what stops the viewer",
        "said_vs_written": "Said vs. written on screen",
        "promise": "Promise",
        "development": "Development",
        "payoff": "Payoff",
        "ending": "Ending",
    }
    lines = [f"# Reference analysis: {Path(material.reference).name}", ""]
    lines += [
        "Observations are anchored to a time or a still. Hypotheses are guesses about "
        "why something works and cite the observations they rest on.",
        "",
    ]
    for name, section in analysis.sections():
        lines += [f"## {titles[name]}", ""]
        if section.not_found:
            lines += [f"Not found: {section.not_found}", ""]
        for obs in section.observations:
            lines.append(f"- **{obs.id}** [{_anchor(obs)}, {obs.evidence.value}] {obs.text}")
        for hypothesis in section.hypotheses:
            lines.append(
                f"- *Hypothesis:* {hypothesis.text} (based on {', '.join(hypothesis.based_on)})"
            )
        lines.append("")
    lines += ["## Pattern to reuse", "", analysis.transferable_pattern, ""]
    if analysis.not_to_copy:
        lines += ["## Not to copy", ""] + [f"- {item}" for item in analysis.not_to_copy] + [""]
    lines += ["## Limitations", ""] + [f"- {item}" for item in analysis.limitations] + [""]
    if analysis.needs_review:
        lines += ["## Watch these stretches", ""]
        lines += [
            f"- {span.start:.2f}-{span.end:.2f} s: {span.reason}" for span in analysis.needs_review
        ]
        lines.append("")
    return "\n".join(lines)
