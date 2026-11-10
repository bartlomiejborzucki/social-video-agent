"""Reel check: the short-form practices that measure, as advisory findings.

What decides reach on Reels, TikTok and Shorts is whether people stay past the
first seconds, finish, replay and send the video on. None of that can be
guaranteed by an edit, and the published numbers behind it are mostly creator
research rather than platform documentation. What an edit can do is avoid the
known ways of losing a viewer, and those are measurable:

- the situation is heard within the first second (hook speed);
- the length sits in the destination's completion window;
- no dead air inside the speech, and no tail after the last word;
- the picture changes every few seconds;
- every spoken word is captioned, for viewing with the sound off;
- the end does not linger on a card;
- the publishing copy asks for a save or a send, the signals that carry a reel
  to people who do not follow the account.

Every finding is a warning. It never blocks a delivery: the editor decides.
"""

from __future__ import annotations

import re
from itertools import pairwise
from pathlib import Path

from pydantic import Field

from social_video.edl.timeline import Timeline
from social_video.errors import FFmpegError
from social_video.ffmpeg.probe import probe
from social_video.ffmpeg.run import run_ffmpeg
from social_video.fsutil import atomic_write_text
from social_video.schemas.base import Artifact, save_artifact
from social_video.schemas.captions import CaptionTrack
from social_video.schemas.edl import EDL
from social_video.schemas.motion import MotionElementType, MotionPlan
from social_video.schemas.platform import PlatformSpec
from social_video.schemas.publish import PublishMetadata
from social_video.schemas.qa import QACheck, QAReport, QASeverity

#: The situation should be heard this soon; viewers decide in one to two.
HOOK_SECONDS = 1.0
#: A pause this long inside speech reads as dead air on a phone.
DEAD_AIR_SECONDS = 0.7
#: The picture should change at least this often.
LONGEST_HOLD = 5.0
#: Silence allowed after the last word before the end.
TAIL_SECONDS = 0.6
#: An end card longer than this costs completion.
END_CARD_SECONDS = 2.0
#: The last seconds should carry what next: a call to action, a teaser, a card.
ENDING_SECONDS = 4.0
#: A phrase caption on screen longer than this is read, then stared at.
PHRASE_CUE_SECONDS = 2.5
CAPTION_COVERAGE = 0.95
SILENCE_FLOOR_DB = -40
#: Words asking for the two signals that reach people beyond followers.
SHARE_ASK = re.compile(
    r"\b(zapisz|zachowaj|udost[eę]pnij|wy[sś]lij|podeślij|prze[sś]lij|oznacz|"
    r"save|share|send|tag)\w*",
    re.IGNORECASE,
)
_SILENCE = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)|silence_end:\s*(-?\d+(?:\.\d+)?)")


class ReelCheck(Artifact):
    """The advisory findings for one delivered video."""

    video: str
    platforms: list[str] = Field(default_factory=list)
    passed: int = Field(ge=0)
    total: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
    report: QAReport


def check_reel(
    video: Path,
    edl: EDL,
    *,
    captions: CaptionTrack | None,
    plan: MotionPlan | None = None,
    platforms: list[PlatformSpec] | None = None,
    publish: PublishMetadata | None = None,
    analysis_dir: Path | None = None,
) -> ReelCheck:
    report = QAReport(output=str(video), edl=edl.name)
    duration = probe(video).duration
    words = [w for cue in (captions.cues if captions else []) for w in cue.words]
    _hook(report, words)
    for spec in platforms or []:
        _length(report, spec, duration)
    _dead_air(report, video, words)
    _tail(report, words, duration)
    _holds(report, edl, plan)
    _end_card(report, plan, duration)
    if plan is not None:
        _ending(report, plan, captions, duration)
    _coverage(report, captions, words)
    if captions is not None and captions.mode == "phrase":
        _phrase_cues(report, captions)
    if captions is not None and captions.origin == "story":
        _story_question(report, captions)
    if publish is not None:
        _share_ask(report, publish)
    warnings = [f"{c.name}: {c.message}" for c in report.checks if not c.passed]
    result = ReelCheck(
        video=str(video),
        platforms=[spec.name for spec in platforms or []],
        passed=sum(c.passed for c in report.checks),
        total=len(report.checks),
        warnings=warnings,
        report=report,
    )
    if analysis_dir is not None:
        save_artifact(result, analysis_dir / "reel-check.json")
        atomic_write_text(analysis_dir / "reel-check.md", render(result))
    return result


def render(result: ReelCheck) -> str:
    lines = [f"# Reel check: {result.passed}/{result.total}", ""]
    for check in result.report.checks:
        lines.append(f"- {'ok' if check.passed else 'warn'} {check.name}: {check.message}")
    lines += ["", "Advisory only: reach depends on the audience, not on any checklist."]
    return "\n".join(lines) + "\n"


# -- checks -------------------------------------------------------------------


def _add(report: QAReport, name: str, ok: bool, message: str, **numbers) -> None:
    report.checks.append(
        QACheck(
            name=name,
            severity=QASeverity.INFO if ok else QASeverity.WARNING,
            passed=ok,
            message=message,
            **numbers,
        )
    )


def _hook(report: QAReport, words) -> None:
    if not words:
        _add(report, "situation heard at once", False,
             "no timed words in the captions, so the hook cannot be timed")  # fmt: skip
        return
    first = min(w.start for w in words)
    _add(
        report,
        "situation heard at once",
        first <= HOOK_SECONDS,
        f"the first word is heard at {first:.2f}s; viewers decide in the first one to two "
        "seconds, so open on the situation, not on a greeting or an introduction",
        at=first,
        measured=round(first, 2),
        expected=HOOK_SECONDS,
    )


def _length(report: QAReport, spec: PlatformSpec, duration: float) -> None:
    ok = spec.sweet_spot_min <= duration <= spec.sweet_spot_max
    _add(
        report,
        f"length suits {spec.name}",
        ok,
        f"{duration:.1f}s; completion is best around {spec.sweet_spot_min:g}-"
        f"{spec.sweet_spot_max:g}s on {spec.name} (directional: compare with your own "
        "analytics)",
        measured=round(duration, 2),
        expected=spec.sweet_spot_max,
    )


def _dead_air(report: QAReport, video: Path, words) -> None:
    if not words:
        return
    start, end = min(w.start for w in words), max(w.end for w in words)
    gaps = [(s, e) for s, e in _silences(video) if s > start + 0.05 and e < end - 0.05]
    longest = max((e - s for s, e in gaps), default=0.0)
    _add(
        report,
        "no dead air inside the speech",
        longest <= DEAD_AIR_SECONDS,
        (
            f"longest pause {longest:.2f}s"
            + (f" at {gaps[0][0]:.1f}s; tighten it to keep the rhythm" if gaps else "")
        ),
        at=round(gaps[0][0], 3) if gaps else None,
        measured=round(longest, 2),
        expected=DEAD_AIR_SECONDS,
    )


def _tail(report: QAReport, words, duration: float) -> None:
    if not words:
        return
    tail = max(0.0, duration - max(w.end for w in words))
    _add(
        report,
        "ends on the payoff",
        tail <= TAIL_SECONDS,
        f"{tail:.2f}s after the last word; end right after the point lands, which also "
        "makes a replay feel like a loop",
        measured=round(tail, 2),
        expected=TAIL_SECONDS,
    )


def _holds(report: QAReport, edl: EDL, plan: MotionPlan | None) -> None:
    total = edl.total_duration
    changes = {0.0, total}
    changes.update(s.output_start for s in Timeline(edl).slices)
    changes.update(o.start_in_output for o in edl.overlays)
    changes.update(o.end_in_output for o in edl.overlays)
    if plan is not None:
        for element in plan.elements:
            changes.update((element.start, element.end))
        for punch in plan.punch_ins:
            changes.update((punch.start, punch.end))
        changes.update(t.at for t in plan.transitions)
        for effect in plan.effects:
            changes.update((effect.start, effect.end))
    times = sorted(t for t in changes if 0.0 <= t <= total)
    gap, at = max(((b - a, a) for a, b in pairwise(times)), default=(0.0, 0.0))
    _add(
        report,
        "the picture changes every few seconds",
        gap <= LONGEST_HOLD,
        f"the longest unchanged stretch is {gap:.1f}s from {at:.1f}s; a cut, a punch-in or "
        "a graphic every three to five seconds keeps a viewer",
        at=round(at, 3),
        measured=round(gap, 2),
        expected=LONGEST_HOLD,
    )


def _end_card(report: QAReport, plan: MotionPlan | None, duration: float) -> None:
    cards = [e for e in (plan.elements if plan else []) if e.type is MotionElementType.END_CARD]
    longest = max((e.end - e.start for e in cards), default=0.0)
    _add(
        report,
        "no lingering end card",
        longest <= END_CARD_SECONDS,
        f"end card {longest:.1f}s" if cards else "no end card",
        measured=round(longest, 2),
        expected=END_CARD_SECONDS,
    )


#: A spoken ask in the last seconds closes a reel as well as a graphic does.
FOLLOW_ASK = re.compile(r"\b(obserwuj|zaobserwuj|follow|subscribe|subskrybuj)\w*", re.IGNORECASE)


def _ending(
    report: QAReport, plan: MotionPlan, captions: CaptionTrack | None, duration: float
) -> None:
    """Something in the last seconds says what next: a graphic, or the words."""
    closing = (MotionElementType.CTA, MotionElementType.END_TEASER, MotionElementType.END_CARD)
    window = max(0.0, duration - ENDING_SECONDS)
    found = [e.type.value for e in plan.elements if e.type in closing and e.end > window]
    said = " ".join(c.text for c in (captions.cues if captions else []) if c.end > window)
    if SHARE_ASK.search(said) or FOLLOW_ASK.search(said):
        found.append("a spoken ask")
    _add(
        report,
        "the end says what next",
        bool(found),
        f"{', '.join(sorted(set(found)))} in the last {ENDING_SECONDS:g} s"
        if found
        else f"no call to action, end teaser or end card in the last {ENDING_SECONDS:g} s; "
        "an end_teaser over the speaker keeps the face and says what comes next",
    )


def _spoken_span(cue) -> float:
    """How long a cue's words take to say; a cue held through a pause is not longer."""
    if cue.words:
        return cue.words[-1].end - cue.words[0].start
    return cue.end - cue.start


def _phrase_cues(report: QAReport, captions: CaptionTrack) -> None:
    # The first cue carries the whole first sentence by the opening rule.
    later = sorted(captions.cues, key=lambda c: c.start)[1:]
    long = [c for c in later if _spoken_span(c) > PHRASE_CUE_SECONDS + 1e-6]
    worst = max(long, key=_spoken_span, default=None)
    _add(
        report,
        "phrase captions change often",
        not long,
        f"{len(long)} cue(s) said over more than {PHRASE_CUE_SECONDS:g} s, the longest "
        f"{_spoken_span(worst):.1f}s at {worst.start:.1f}s"
        if worst
        else f"every cue after the first is said within {PHRASE_CUE_SECONDS:g} s",
        at=round(worst.start, 3) if worst else None,
        measured=round(_spoken_span(worst), 2) if worst else None,
        expected=PHRASE_CUE_SECONDS,
    )


def _story_question(report: QAReport, captions: CaptionTrack) -> None:
    last = captions.cues[-1].text.strip() if captions.cues else ""
    _add(
        report,
        "the story ends on a question",
        last.endswith("?"),
        f"last sentence {last!r}"
        + ("" if last.endswith("?") else "; a question at the end invites the comments"),
    )


def _coverage(report: QAReport, captions: CaptionTrack | None, words) -> None:
    if captions is None or not captions.cues:
        _add(report, "captioned for sound off", False,
             "no captions; most short-form viewing starts muted")  # fmt: skip
        return
    spoken = max(w.end for w in words) - min(w.start for w in words) if words else 0.0
    shown = sum(c.end - c.start for c in captions.cues)
    share = min(1.0, shown / spoken) if spoken > 0 else 1.0
    _add(
        report,
        "captioned for sound off",
        share >= CAPTION_COVERAGE,
        f"captions cover {share:.0%} of the speech",
        measured=round(share * 100, 1),
        expected=CAPTION_COVERAGE * 100,
    )


def _share_ask(report: QAReport, publish: PublishMetadata) -> None:
    text = " ".join(filter(None, [publish.cta or "", publish.description]))
    _add(
        report,
        "asks for a save or a send",
        bool(SHARE_ASK.search(text)),
        "the copy asks viewers to save or send the reel"
        if SHARE_ASK.search(text)
        else "the copy does not ask for a save or a send, the signals that reach people "
        "beyond your followers; end the description with one honest ask",
    )


def _silences(video: Path) -> list[tuple[float, float]]:
    info = probe(video)
    if not info.has_audio:
        return []
    try:
        heard = run_ffmpeg(
            ["-i", str(video), "-map", "0:a:0",
             "-af", f"silencedetect=noise={SILENCE_FLOOR_DB}dB:d={DEAD_AIR_SECONDS / 2:.2f}",
             "-f", "null", "-"],
            desc=f"find the silences in {video.name}", timeout=600,
        )  # fmt: skip
    except FFmpegError as exc:
        heard = exc.stderr
    spans: list[tuple[float, float]] = []
    start: float | None = None
    for began, ended in _SILENCE.findall(heard):
        if began:
            start = float(began)
        elif ended and start is not None:
            spans.append((start, float(ended)))
            start = None
    return spans
