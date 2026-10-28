"""Compiling an edit plan into an EDL.

The plan says what to keep and drop in the language of the content. This turns
that into exact ranges, with every boundary snapped to a word edge and every
decision's reason carried through so the EDL stays readable.
"""

from __future__ import annotations

from social_video.editorial.acoustic import AcousticEdges
from social_video.editorial.boundaries import snap_range, text_in
from social_video.schemas.brand import OutputProfile
from social_video.schemas.edl import EDL, EDLRange, ReframeMode, VisualFillStrategy
from social_video.schemas.plan import EditPlan, PlanAction, PlanItem
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


def is_multi_source(plan: EditPlan, primary: str) -> bool:
    """Whether the plan keeps more than the primary recording, or mixes them."""
    return any(
        item.source != primary or item.audio_source is not None or item.reframe is not None
        for item in plan.kept
    )


def compile_plan(
    plan: EditPlan,
    transcript: Transcript,
    profile: OutputProfile,
    *,
    source_id: str | None = None,
    reframe_mode: ReframeMode | None = None,
    name: str = "main",
    transcripts: dict[str, Transcript] | None = None,
    edges: AcousticEdges | None = None,
) -> EDL:
    """Turn a plan into a renderable EDL with word-aligned boundaries.

    A plan whose kept items come from several recordings -- or put one
    recording's voice under another's picture, or fix an item's framing --
    is compiled item by item, in ``order``, each against the transcript of the
    recording it keeps the words of (``transcripts``, by source id).

    With ``edges``, each range's outer edges then move from the word times to
    where the speech is heard to start and stop; the moves are kept on it.
    """
    sid = source_id or transcript.source_id
    if is_multi_source(plan, sid):
        known = {sid: transcript, **(transcripts or {})}
        return _compile_items(
            plan, known, profile, reframe_mode=reframe_mode, name=name, edges=edges
        )
    duration = transcript.duration
    intervals = keep_intervals(plan, duration)
    # A kept item's beat names its scene; labels are pinned to scenes by it.
    beats = {(item.start, item.end): item.beat for item in plan.kept if item.beat}
    looks = {(item.start, item.end): _look(item) for item in plan.kept}
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
        low, high = snapped.start, snapped.end
        if edges is not None:
            low, high = edges.refine(transcript, low, high, padding=profile.cut_padding)
            because += _edge_note(snapped.start, snapped.end, low, high)
        # A cut candidate's span is already word-aligned and already includes
        # the right amount of silence, so it is removed exactly, not re-snapped:
        # snapping could pull a short filler's edge back over the filler.
        for piece_start, piece_end, removed in _subtract(low, high, cuts):
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
                    beat=beats.get((start, end), ""),
                    **looks.get((start, end), {}),
                )
            )

    if not ranges:
        # Never emit an empty EDL: it would fail schema validation with a less
        # useful message than this one.
        raise ValueError(
            "the plan removes everything; nothing would be left to render. "
            "Check the drop spans in edit-plan.json."
        )

    _check_tail(edges, {sid: transcript}, ranges)
    mode = reframe_mode or ReframeMode(profile.default_reframe)
    return EDL(
        name=name,
        ranges=ranges,
        output_width=profile.width,
        output_height=profile.height,
        default_reframe=mode,
    )


def _compile_items(
    plan: EditPlan,
    transcripts: dict[str, Transcript],
    profile: OutputProfile,
    *,
    reframe_mode: ReframeMode | None,
    name: str,
    edges: AcousticEdges | None = None,
) -> EDL:
    """One range per kept item, from whichever recordings it names."""
    kept = [(n, item) for n, item in enumerate(plan.items) if item in plan.kept]
    ordered = sorted(kept, key=lambda p: (p[1].order if p[1].order is not None else p[0], p[0]))
    cuts = sorted(
        (item.source, item.start, item.end, item.cut)
        for item in plan.items
        if item.action is PlanAction.DROP and item.cut is not None
    )
    missing = sorted(
        {item.sound_source for _n, item in ordered if item.sound_source not in transcripts}
    )
    if missing:
        raise ValueError(
            "no transcript for "
            + ", ".join(repr(m) for m in missing)
            + "; transcribe every recording the plan keeps words from into this workspace"
        )
    ranges: list[EDLRange] = []
    for number, item in ordered:
        transcript = transcripts[item.sound_source]
        low, high = item.sound_span
        snapped = snap_range(
            transcript, low, high, padding=profile.cut_padding, source_duration=transcript.duration
        )
        because = item.reason or _describe(snapped.start_reason, snapped.end_reason)
        low, high = snapped.start, snapped.end
        if edges is not None:
            limit = None
            if item.audio_source is not None:
                limit = low + (item.end - item.start) / item.speed
            low, high = edges.refine(
                transcript, low, high, padding=profile.cut_padding, limit_end=limit
            )
            because += _edge_note(snapped.start, snapped.end, low, high)
        quote = text_in(transcript, low, high)[:300]
        if item.audio_source is not None:
            voice = high - low
            picture = (item.end - item.start) / item.speed
            if voice > picture + 0.001:
                slower = (item.end - item.start) / voice
                raise ValueError(
                    f"plan item {number}: the voice from {item.audio_source!r} lasts "
                    f"{voice:.2f}s but its picture from {item.source!r} only {picture:.2f}s"
                    + (f" at speed {item.speed:g}" if item.speed != 1.0 else "")
                    + f"; extend end to at least {item.start + voice * item.speed:.2f}"
                    + (f" or set speed to {slower:.3f} or less" if slower >= 0.25 else "")
                )
            ranges.append(
                EDLRange(
                    source=item.source,
                    start=item.start,
                    end=round(item.start + voice * item.speed, 4),
                    audio_source=item.audio_source,
                    audio_start=round(low, 4),
                    audio_end=round(high, 4),
                    reason=because + f"; voice from {item.audio_source}",
                    audio_track=transcript.audio_track,
                    beat=item.beat,
                    reframe=item.reframe,
                    quote=quote,
                    **_look(item),
                )
            )
            continue
        own = [(s, e, c) for src, s, e, c in cuts if src == item.source]
        for piece_start, piece_end, removed in _subtract(low, high, own):
            if piece_end - piece_start < 0.08:
                continue
            ranges.append(
                EDLRange(
                    source=item.source,
                    start=round(piece_start, 4),
                    end=round(piece_end, 4),
                    reason=because + (f"; then {', '.join(removed)} removed" if removed else ""),
                    audio_track=transcript.audio_track,
                    beat=item.beat,
                    reframe=item.reframe,
                    quote=text_in(transcript, piece_start, piece_end)[:300],
                    **_look(item),
                )
            )
    if not ranges:
        raise ValueError(
            "the plan removes everything; nothing would be left to render. "
            "Check the kept items in edit-plan.json."
        )
    _check_tail(edges, transcripts, ranges)
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


def _look(item: PlanItem) -> dict:
    """The framing and pace an item asks of every range it becomes."""
    return {"zoom": item.zoom, "speed": item.speed, "grade": item.grade}


def _edge_note(start: float, end: float, low: float, high: float) -> str:
    moved = []
    if abs(low - start) >= 0.03:
        moved.append(f"in {low - start:+.2f}s")
    if abs(high - end) >= 0.03:
        moved.append(f"out {high - end:+.2f}s")
    return f"; {' and '.join(moved)} to the speech" if moved else ""


def _check_tail(
    edges: AcousticEdges | None, transcripts: dict[str, Transcript], ranges: list[EDLRange]
) -> None:
    """Say so when the voice carries on past the end of the edit."""
    if edges is None or not ranges:
        return
    last = ranges[-1]
    transcript = transcripts.get(last.effective_audio_source)
    if transcript is None:
        return
    heard = edges.check_tail(transcript, last.effective_audio_end)
    if heard > 0:
        edges.warnings.append(
            f"speech carries on for {heard:.2f}s after the edit ends at "
            f"{last.effective_audio_end:.2f}s in {last.effective_audio_source}; "
            "the last word may be cut"
        )


def _describe(start_reason: str, end_reason: str) -> str:
    parts = [p for p in (start_reason, end_reason) if p and "left as requested" not in p]
    return "; ".join(parts) if parts else "kept"


#: The longest frozen last frame `compile` adds on its own, in output seconds;
#: the same as a range's default `max_static_hold`.
FREEZE_LIMIT_S = 0.75


def fit_to_picture(edl: EDL, picture: dict[str, float]) -> tuple[EDL, list[str]]:
    """Keep every range inside its recording's picture; say what changed.

    A phone often stops the picture a little before the sound, and an out-point
    moved to the end of the speech can land past the last frame: the rendered
    range comes out short and every later shot moves. ``picture`` holds each
    source's video length. Up to `FREEZE_LIMIT_S` past it, the last frame is
    held under the rest of the words; further than that, the range ends with
    the picture.
    """
    ranges: list[EDLRange] = []
    notes: list[str] = []
    for rng in edl.ranges:
        length = picture.get(rng.effective_video_source)
        # A voice from another recording is checked against its picture already.
        if (
            length is None
            or rng.effective_audio_source != rng.effective_video_source
            or rng.visual_fill_strategy is not None
            or rng.effective_video_end <= length + 1e-3
            or length <= rng.effective_video_start
        ):
            ranges.append(rng)
            continue
        where = f"range {rng.start:.2f}-{rng.end:.2f}s of {rng.effective_video_source!r}"
        over = rng.effective_video_end - length
        held = rng.model_copy(update={"video_end": length})
        gap = held.unfilled_visual_duration
        if gap <= FREEZE_LIMIT_S:
            ranges.append(
                EDLRange.model_validate(
                    held.model_copy(
                        update={
                            "freeze_at": length,
                            "freeze_duration": round(gap, 3),
                            "visual_fill_strategy": VisualFillStrategy.FREEZE,
                            "visual_fill_reason": "The picture ends before the words do.",
                        }
                    ).model_dump()
                )
            )
            notes.append(
                f"{where} runs {over:.2f}s past the end of its picture ({length:.2f}s); "
                f"the last frame is held {gap:.2f}s under the last words"
            )
            continue
        cut = {"end": length, "video_end": None, "audio_end": None}
        ranges.append(EDLRange.model_validate(rng.model_copy(update=cut).model_dump()))
        notes.append(
            f"{where} runs {over:.2f}s past the end of its picture ({length:.2f}s); "
            "it now ends with the picture, and the words after it are cut"
        )
    if not notes:
        return edl, []
    return EDL.model_validate(edl.model_copy(update={"ranges": ranges}).model_dump()), notes
