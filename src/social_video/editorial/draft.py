"""A mechanical first pass at an edit.

This is deliberately *not* the editorial intelligence. It removes what can be
identified without understanding the content -- dead air, and repeated word
runs that are almost certainly a restart -- and marks everything else as kept.
The agent then reads the packed transcript and revises the plan with the
judgements that actually require understanding: which explanation is the better
take, which tangent to drop, where the piece should open.

Keeping the mechanical and the semantic passes separate is what makes the plan
reviewable. It is always clear which decisions a machine made.
"""

from __future__ import annotations

from social_video.editorial.boundaries import text_in
from social_video.schemas.brand import OutputProfile
from social_video.schemas.plan import EditPlan, PlanAction, PlanItem
from social_video.schemas.transcript import TokenType, Transcript

#: Words that are filler when they stand alone between pauses.
FILLER_WORDS = frozenset(
    {
        "um",
        "uh",
        "erm",
        "ah",
        "eh",
        "hmm",
        "mm",
        "yyy",
        "eee",
        "yy",
        "no",  # Polish hesitation sounds
    }
)


def draft_edit_plan(
    transcript: Transcript,
    profile: OutputProfile,
    *,
    goal: str = "",
) -> EditPlan:
    """Build a first-pass plan from timing alone."""
    items: list[PlanItem] = []
    words = transcript.words

    if not words:
        return EditPlan(
            goal=goal or "edit this source",
            profile=profile.name,
            strategy="No speech was found, so there is nothing to plan from timing.",
            open_questions=["This source has no detectable speech. Is that expected?"],
        )

    for token in transcript.tokens:
        if token.type is not TokenType.SPACING:
            continue
        if token.duration < profile.max_pause:
            continue
        # Tighten rather than close: a pause shortened to the floor still reads
        # as a breath, which is what keeps the rhythm human.
        keep = profile.min_pause
        margin = keep / 2.0
        start, end = token.start + margin, token.end - margin
        if end - start < 0.05:
            continue
        items.append(
            PlanItem(
                action=PlanAction.DROP,
                source=transcript.source_id,
                start=start,
                end=end,
                reason=(f"dead air of {token.duration:.2f}s, tightened to {keep:.2f}s"),
            )
        )

    if profile.remove_filler:
        items.extend(_isolated_filler(transcript))

    items.extend(_repeated_runs(transcript))

    lead_in = words[0].start
    if lead_in > profile.max_pause:
        items.insert(
            0,
            PlanItem(
                action=PlanAction.DROP,
                source=transcript.source_id,
                start=0.0,
                end=max(0.0, lead_in - profile.cut_padding),
                reason=f"{lead_in:.2f}s of silence before the first word",
            ),
        )
    tail = transcript.duration - words[-1].end
    if tail > profile.max_pause:
        items.append(
            PlanItem(
                action=PlanAction.DROP,
                source=transcript.source_id,
                start=words[-1].end + profile.cut_padding,
                end=transcript.duration,
                reason=f"{tail:.2f}s of silence after the last word",
            )
        )

    dropped = sum(i.end - i.start for i in items if i.action is PlanAction.DROP)
    return EditPlan(
        goal=goal or "remove dead air and obvious restarts",
        profile=profile.name,
        target_duration=None,
        strategy=(
            f"Mechanical first pass over {transcript.duration:.1f}s of source. "
            f"Marked {len(items)} span(s) for removal totalling {dropped:.1f}s: dead air "
            f"longer than {profile.max_pause:.2f}s tightened to {profile.min_pause:.2f}s, "
            f"plus isolated filler and repeated word runs. No judgement about meaning has "
            f"been applied yet -- decide what the piece is about, which take is best, and "
            f"what to open and close on."
        ),
        items=items,
        open_questions=[
            "What is this clip for, and how long should it be?",
            "Which moment is the strongest opening?",
            "Is there material here that should be dropped for being off-topic?",
        ],
    )


def _isolated_filler(transcript: Transcript) -> list[PlanItem]:
    """Filler words that stand alone between pauses.

    Only isolated occurrences are removed. A 'um' in the middle of a fluent
    sentence is part of how the person speaks; one sitting alone between two
    pauses is a stumble.
    """
    items: list[PlanItem] = []
    tokens = transcript.tokens
    for index, token in enumerate(tokens):
        if token.type is not TokenType.WORD:
            continue
        word = token.text.strip().strip(".,!?;:").lower()
        if word not in FILLER_WORDS:
            continue
        before = tokens[index - 1] if index > 0 else None
        after = tokens[index + 1] if index + 1 < len(tokens) else None
        isolated = (
            before is not None
            and before.type is TokenType.SPACING
            and after is not None
            and after.type is TokenType.SPACING
        )
        if isolated:
            items.append(
                PlanItem(
                    action=PlanAction.DROP,
                    source=transcript.source_id,
                    start=token.start,
                    end=token.end,
                    quote=token.text,
                    reason=f"isolated filler {token.text!r} between pauses",
                )
            )
    return items


def _repeated_runs(transcript: Transcript, *, run: int = 3) -> list[PlanItem]:
    """Find a phrase immediately repeated, and drop the first attempt.

    A speaker restarting a sentence says the same few words twice in a row.
    Keeping the second attempt is nearly always right: it is the one they
    finished.
    """
    words = transcript.words
    items: list[PlanItem] = []
    index = 0
    while index + run * 2 <= len(words):
        first = [w.text.strip().lower().strip(".,!?;:") for w in words[index : index + run]]
        second = [
            w.text.strip().lower().strip(".,!?;:") for w in words[index + run : index + run * 2]
        ]
        if first == second and all(first):
            start = words[index].start
            end = words[index + run - 1].end
            items.append(
                PlanItem(
                    action=PlanAction.DROP,
                    source=transcript.source_id,
                    start=start,
                    end=end,
                    quote=text_in(transcript, start, end),
                    reason="false start: this phrase is immediately repeated",
                )
            )
            index += run * 2
        else:
            index += 1
    return items
