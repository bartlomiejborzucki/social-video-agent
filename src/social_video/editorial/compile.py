"""Compiling an edit plan into an EDL.

The plan says what to keep and drop in the language of the content. This turns
that into exact ranges, with every boundary snapped to a word edge and every
decision's reason carried through so the EDL stays readable.
"""

from __future__ import annotations

from social_video.editorial.boundaries import snap_range, text_in
from social_video.schemas.brand import OutputProfile
from social_video.schemas.edl import EDL, EDLRange, ReframeMode
from social_video.schemas.plan import EditPlan, PlanAction
from social_video.schemas.transcript import Transcript


def keep_intervals(plan: EditPlan, duration: float) -> list[tuple[float, float, str]]:
    """Work out what survives, as (start, end, reason) triples.

    Explicit keeps win when the plan has any; otherwise everything survives
    except what the plan drops. Both styles are useful: a mechanical pass
    naturally expresses itself as drops, while an agent selecting the best
    moments expresses itself as keeps.
    """
    keeps = [i for i in plan.items if i.action in (PlanAction.KEEP, PlanAction.TIGHTEN)]
    # Accepted cut candidates are subtracted after snapping, in compile_plan.
    drops = [i for i in plan.items if i.action is PlanAction.DROP and not i.cut]

    if keeps:
        ordered = sorted(keeps, key=lambda i: (i.order if i.order is not None else 0, i.start))
        return [(i.start, i.end, i.reason) for i in ordered]

    if not drops:
        return [(0.0, duration, "whole source kept")]

    intervals: list[tuple[float, float, str]] = []
    cursor = 0.0
    for drop in sorted(drops, key=lambda i: i.start):
        if drop.start > cursor:
            intervals.append((cursor, drop.start, ""))
        cursor = max(cursor, drop.end)
    if cursor < duration:
        intervals.append((cursor, duration, ""))
    return [(s, e, r) for s, e, r in intervals if e - s > 0.05]


def compile_plan(
    plan: EditPlan,
    transcript: Transcript,
    profile: OutputProfile,
    *,
    source_id: str | None = None,
    reframe_mode: ReframeMode | None = None,
    name: str = "main",
) -> EDL:
    """Turn a plan into a renderable EDL with word-aligned boundaries."""
    sid = source_id or transcript.source_id
    duration = transcript.duration
    intervals = keep_intervals(plan, duration)
    cuts = sorted(
        (item.start, item.end, item.cut)
        for item in plan.items
        if item.action is PlanAction.DROP and item.cut is not None
    )

    ranges: list[EDLRange] = []
    for start, end, reason in intervals:
        snapped = snap_range(
            transcript,
            start,
            end,
            padding=profile.cut_padding,
            source_duration=duration,
        )
        if snapped.end - snapped.start < 0.08:
            continue
        because = reason or _describe(snapped.start_reason, snapped.end_reason)
        # A cut candidate's span is already word-aligned and already includes
        # the right amount of silence, so it is removed exactly, not re-snapped:
        # snapping could pull a short filler's edge back over the filler.
        for piece_start, piece_end, removed in _subtract(snapped.start, snapped.end, cuts):
            if piece_end - piece_start < 0.08:
                continue
            quote = text_in(transcript, piece_start, piece_end)
            ranges.append(
                EDLRange(
                    source=sid,
                    start=round(piece_start, 4),
                    end=round(piece_end, 4),
                    # Carry the transcribed track through, so the render and the
                    # captions describe the same audio.
                    audio_track=transcript.audio_track,
                    quote=quote[:300],
                    reason=because + (f"; then {', '.join(removed)} removed" if removed else ""),
                )
            )

    if not ranges:
        # Never emit an empty EDL: it would fail schema validation with a less
        # useful message than this one.
        raise ValueError(
            "the plan removes everything; nothing would be left to render. "
            "Check the drop spans in edit-plan.json."
        )

    mode = reframe_mode or ReframeMode(profile.default_reframe)
    return EDL(
        name=name,
        ranges=ranges,
        output_width=profile.width,
        output_height=profile.height,
        default_reframe=mode,
    )


def _subtract(
    start: float, end: float, cuts: list[tuple[float, float, str]]
) -> list[tuple[float, float, list[str]]]:
    """Split ``[start, end)`` around every cut inside it.

    Each piece after the first records the cut that ended the piece before it,
    so the EDL says why a continuous keep became two ranges.
    """
    pieces: list[tuple[float, float, list[str]]] = []
    cursor = start
    pending: list[str] = []
    for cut_start, cut_end, cut_id in cuts:
        if cut_end <= cursor or cut_start >= end:
            continue
        if cut_start > cursor:
            pieces.append((cursor, cut_start, pending))
            pending = []
        pending = [*pending, cut_id]
        cursor = max(cursor, cut_end)
    if cursor < end:
        pieces.append((cursor, end, pending))
    return pieces


def _describe(start_reason: str, end_reason: str) -> str:
    parts = [p for p in (start_reason, end_reason) if p and "left as requested" not in p]
    return "; ".join(parts) if parts else "kept"
