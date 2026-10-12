"""Caption translation: the agent translates, the CLI checks and burns.

Nothing here calls a translation service. `export_for_translation` writes the
cues with an empty `translation` beside each; the agent fills them in, in the
user's terms; `apply_translation` refuses a file whose cues were added,
dropped or retimed, or whose lines would not fit the caption geometry, and
builds a caption track in the new language on the same timings. Dubbing is
out of scope: the voice stays the speaker's own.

A translated cue has no measured word timings, so the active-word highlight
runs on estimated ones, spread over the cue by the length of each word. The
track records that, so nobody mistakes them for measurements.
"""

from __future__ import annotations

import re
from pathlib import Path

from social_video.errors import ValidationError
from social_video.schemas.brand import CaptionStyle
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord

LANGUAGE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")


def check_language(code: str) -> str:
    code = code.strip()
    if not LANGUAGE.match(code):
        raise ValidationError(f"{code!r} is not a language code such as en, de or pt-BR")
    return code


def export_for_translation(track: CaptionTrack, language: str, style: CaptionStyle) -> dict:
    """The cues to translate, with the limits each translated line must keep."""
    return {
        "source_language": track.language,
        "target_language": check_language(language),
        "max_chars_per_cue": style.max_chars_per_cue,
        "instructions": (
            "Fill in `translation` for every cue. Keep every cue, its index and its "
            "times; keep each translation within max_chars_per_cue; translate meaning, "
            "not word for word."
        ),
        "cues": [
            {
                "index": cue.index,
                "start": cue.start,
                "end": cue.end,
                "text": cue.text,
                "translation": "",
            }
            for cue in track.cues
        ],
    }


def apply_translation(
    track: CaptionTrack,
    data: dict,
    style: CaptionStyle,
    *,
    language: str,
    max_chars: int | None = None,
) -> CaptionTrack:
    """A caption track in ``language`` on the original timings, or a refusal."""
    language = check_language(language)
    if data.get("target_language") not in (None, language):
        raise ValidationError(
            f"the file is a translation into {data.get('target_language')!r}, not {language!r}"
        )
    cues = data.get("cues")
    if not isinstance(cues, list):
        raise ValidationError("the translation file has no list of cues")
    if not all(isinstance(c, dict) and isinstance(c.get("index"), int) for c in cues):
        raise ValidationError("every cue in the translation file needs its integer index")
    by_index = {cue.index: cue for cue in track.cues}
    seen: list[int] = [c["index"] for c in cues]
    if sorted(seen) != sorted(by_index):
        missing = sorted(set(by_index) - set(seen))
        extra = sorted(set(seen) - set(by_index))
        raise ValidationError(
            "the translation must keep every cue and add none"
            + (f"; missing {missing}" if missing else "")
            + (f"; unknown {extra}" if extra else "")
        )
    limit = max_chars or style.max_chars_per_cue
    problems: list[str] = []
    translated: list[CaptionCue] = []
    for raw in sorted(cues, key=lambda c: c["index"]):
        original = by_index[raw["index"]]
        text = " ".join(str(raw.get("translation") or "").split())
        if (
            abs(float(raw.get("start", -1)) - original.start) > 1e-3
            or abs(float(raw.get("end", -1)) - original.end) > 1e-3
        ):
            problems.append(f"cue {original.index} was retimed")
            continue
        if not text:
            problems.append(f"cue {original.index} has no translation")
            continue
        if limit and len(text) > limit:
            problems.append(f"cue {original.index} is {len(text)} characters; the limit is {limit}")
            continue
        translated.append(
            CaptionCue(
                index=original.index,
                start=original.start,
                end=original.end,
                text=text,
                speaker=original.speaker,
                words=estimated_words(text, original.start, original.end),
            )
        )
    if problems:
        shown = "; ".join(problems[:8]) + ("; ..." if len(problems) > 8 else "")
        raise ValidationError(f"the translation cannot be used: {shown}")
    return CaptionTrack(language=language, cues=translated, corrected=True, word_timing="estimated")


def estimated_words(text: str, start: float, end: float) -> list[CaptionWord]:
    """Word timings spread over a cue in proportion to each word's length."""
    words = text.split()
    if not words:
        return []
    weights = [len(word) + 1 for word in words]
    total = sum(weights)
    span = end - start
    timed = []
    at = start
    for word, weight in zip(words, weights, strict=True):
        until = at + span * weight / total
        timed.append(CaptionWord(text=word, start=round(at, 3), end=round(min(until, end), 3)))
        at = until
    return timed


def translated_paths(captions_dir: Path, edl_name: str, language: str) -> dict[str, Path]:
    """Where a language's caption files live, beside the original track."""
    stem = f"{edl_name}.{language}"
    return {
        "request": captions_dir / f"{edl_name}.translate-{language}.json",
        "json": captions_dir / f"{stem}.json",
        "ass": captions_dir / f"{stem}.ass",
        "srt": captions_dir / f"{stem}.srt",
        "vtt": captions_dir / f"{stem}.vtt",
    }
