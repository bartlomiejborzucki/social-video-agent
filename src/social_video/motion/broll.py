"""B-roll from the user's own library, matched to what is being said.

A clip is found by its file name and an optional sidecar of tags
(`klip.mp4.txt`, words separated by spaces or commas). A spoken word matches a
tag exactly (high confidence) or by its first five letters (medium), which
catches Polish inflection -- "samochodu" finds `samochod.mp4` -- without a
dictionary. Nothing is generated and nothing is downloaded: the library is the
user's, and only what they accept becomes an overlay in the EDL.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import Field

from social_video.captions.emphasis import normalise
from social_video.errors import ValidationError
from social_video.schemas.base import Artifact
from social_video.schemas.edl import EDL, Overlay
from social_video.schemas.transcript import Transcript

VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
MIN_GAP = 4.0
MAX_SHOT = 3.5
STEM = 5


class BrollCandidate(Artifact):
    id: str
    file: str
    keyword: str
    at: float = Field(ge=0)
    duration: float = Field(gt=0)
    confidence: str = Field(pattern=r"^(high|medium)$")
    quote: str = ""
    reason: str


class BrollCandidateSet(Artifact):
    library: str
    candidates: list[BrollCandidate] = Field(default_factory=list)

    def by_id(self, candidate_id: str) -> BrollCandidate:
        for candidate in self.candidates:
            if candidate.id == candidate_id:
                return candidate
        known = ", ".join(c.id for c in self.candidates) or "<none>"
        raise KeyError(f"unknown b-roll candidate {candidate_id!r}; known: {known}")


def _tags(clip: Path) -> set[str]:
    words = re.split(r"[\s,_\-.]+", clip.stem)
    sidecar = clip.with_name(clip.name + ".txt")
    if sidecar.is_file():
        words += re.split(r"[\s,]+", sidecar.read_text(encoding="utf-8"))
    return {tag for tag in (normalise(word) for word in words) if len(tag) >= 3}


def find_broll(transcript: Transcript, edl: EDL, directory: Path) -> BrollCandidateSet:
    from social_video.edl.timeline import Timeline
    from social_video.ffmpeg.probe import probe

    if not directory.is_dir():
        raise ValidationError(f"no b-roll library at {directory}")
    clips = {
        clip: _tags(clip)
        for clip in sorted(directory.rglob("*"))
        if clip.suffix.casefold() in VIDEO
    }
    if not clips:
        raise ValidationError(f"no video clips ({', '.join(sorted(VIDEO))}) in {directory}")
    timeline = Timeline(edl)
    words = transcript.words
    found: list[BrollCandidate] = []
    used: set[Path] = set()
    for index, word in enumerate(words):
        key = normalise(word.text)
        if len(key) < 4:
            continue
        match = None
        for clip, tags in clips.items():
            if clip in used:
                continue
            if key in tags:
                match = (clip, key, "high")
                break
            if len(key) >= STEM and any(len(t) >= STEM and t[:STEM] == key[:STEM] for t in tags):
                match = match or (clip, key, "medium")
        if match is None:
            continue
        at = timeline.map_to_output(transcript.source_id, word.start)
        if not at or any(abs(at[0] - c.at) < MIN_GAP for c in found):
            continue
        clip, keyword, confidence = match
        length = min(MAX_SHOT, max(1.0, probe(clip).duration), edl.total_duration - at[0])
        if length < 1.0:
            continue
        found.append(
            BrollCandidate(
                id="", file=str(clip.resolve()), keyword=keyword, at=round(at[0], 3),
                duration=round(length, 3), confidence=confidence,
                quote=" ".join(w.text for w in words[max(0, index - 3) : index + 5]),
                reason=f"'{word.text}' is said here and the library has {clip.name}",
            )
        )  # fmt: skip
        used.add(clip)
    for number, candidate in enumerate(found, start=1):
        candidate.id = f"br-{number:03d}"
    return BrollCandidateSet(library=str(directory.resolve()), candidates=found)


def accept_broll(edl: EDL, found: BrollCandidateSet, ids: list[str]) -> tuple[EDL, list[Overlay]]:
    if not ids:
        raise ValidationError("name at least one b-roll candidate to accept")
    added: list[Overlay] = []
    present = {(o.file, round(o.start_in_output, 2)) for o in edl.overlays}
    for candidate_id in dict.fromkeys(ids):
        try:
            candidate = found.by_id(candidate_id)
        except KeyError as exc:
            raise ValidationError(str(exc.args[0])) from exc
        if (candidate.file, round(candidate.at, 2)) in present:
            continue
        added.append(
            Overlay(
                file=candidate.file, start_in_output=candidate.at, duration=candidate.duration,
                x="(W-w)/2", y="(H-h)/2", scale_width=edl.output_width,
                reason=f"B-roll for '{candidate.keyword}': {candidate.reason}",
            )
        )  # fmt: skip
    updated = edl.model_copy(update={"overlays": [*edl.overlays, *added]})
    return EDL.model_validate(updated.model_dump()), added
