"""Motion QA: the Stage 3 questions about every graphic, as measurements.

Stage 3 used to judge the motion sheet by eye: does each graphic stay long
enough to read, does it cover the captions or a face, does the cut keep
moving without moving too much. Each of those is a number here, reported as
measured against expected, the way platform QA reports safe zones. Every
check is a warning: the editor decides, and accepts a deviation by name.

Where a label, a call to action, a list or steps sit comes from
``motion.layout``, the geometry the compositor draws them with, so a list
moved to the top is measured at the top. For the other graphics
``GRAPHIC_BANDS`` mirrors the compositor's layout as fractions of the frame
height. A face is measured on a real frame: the technical base render on the
Remotion route, which has no graphics drawn over it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from social_video.edl.timeline import Timeline
from social_video.motion.energy import EnergyPreset, energy_preset
from social_video.motion.layout import SceneFrameGeometry, element_band, scene_frame_geometry
from social_video.schemas.brand import CaptionPosition, CaptionStyle
from social_video.schemas.captions import CaptionTrack
from social_video.schemas.config import BrandContract
from social_video.schemas.edl import EDL
from social_video.schemas.motion import TEXTLESS, MotionElement, MotionElementType, MotionPlan
from social_video.schemas.motion_film import FilmSegment
from social_video.schemas.qa import QACheck, QAReport, QASeverity

#: Characters a viewer reads per second, by style pack. Subtitle guidance for
#: adults is 15-17; a louder pack is read in bursts.
READING_CPS = {"editorial": 15.0, "bold-social": 17.0, "tech-minimal": 15.0}
#: Time to notice a graphic before reading starts.
NOTICE_SECONDS = 0.6
#: The rhythm rule is a change every 3-5 s; a second of slack before warning.
LONGEST_STILL = 6.0
#: Share of a face a graphic may cover before it reads as covering the speaker.
FACE_COVER_LIMIT = 0.3
#: Clear space a graphic keeps from a scene frame, as a fraction of the frame
#: height: a pulse and a shadow make a graphic closer than this touch the rim.
FRAME_CLEARANCE = 0.012

#: Vertical extent of each graphic as (top, bottom) fractions of the frame,
#: mirroring remotion/SocialVideo.tsx and DataGraphics.tsx. ``None`` edges
#: follow the safe margins (see `graphic_band`).
GRAPHIC_BANDS: dict[MotionElementType, tuple[float, float]] = {
    MotionElementType.HOOK: (0.07, 0.30),
    MotionElementType.HOOK_CARD: (0.30, 0.70),
    MotionElementType.LOWER_THIRD: (0.765, 0.865),
    MotionElementType.CALLOUT: (0.40, 0.60),
    MotionElementType.END_CARD: (0.0, 1.0),
    MotionElementType.QUOTE: (0.30, 0.70),
    MotionElementType.STAT: (0.38, 0.62),
    MotionElementType.LIST: (0.30, 0.70),
    MotionElementType.CHART: (0.25, 0.75),
    MotionElementType.COMPARE: (0.25, 0.75),
    MotionElementType.STEPS: (0.25, 0.75),
    MotionElementType.LOGO_REVEAL: (0.40, 0.60),
}

#: Face boxes at a moment, as (left, top, right, bottom) fractions of the frame.
FaceProvider = Callable[[float], list[tuple[float, float, float, float]]]


@dataclass(frozen=True)
class Shown:
    """One thing on screen: a plan graphic, or a Motion segment standing in for one."""

    element: MotionElement
    label: str
    film: bool = False


def check_motion(
    edl: EDL,
    plan: MotionPlan | None,
    contract: BrandContract | None,
    *,
    output: str = "",
    captions: CaptionTrack | None = None,
    film_segments: list[FilmSegment] | None = None,
    faces: FaceProvider | None = None,
    faces_note: str = "",
) -> QAReport:
    report = QAReport(output=output, edl=edl.name)
    energy = energy_preset(contract.brand.motion_energy if contract else "lively")
    pack = contract.brand.style_pack if contract else (plan.style if plan else "editorial")
    shown = _shown(plan, film_segments or [])
    margins = contract.safe_margins if contract else {}
    style = contract.brand.captions if contract else None
    place = _Placement.of(contract, margins)

    for item in shown:
        _readable(report, item, pack)
        if style is not None and captions is not None and not item.film:
            _clear_of_captions(report, item, style, captions, place)
        if place.frame is not None and not item.film:
            _clear_of_scene_frame(report, item, shown, place)
        if faces is not None:
            _clear_of_faces(report, item, faces, place)
    if faces is None and shown:
        report.checks.append(
            QACheck(
                name="graphics clear of faces",
                severity=QASeverity.WARNING,
                passed=False,
                message=f"not measured: {faces_note or 'no frame to detect faces on'}",
            )
        )
    _transitions_clear_of_speech(report, plan, captions, faces)
    _budget(report, edl, plan, shown, energy)
    _rhythm(report, edl, plan, shown)
    return report


def _transitions_clear_of_speech(
    report: QAReport,
    plan: MotionPlan | None,
    captions: CaptionTrack | None,
    faces: FaceProvider | None,
) -> None:
    """A transition that blurs or zooms a talking face reads as lips out of sync.

    Each transition's span is compared with the caption words heard during it;
    with a face on screen at that moment it is worth a warning, since the fix
    is a plain cut or a sharp framing jump (`motion suggest` proposes one).
    """
    if plan is None or not plan.transitions or captions is None:
        return
    words: list[_CueWord] = [
        _CueWord(w.start, w.end) for cue in captions.cues for w in cue.words
    ] or [_CueWord(cue.start, cue.end) for cue in captions.cues]
    for transition in plan.transitions:
        low = transition.at - transition.duration / 2
        high = transition.at + transition.duration / 2
        talking = sum(max(0.0, min(high, w.end) - max(low, w.start)) for w in words)
        if talking <= 0.05:
            continue
        on_screen = faces(transition.at) if faces is not None else None
        if on_screen is not None and not on_screen:
            continue
        seen = "a face is on screen" if on_screen else "faces were not measured"
        report.checks.append(
            QACheck(
                name=f"transition at {transition.at:.2f}s clear of speech",
                severity=QASeverity.WARNING,
                passed=False,
                at=round(transition.at, 3),
                measured=round(talking, 3),
                expected=0.0,
                message=(
                    f"the {transition.style.value} transition runs over {talking:.2f}s of speech "
                    f"and {seen}; a moving mouth under it reads as audio out of sync. "
                    "Use a plain cut or a sharp framing jump (zoom on the range)."
                ),
            )
        )


@dataclass(frozen=True)
class _CueWord:
    start: float
    end: float


def graphic_band(kind: MotionElementType, margins: dict[str, float]) -> tuple[float, float] | None:
    """The vertical extent of a graphic, as fractions of the frame height."""
    top = margins.get("top", 6.0) / 100.0
    bottom = margins.get("bottom", 6.0) / 100.0
    if kind is MotionElementType.CHAPTER:
        return top + 0.02, top + 0.14
    if kind is MotionElementType.LABEL:
        return top, top + 0.06
    if kind is MotionElementType.CTA:
        low = 1.0 - bottom - 0.16
        return low - 0.06, low
    if kind is MotionElementType.PROGRESS:
        return top * 0.5, top * 0.5 + 0.01
    return GRAPHIC_BANDS.get(kind)


@dataclass(frozen=True)
class _Placement:
    """Where this contract's graphics are drawn, for the overlap checks."""

    margins: dict[str, float]
    height: int = 1920
    label_style: str = "chip"
    frame: SceneFrameGeometry | None = None

    @classmethod
    def of(cls, contract: BrandContract | None, margins: dict[str, float]) -> _Placement:
        if contract is None:
            return cls(margins=margins)
        frame = None
        if contract.brand.label_style == "scene_frame":
            frame = scene_frame_geometry(
                contract.brand.captions,
                width=contract.output_width,
                height=contract.output_height,
                safe_margins=margins,
            )
        return cls(
            margins=margins,
            height=contract.output_height,
            label_style=contract.brand.label_style,
            frame=frame,
        )

    def band(self, element: MotionElement) -> tuple[float, float] | None:
        placed = element_band(
            element,
            height=self.height,
            margins=self.margins,
            label_style=self.label_style,
            frame=self.frame,
        )
        return placed if placed is not None else graphic_band(element.type, self.margins)

    def framed(self, element: MotionElement) -> bool:
        return self.frame is not None and element.type is MotionElementType.LABEL


def caption_band(style: CaptionStyle) -> tuple[float, float]:
    """Where the captions sit, as fractions of the frame height."""
    margin = style.margin_pct / 100.0
    depth = style.max_lines * style.font_size_pct / 100.0 * 1.3
    if style.position is CaptionPosition.TOP:
        return margin, margin + depth
    if style.position is CaptionPosition.CENTER:
        return 0.5 - depth / 2, 0.5 + depth / 2
    return 1.0 - margin - depth, 1.0 - margin


def faces_from_video(video: Path, *, samples_per_second: float = 2.0) -> FaceProvider:
    """Detect faces across ``video`` once, and answer for any moment from that."""
    from social_video.ffmpeg.probe import probe
    from social_video.reframe.detect import detect_faces

    info = probe(video)
    if info.video is None:
        return lambda _t: []
    width, height = info.video.display_size
    found = detect_faces(video, samples_per_second=samples_per_second)

    def at(moment: float) -> list[tuple[float, float, float, float]]:
        near = [f for f in found if abs(f.t - moment) <= 0.5 / samples_per_second + 0.01]
        if not near:
            return []
        frame = min(near, key=lambda f: abs(f.t - moment))
        return [
            (f.x / width, f.y / height, (f.x + f.width) / width, (f.y + f.height) / height)
            for f in frame.faces
        ]

    return at


def moment_verdicts(moments: list[tuple[float, str]], report: QAReport) -> list[str]:
    """The worst finding near each review-sheet moment: ok, warning or error."""
    verdicts = []
    for at, _label in moments:
        near = [
            c
            for c in report.checks
            if c.at is not None and not c.passed and not c.accepted and at - 0.75 <= c.at <= at
        ]
        if any(c.severity is QASeverity.ERROR for c in near):
            verdicts.append("error")
        elif near:
            verdicts.append("warning")
        else:
            verdicts.append("ok")
    return verdicts


# -- checks -------------------------------------------------------------------


def _shown(plan: MotionPlan | None, segments: list[FilmSegment]) -> list[Shown]:
    shown = [
        Shown(element=e, label=f"{e.type.value} at {e.start:.2f}s")
        for e in (plan.elements if plan else [])
    ]
    for segment in segments:
        # Without the graphic it replaced, its words are unknown: built
        # unvalidated with no text, it is timed and placed but not read.
        element = segment.replaced_element or MotionElement.model_construct(
            type=segment.element_type,
            start=segment.start_in_output,
            end=segment.start_in_output + segment.duration,
            text="",
            secondary_text=None,
            items=[],
            reason="Claude Motion segment.",
        )
        shown.append(
            Shown(
                element=element,
                label=f"motion film {segment.scene_id} at {segment.start_in_output:.2f}s",
                film=True,
            )
        )
    return sorted(shown, key=lambda s: s.element.start)


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


def _readable(report: QAReport, item: Shown, pack: str) -> None:
    element = item.element
    if element.type in TEXTLESS:
        return
    chars = len(element.text) + len(element.secondary_text or "") + sum(map(len, element.items))
    if chars == 0:
        return
    cps = READING_CPS.get(pack, 15.0)
    needed = round(NOTICE_SECONDS + chars / cps, 2)
    shown = round(element.end - element.start, 2)
    _add(
        report,
        f"{item.label} readable",
        shown >= needed,
        f"{chars} characters on screen for {shown:.2f}s; reading them at {cps:g} per second "
        f"takes {needed:.2f}s",
        at=element.start,
        measured=shown,
        expected=needed,
    )


def _clear_of_captions(
    report: QAReport,
    item: Shown,
    style: CaptionStyle,
    captions: CaptionTrack,
    place: _Placement,
) -> None:
    element = item.element
    # A scene frame holds the captions by design; its title sits on the rim.
    if place.framed(element):
        return
    band = place.band(element)
    if band is None or element.type is MotionElementType.END_CARD:
        return
    spoken = [c for c in captions.cues if c.start < element.end and element.start < c.end]
    if not spoken:
        return
    low, high = caption_band(style)
    overlap = max(0.0, min(band[1], high) - max(band[0], low))
    _add(
        report,
        f"{item.label} clear of captions",
        overlap <= 0.0,
        (
            f"overlaps the caption band by {overlap:.0%} of the frame height while "
            f"{len(spoken)} cue(s) are on screen"
            if overlap > 0
            else "clear of the caption band"
        ),
        at=element.start,
        measured=round(overlap * 100, 1),
        expected=0.0,
    )


def _clear_of_scene_frame(
    report: QAReport, item: Shown, shown: list[Shown], place: _Placement
) -> None:
    """A graphic on screen with a scene frame must not cut across the frame."""
    element = item.element
    if place.frame is None or element.type in (MotionElementType.LABEL, MotionElementType.END_CARD):
        return
    framing = [
        s.element
        for s in shown
        if place.framed(s.element)
        and s.element.start < element.end
        and element.start < s.element.end
    ]
    band = place.band(element)
    if not framing or band is None:
        return
    top = place.frame.tab_top / place.height - FRAME_CLEARANCE
    bottom = place.frame.bottom / place.height + FRAME_CLEARANCE
    overlap = max(0.0, min(band[1], bottom) - max(band[0], top))
    hint = " Set position: top." if element.type is MotionElementType.CTA else ""
    _add(
        report,
        f"{item.label} clear of the scene frame",
        overlap <= 0.0,
        (
            f"touches the scene frame of {framing[0].text!r}: {overlap:.1%} of the frame "
            f"height inside it or its {FRAME_CLEARANCE:.1%} clearance.{hint}"
            if overlap > 0
            else "clear of the scene frame"
        ),
        at=element.start,
        measured=round(overlap * 100, 1),
        expected=0.0,
    )


def _clear_of_faces(report: QAReport, item: Shown, faces: FaceProvider, place: _Placement) -> None:
    element = item.element
    # A full-frame segment hides the face it covers, so look just after it.
    middle = element.end + 0.1 if item.film else (element.start + element.end) / 2
    boxes = faces(middle)
    if not boxes:
        return
    if item.film:
        _add(
            report,
            f"{item.label} hides the speaker",
            False,
            f"a full-frame segment hides {len(boxes)} face(s) for "
            f"{element.end - element.start:.1f}s",
            at=element.start,
            measured=round(element.end - element.start, 2),
        )
        return
    band = place.band(element)
    if band is None or element.type is MotionElementType.END_CARD:
        return
    covered = max(
        max(0.0, min(bottom, band[1]) - max(top, band[0])) / max(bottom - top, 1e-6)
        for _left, top, _right, bottom in boxes
    )
    _add(
        report,
        f"{item.label} clear of faces",
        covered <= FACE_COVER_LIMIT,
        f"covers {covered:.0%} of the largest overlapping face; up to "
        f"{FACE_COVER_LIMIT:.0%} reads as clear",
        at=element.start,
        measured=round(covered * 100, 1),
        expected=FACE_COVER_LIMIT * 100,
    )


def _budget(
    report: QAReport, edl: EDL, plan: MotionPlan | None, shown: list[Shown], energy: EnergyPreset
) -> None:
    minutes = max(edl.total_duration, 1.0) / 60.0
    accents = len(shown) + (len(plan.punch_ins) if plan else 0)
    rate = round(accents / minutes, 1)
    allowed = round(energy.accents_per_minute * 1.25, 1)
    _add(
        report,
        "accents per minute",
        rate <= allowed,
        f"{accents} graphic(s) and punch-in(s) over {edl.total_duration:.1f}s is {rate:g}/min; "
        f"{energy.name} proposes about {energy.accents_per_minute:g}/min",
        measured=rate,
        expected=allowed,
    )
    transitions = len(plan.transitions) if plan else 0
    t_rate = round(transitions / minutes, 1)
    _add(
        report,
        "transitions per minute",
        t_rate <= energy.transitions_per_minute,
        f"{transitions} transition(s) is {t_rate:g}/min; {energy.name} allows "
        f"{energy.transitions_per_minute:g}/min",
        measured=t_rate,
        expected=energy.transitions_per_minute,
    )


def _rhythm(report: QAReport, edl: EDL, plan: MotionPlan | None, shown: list[Shown]) -> None:
    total = edl.total_duration
    changes = {0.0, total}
    changes.update(s.output_start for s in Timeline(edl).slices)
    # A graphic leaving the screen is as much a change as one arriving.
    changes.update(s.element.start for s in shown)
    changes.update(s.element.end for s in shown)
    if plan is not None:
        changes.update(p.start for p in plan.punch_ins)
        changes.update(p.end for p in plan.punch_ins)
        changes.update(t.at for t in plan.transitions)
    times = sorted(t for t in changes if 0.0 <= t <= total)
    gap, at = max(((b - a, a) for a, b in pairwise(times)), default=(0.0, 0.0))
    _add(
        report,
        "something changes every few seconds",
        gap <= LONGEST_STILL,
        f"the longest stretch without a cut, graphic, punch-in or transition is "
        f"{gap:.1f}s, from {at:.1f}s",
        at=round(at, 3),
        measured=round(gap, 2),
        expected=LONGEST_STILL,
    )
