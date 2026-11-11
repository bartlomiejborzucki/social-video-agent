"""`audio bed`: set the music under an edit without editing edl.json by hand."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from social_video.cli import app
from social_video.cli.media import _with_bed
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.edl import EDL, AudioBed, EDLRange
from social_video.workspace.layout import Workspace
from tests.conftest import ffmpeg, requires_ffmpeg

pytestmark = requires_ffmpeg


def _music(path: Path, seconds: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg("-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}", "-c:a", "aac", str(path))
    return path


def _workspace(tmp_path: Path, seconds: float = 6.0) -> Workspace:
    ws = Workspace.at(tmp_path / "edit").ensure()
    save_artifact(EDL(ranges=[EDLRange(source="kamera", start=0.0, end=seconds)]), ws.edl)
    return ws


def _run(*args: str):
    return CliRunner().invoke(app, ["audio", "bed", *args])


def _said(result) -> str:
    """What the command printed, on one line: a long path wraps the message."""
    return " ".join(result.output.split())


def test_a_bed_is_written_with_what_was_asked_and_can_be_taken_out(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    track = _music(tmp_path / "muzyka" / "podklad.m4a", 8.0)

    done = _run(str(track), "-w", str(ws.root), "--gain-db", "-16", "--no-duck",
                "--license-note", "Utwór własny.", "--json")  # fmt: skip

    assert done.exit_code == 0, done.output
    payload = json.loads(done.stdout)
    assert payload["covers_s"] >= 7.9 and payload["edit_s"] == 6.0
    bed = load_artifact(EDL, ws.edl).audio_bed
    assert bed is not None and Path(bed.path) == track.resolve()
    assert (bed.gain_db, bed.duck, bed.license_confirmed) == (-16.0, False, True)
    assert bed.license_note == "Utwór własny." and bed.reason

    removed = _run("--remove", "-w", str(ws.root))
    assert removed.exit_code == 0 and "removed" in _said(removed)
    assert load_artifact(EDL, ws.edl).audio_bed is None


def test_a_track_shorter_than_the_edit_is_refused_unless_it_loops(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    short = _music(tmp_path / "krotki.m4a", 3.0)

    refused = _run(str(short), "-w", str(ws.root))
    looped = _run(str(short), "-w", str(ws.root), "--loop")

    assert refused.exit_code == 1 and "covers 3." in _said(refused) and "--loop" in _said(refused)
    assert looped.exit_code == 0
    assert load_artifact(EDL, ws.edl).audio_bed.loop is True


def test_the_command_says_what_is_missing(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    video_only = tmp_path / "niemy.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=7", "-an", str(video_only))

    assert "name the music file" in _said(_run("-w", str(ws.root)))
    assert "no audio stream" in _said(_run(str(video_only), "-w", str(ws.root)))
    assert "compile the edit first" in _said(_run("x.m4a", "-w", str(tmp_path / "pusty")))


def test_a_recompile_keeps_the_bed_the_edit_had(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    bed = AudioBed(path="/muzyka/podklad.m4a", reason="Podkład pod całą rolkę.")
    rebuilt = EDL(ranges=[EDLRange(source="kamera", start=1.0, end=5.0)])

    kept = _with_bed(rebuilt, bed, ws)

    assert kept.audio_bed == bed
    assert load_artifact(EDL, ws.edl).audio_bed == bed, "saved, not only returned"
    own = EDL(ranges=rebuilt.ranges, audio_bed=AudioBed(path="/inny.m4a", reason="Nowy."))
    assert _with_bed(own, bed, ws).audio_bed.path == "/inny.m4a", "a bed of its own wins"
    assert _with_bed(EDL(ranges=rebuilt.ranges), None, ws).audio_bed is None
