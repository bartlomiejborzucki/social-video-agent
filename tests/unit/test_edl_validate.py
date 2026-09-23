"""EDL validation reports every input problem by name, before ffmpeg runs."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from social_video.edl import validate as validate_module
from social_video.edl.validate import validate_edl
from social_video.errors import ValidationError
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.source import SourceEntry, SourceManifest


def _manifest(path: Path, *, duration: float = 10.0) -> SourceManifest:
    return SourceManifest(
        sources=[
            SourceEntry(
                id="a",
                path=str(path),
                fingerprint="f",
                size_bytes=1,
                duration=duration,
                width=1080,
                height=1920,
                frame_rate="30/1",
                audio_tracks=1,
            )
        ]
    )


def test_an_unknown_source_names_the_ones_that_exist(tmp_path: Path) -> None:
    edl = EDL(ranges=[EDLRange(source="b", start=0, end=2)])

    with pytest.raises(ValidationError, match=r"unknown source\. Manifest has: a"):
        validate_edl(edl, _manifest(tmp_path / "a.mp4"), check_media=False)


def test_a_range_past_the_end_uses_the_manifest_duration(tmp_path: Path) -> None:
    edl = EDL(ranges=[EDLRange(source="a", start=11, end=12)])

    with pytest.raises(ValidationError, match=r"the source is only 10\.00s long"):
        validate_edl(edl, _manifest(tmp_path / "a.mp4"), check_media=False)


def test_a_missing_source_file_is_named(tmp_path: Path) -> None:
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=2)])

    with pytest.raises(ValidationError, match="source file is missing"):
        validate_edl(edl, _manifest(tmp_path / "gone.mp4"))


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe not installed")
def test_an_unreadable_source_is_a_named_problem_not_a_crash(tmp_path: Path) -> None:
    source = tmp_path / "a.mp4"
    source.write_bytes(b"not a video")
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=2)])

    with pytest.raises(ValidationError, match="source could not be probed"):
        validate_edl(edl, _manifest(source, duration=0))


def test_each_source_is_probed_once_however_often_it_is_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "a.mp4"
    source.write_bytes(b"video")
    calls: list[Path] = []

    class Info:
        duration = 10.0
        video = object()
        has_audio = True

    def counting_probe(path: Path):
        calls.append(path)
        return Info()

    monkeypatch.setattr(validate_module, "probe", counting_probe)
    edl = EDL(
        ranges=[
            EDLRange(source="a", start=0, end=2),
            EDLRange(source="a", start=4, end=6),
        ]
    )

    validate_edl(edl, _manifest(source))

    assert calls == [source]
