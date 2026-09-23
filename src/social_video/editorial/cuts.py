"""Cut candidates: stumbles found by timing and repetition, never applied alone.

The code can find what is visible without understanding the content -- dead
air, hesitation sounds, a doubled word, a restarted phrase -- and say how sure
it is. It cannot know whether "bardzo bardzo" is a stutter or emphasis, or
whether a long pause is a stumble or a beat. So every finding is a candidate
with an id; the agent reads them against the transcript and accepts the ones
it agrees with, and only accepted candidates reach the edit plan.

Spans are chosen so that removing one leaves natural speech: a stumble is
removed together with the gap after it, up to the next word, keeping the gap
before it; a pause is tightened to the profile's floor rather than closed.
"""

from __future__ import annotations

from social_video.analysis.silence import find_pauses_from_transcript
from social_video.captions.emphasis import normalise
from social_video.editorial.boundaries import text_in
from social_video.editorial.draft import FILLER_WORDS
from social_video.errors import ValidationError
from social_video.schemas.brand import OutputProfile
from social_video.schemas.plan import (
    CutCandidate,
    CutCandidateSet,
    CutConfidence,
    CutKind,
    EditPlan,
    PlanAction,
    PlanItem,
)
from social_video.schemas.transcript import Transcript, TranscriptToken

#: Real words that are also hesitation sounds. Polish "no" means "well" or
#: "yes"; it is only a candidate when it stands alone between pauses.
_AMBIGUOUS_FILLERS = frozenset({"no"})

#: Words a speaker doubles on purpose ("bardzo bardzo", "that that is").
#: Doubling one is still a candidate, but at medium confidence.
_DELIBERATE_REPEATS = frozenset(
    {"bardzo", "coraz", "tak", "nie", "no", "very", "really", "so", "that", "had", "yes"}
)

#: Longest restarted phrase looked for, in words.
_MAX_RESTART = 5

#: Silence kept in front of the next word when a stumble and its gap are cut.
_LEAD_IN = 0.05

#: A gap at least this long on both sides makes a hesitation "between pauses".
_ISOLATING_GAP = 0.15


def find_cut_candidates(transcript: Transcript, profile: OutputProfile) -> CutCandidateSet:
    """Every stumble visible from timing and repetition, most certain first.

    Overlapping findings are resolved in favour of the more specific one: a
    restarted phrase over a doubled word inside it, and either over a pause.
    """
    words = transcript.words
    found: list[CutCandidate] = []
    found += _false_starts(transcript, words)
    found += _stutters(transcript, words)
    if profile.remove_filler:
        found += _fillers(transcript, words)
    found += _pauses(transcript, profile)

    kept: list[CutCandidate] = []
    for candidate in found:
        if all(candidate.end <= k.start or candidate.start >= k.end for k in kept):
            kept.append(candidate)
    kept.sort(key=lambda c: c.start)
    for number, candidate in enumerate(kept, start=1):
        candidate.id = f"cut-{number:03d}"
    return CutCandidateSet(
        source=transcript.source_id,
        transcript_fingerprint=transcript.source_fingerprint,
        candidates=kept,
    )


def accept_cuts(plan: EditPlan, cuts: CutCandidateSet, ids: list[str]) -> list[PlanItem]:
    """Add the chosen candidates to the plan as drops, once each.

    Returns the items that were added. Accepting a candidate already in the
    plan is not an error and adds nothing.
    """
    if not ids:
        raise ValidationError("name at least one cut candidate to accept")
    chosen: list[CutCandidate] = []
    for candidate_id in dict.fromkeys(ids):
        try:
            chosen.append(cuts.by_id(candidate_id))
        except KeyError as exc:
            raise ValidationError(str(exc.args[0])) from exc
    sources = {item.source for item in plan.items}
    if sources and cuts.source not in sources:
        raise ValidationError(
            f"these cut candidates are for source {cuts.source!r}, but the edit plan covers "
            f"{', '.join(sorted(sources))}; run `cuts find` for the planned source"
        )
    present = {item.cut for item in plan.items if item.cut}
    added: list[PlanItem] = []
    for candidate in chosen:
        if candidate.id in present:
            continue
        item = PlanItem(
            action=PlanAction.DROP,
            source=candidate.source,
            start=candidate.start,
            end=candidate.end,
            quote=candidate.quote,
            reason=f"accepted {candidate.id}: {candidate.reason}",
            cut=candidate.id,
        )
        plan.items.append(item)
        added.append(item)
    return added


def _span_through_gap(words: list[TranscriptToken], first: int, last: int) -> tuple[float, float]:
    """From the first word's start up to just before the word after ``last``."""
    start = words[first].start
    if last + 1 < len(words):
        following = words[last + 1].start
        return start, max(words[last].end, following - _LEAD_IN)
    return start, words[last].end


def _candidate(
    transcript: Transcript,
    kind: CutKind,
    confidence: CutConfidence,
    span: tuple[float, float],
    reason: str,
    quote: str | None = None,
) -> CutCandidate:
    start, end = span
    return CutCandidate(
        id="",
        kind=kind,
        confidence=confidence,
        source=transcript.source_id,
        start=round(start, 4),
        end=round(end, 4),
        quote=text_in(transcript, start, end) if quote is None else quote,
        reason=reason,
    )


def _false_starts(transcript: Transcript, words: list[TranscriptToken]) -> list[CutCandidate]:
    """A phrase said twice in a row: the first, abandoned attempt is the candidate."""
    keys = [normalise(w.text) for w in words]
    found: list[CutCandidate] = []
    index = 0
    while index < len(words):
        for length in range(_MAX_RESTART, 1, -1):
            first = keys[index : index + length]
            second = keys[index + length : index + 2 * length]
            if len(second) == length and first == second and all(first):
                found.append(
                    _candidate(
                        transcript,
                        CutKind.FALSE_START,
                        CutConfidence.HIGH if length >= 3 else CutConfidence.MEDIUM,
                        _span_through_gap(words, index, index + length - 1),
                        f"restarted phrase: {length} words said twice; the second take is kept",
                    )
                )
                index += length
                break
        else:
            index += 1
    return found


def _stutters(transcript: Transcript, words: list[TranscriptToken]) -> list[CutCandidate]:
    found: list[CutCandidate] = []
    for index in range(len(words) - 1):
        key = normalise(words[index].text)
        if not key or key in FILLER_WORDS or key != normalise(words[index + 1].text):
            continue
        deliberate = key in _DELIBERATE_REPEATS
        found.append(
            _candidate(
                transcript,
                CutKind.STUTTER,
                CutConfidence.MEDIUM if deliberate else CutConfidence.HIGH,
                _span_through_gap(words, index, index),
                f"doubled word {words[index].text!r}"
                + ("; often said twice on purpose, listen first" if deliberate else ""),
            )
        )
    return found


def _fillers(transcript: Transcript, words: list[TranscriptToken]) -> list[CutCandidate]:
    found: list[CutCandidate] = []
    for index, word in enumerate(words):
        key = normalise(word.text)
        if key not in FILLER_WORDS:
            continue
        # Spacing tokens exist for any gap over 10 ms, so "between pauses" is
        # measured here: a real pause on both sides, or the edge of speech.
        gap_before = word.start - words[index - 1].end if index > 0 else _ISOLATING_GAP
        gap_after = words[index + 1].start - word.end if index + 1 < len(words) else _ISOLATING_GAP
        isolated = gap_before >= _ISOLATING_GAP and gap_after >= _ISOLATING_GAP
        if not isolated and key in _AMBIGUOUS_FILLERS:
            continue
        found.append(
            _candidate(
                transcript,
                CutKind.FILLER,
                CutConfidence.HIGH if isolated else CutConfidence.MEDIUM,
                _span_through_gap(words, index, index),
                f"hesitation {word.text!r}"
                + (" between pauses" if isolated else " inside a sentence; listen first"),
            )
        )
    return found


def _pauses(transcript: Transcript, profile: OutputProfile) -> list[CutCandidate]:
    found: list[CutCandidate] = []
    duration = transcript.duration
    for pause in find_pauses_from_transcript(transcript, minimum=profile.max_pause):
        if pause.start <= 0.0:
            span = (0.0, max(0.0, pause.end - profile.cut_padding))
            reason = f"{pause.duration:.2f}s of silence before the first word"
        elif pause.end >= duration:
            span = (min(duration, pause.start + profile.cut_padding), duration)
            reason = f"{pause.duration:.2f}s of silence after the last word"
        else:
            span = pause.tightened_to(profile.min_pause)
            reason = f"{pause.duration:.2f}s pause, tightened to {profile.min_pause:.2f}s"
        if span[1] - span[0] < 0.05:
            continue
        found.append(
            _candidate(transcript, CutKind.PAUSE, CutConfidence.HIGH, span, reason, quote="")
        )
    return found
