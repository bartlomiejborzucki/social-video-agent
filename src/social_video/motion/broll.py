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
    #: The clip's rights and consent, as `broll.yaml` records them.
    rights: str = ""


class BrollCandidateSet(Artifact):
    library: str
    candidates: list[BrollCandidate] = Field(default_factory=list)
    #: Clips the brand's rules kept out, and why.
    skipped: list[str] = Field(default_factory=list)

    def by_id(self, candidate_id: str) -> BrollCandidate:
        for candidate in self.candidates:
            if candidate.id == candidate_id:
                return candidate
        known = ", ".join(c.id for c in self.candidates) or "<none>"
        raise KeyError(f"unknown b-roll candidate {candidate_id!r}; known: {known}")


class ClipInfo(Artifact):
    """One clip as described in the library's `broll.yaml`."""

    file: str
    description: str = ""
    keywords: list[str] = Field(default_factory=list)
    #: A child's face that can be recognised. Such a clip is never proposed.
    child_face_visible: bool = False
    #: Whose footage it is and the consent to use it, in the owner's words.
    rights: str = ""


def load_library(directory: Path) -> dict[Path, ClipInfo | None]:
    """Every clip in the library, with its `broll.yaml` entry when there is one."""
    import yaml

    clips = sorted(c for c in directory.rglob("*") if c.suffix.casefold() in VIDEO)
    described: dict[Path, ClipInfo] = {}
    meta = directory / "broll.yaml"
    if meta.is_file():
        data = yaml.safe_load(meta.read_text(encoding="utf-8")) or {}
        for entry in data.get("clips", []):
            info = ClipInfo.model_validate(entry)
            described[(directory / info.file).resolve()] = info
    return {clip: described.get(clip.resolve()) for clip in clips}


def _tags(clip: Path, info: ClipInfo | None = None) -> set[str]:
    words = re.split(r"[\s,_\-.]+", clip.stem)
    sidecar = clip.with_name(clip.name + ".txt")
    if sidecar.is_file():
        words += re.split(r"[\s,]+", sidecar.read_text(encoding="utf-8"))
    if info is not None:
        for keyword in info.keywords:
            words += keyword.split()
    return {tag for tag in (normalise(word) for word in words) if len(tag) >= 3}


def _stem_match(key: str, tags: set[str]) -> bool:
    """Polish inflection without a dictionary.

    The first five letters agree ("samochodu" and "samochod"), or the word is
    a short keyword plus an ending of up to three letters ("parku", "park").
    """
    for tag in tags:
        if len(key) >= STEM and len(tag) >= STEM and tag[:STEM] == key[:STEM]:
            return True
        if len(tag) >= 4 and key.startswith(tag) and len(key) - len(tag) <= 3:
            return True
    return False


#: A clip over someone talking to the camera hides their mouth; this long at most.
MAX_OVER_SPEECH = 2.0
#: Something changes every 3-5 s: b-roll no closer together than this.
RHYTHM_GAP = 3.0


def find_broll(
    transcript: Transcript | list[Transcript],
    edl: EDL,
    directory: Path,
    *,
    synonyms: dict[str, list[str]] | None = None,
    density: float = 0.0,
) -> BrollCandidateSet:
    """Clips whose keywords are said, placed on the word, inside the brand's rules.

    A clip with a recognisable child's face (`child_face_visible: true`) is
    never proposed. Over a speaker talking to the camera a clip stays at most
    2 s, so the mouth is not hidden for long; clips keep 3 s apart, and with
    `broll_density` above zero cover at most that share of the edit.
    """
    from social_video.edl.timeline import Timeline
    from social_video.ffmpeg.probe import probe

    if not directory.is_dir():
        raise ValidationError(f"no b-roll library at {directory}")
    library = load_library(directory)
    if not library:
        raise ValidationError(f"no video clips ({', '.join(sorted(VIDEO))}) in {directory}")
    skipped = [
        f"{clip.name}: a child's face is visible" for clip, info in library.items()
        if info is not None and info.child_face_visible
    ]  # fmt: skip
    clips = {
        clip: _tags(clip, info)
        for clip, info in library.items()
        if info is None or not info.child_face_visible
    }
    # A word said that names a synonym of a keyword counts as the keyword.
    alias = {
        normalise(word): normalise(keyword)
        for keyword, words in (synonyms or {}).items()
        for word in words
    }
    timeline = Timeline(edl)
    budget = density * edl.total_duration if density > 0 else edl.total_duration
    transcripts = transcript if isinstance(transcript, list) else [transcript]
    spoken = sorted(
        ((t.source_id, w) for t in transcripts for w in t.words),
        key=lambda item: (timeline.map_to_output(item[0], item[1].start) or [1e9])[0],
    )
    found: list[BrollCandidate] = []
    used: set[Path] = set()
    for index, (source_id, word) in enumerate(spoken):
        key = normalise(word.text)
        if len(key) < 4:
            continue
        keys = {key, alias.get(key, key)}
        match = None
        for clip, tags in clips.items():
            if clip in used:
                continue
            if keys & tags:
                match = (clip, alias.get(key, key), "high")
                break
            if any(_stem_match(k, tags) for k in keys):
                match = match or (clip, alias.get(key, key), "medium")
        if match is None:
            continue
        at = timeline.map_to_output(source_id, word.start)
        if not at or any(abs(at[0] - c.at) < RHYTHM_GAP for c in found):
            continue
        clip, keyword, confidence = match
        slice_ = next(s for s in timeline.slices if s.output_start <= at[0] <= s.output_end)
        to_camera = slice_.range.effective_audio_source == slice_.range.effective_video_source
        longest = MAX_OVER_SPEECH if to_camera else MAX_SHOT
        length = min(longest, max(1.0, probe(clip).duration), edl.total_duration - at[0])
        if length < 1.0 or sum(c.duration for c in found) + length > budget + 1e-6:
            continue
        info = library.get(clip)
        found.append(
            BrollCandidate(
                id="", file=str(clip.resolve()), keyword=keyword, at=round(at[0], 3),
                duration=round(length, 3), confidence=confidence,
                quote=" ".join(w.text for _s, w in spoken[max(0, index - 3) : index + 5]),
                reason=f"'{word.text}' is said here and the library has {clip.name}"
                + (f" ({info.description})" if info and info.description else "")
                + (" -- kept to 2 s over speech to the camera" if to_camera else ""),
                rights=info.rights if info else "",
            )
        )  # fmt: skip
        used.add(clip)
    for number, candidate in enumerate(found, start=1):
        candidate.id = f"br-{number:03d}"
    return BrollCandidateSet(library=str(directory.resolve()), candidates=found, skipped=skipped)


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
