"""A project b-roll library described in broll.yaml, inside the brand's rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from social_video.motion.broll import find_broll, load_library
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.transcript import TokenType, Transcript, TranscriptToken
from social_video.transcribe.normalize import synthesize_spacing
from tests.conftest import ffmpeg, requires_ffmpeg

pytestmark = requires_ffmpeg


def _clip(path: Path, colour: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg("-f", "lavfi", "-i", f"color=c={colour}:s=180x320:r=30:d=4", "-c:v", "libx264",
           "-pix_fmt", "yuv420p", str(path))  # fmt: skip
    return path


def _library(root: Path) -> Path:
    lib = root / "broll"
    _clip(lib / "hustawka.mp4", "green")
    _clip(lib / "rece.mp4", "blue")
    _clip(lib / "twarz.mp4", "red")
    (lib / "broll.yaml").write_text(
        "clips:\n"
        "  - file: hustawka.mp4\n    description: pusta huśtawka w ruchu\n"
        "    keywords: [park, huśtawka]\n    child_face_visible: false\n"
        "    rights: własne nagranie\n"
        "  - file: rece.mp4\n    description: dłoń rodzica i dziecka\n"
        "    keywords: [pomoc, ręka]\n    child_face_visible: false\n    rights: własne\n"
        "  - file: twarz.mp4\n    description: dziecko płacze, widać twarz\n"
        "    keywords: [płacz, plac]\n    child_face_visible: true\n    rights: zgoda\n",
        encoding="utf-8",
    )
    return lib


def _transcript(words: list[tuple[str, float, float]]) -> Transcript:
    tokens = [TranscriptToken(type=TokenType.WORD, text=t, start=s, end=e) for t, s, e in words]
    return Transcript(source_id="kamera", source_fingerprint="x", duration=30.0,
                      provider="test", tokens=synthesize_spacing(tokens))  # fmt: skip


SAID = [("Wychodzimy", 1.0, 1.6), ("z", 1.6, 1.7), ("parku", 1.7, 2.1), ("teraz.", 2.1, 2.6),
        ("Pomogę", 6.0, 6.5), ("ci,", 6.5, 6.7), ("pomocy", 7.0, 7.5)]  # fmt: skip


def test_metadata_keywords_inflection_and_two_inserts(tmp_path: Path) -> None:
    lib = _library(tmp_path)
    library = load_library(lib)
    assert {p.name for p, info in library.items() if info and info.child_face_visible} == {
        "twarz.mp4"
    }
    edl = EDL(ranges=[EDLRange(source="kamera", start=0, end=12)])
    found = find_broll(_transcript(SAID), edl, lib)
    names = [Path(c.file).name for c in found.candidates]
    assert names == ["hustawka.mp4", "rece.mp4"]
    assert found.candidates[0].keyword in {"parku", "park"}
    assert found.candidates[1].rights == "własne"
    assert all(c.duration == pytest.approx(2.0) for c in found.candidates)
    assert found.skipped == ["twarz.mp4: a child's face is visible"]
    from social_video.motion.broll import accept_broll

    with_inserts, added = accept_broll(edl, found, [c.id for c in found.candidates])
    assert len(added) == 2 and len(with_inserts.overlays) == 2


def test_synonyms_from_config_and_the_rhythm_gap(tmp_path: Path) -> None:
    lib = _library(tmp_path)
    said = [("Huśtamy", 1.0, 1.5), ("się", 1.5, 1.7), ("trzymaj", 2.5, 3.0), ("rączkę", 3.0, 3.4)]
    edl = EDL(ranges=[EDLRange(source="glos", start=0, end=10, audio_source="kamera",
                               audio_start=0, audio_end=10)])  # fmt: skip
    found = find_broll(_transcript(said), edl, lib,
                       synonyms={"huśtawka": ["huśtamy"], "ręka": ["rączkę"]})  # fmt: skip
    # The second match is 2 s after the first: closer than the 3 s rhythm gap.
    assert [Path(c.file).name for c in found.candidates] == ["hustawka.mp4"]
    # Over a picture that is not the speaker, a clip may stay up to 3.5 s.
    assert found.candidates[0].duration == pytest.approx(3.5)


def test_density_caps_the_share_of_the_edit(tmp_path: Path) -> None:
    lib = _library(tmp_path)
    edl = EDL(ranges=[EDLRange(source="kamera", start=0, end=12)])
    found = find_broll(_transcript(SAID), edl, lib, density=0.2)
    assert len(found.candidates) == 1
