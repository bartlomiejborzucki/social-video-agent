"""Adding a recording to a workspace that already has an edit in it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from social_video.cli import app
from social_video.errors import SocialVideoError
from social_video.pipeline import stage_ingest
from social_video.schemas.base import load_artifact
from social_video.schemas.source import SourceManifest
from social_video.sources import add_source
from social_video.transcribe.service import source_id_for
from social_video.workspace.layout import Workspace
from tests.conftest import make_video, requires_ffmpeg

pytestmark = requires_ffmpeg


def test_add_source_names_refreshes_and_refuses_a_taken_id(tmp_path: Path) -> None:
    first = make_video(tmp_path / "ujecie.mp4", duration=1.0)
    other = make_video(tmp_path / "plac.mp4", duration=1.0)
    manifest, entry, status = add_source(SourceManifest(), first, source_id="kamera")
    assert (entry.id, status) == ("kamera", "added")
    manifest, _entry, status = add_source(manifest, first)
    assert status == "unchanged"
    make_video(first, duration=1.5)
    manifest, _entry, status = add_source(manifest, first)
    assert status == "updated"
    with pytest.raises(SocialVideoError, match="already names"):
        add_source(manifest, other, source_id="kamera")
    with pytest.raises(SocialVideoError, match="already in the manifest as 'kamera'"):
        add_source(manifest, first, source_id="inne")


def test_sources_add_leaves_transcripts_and_state_alone(tmp_path: Path) -> None:
    main = make_video(tmp_path / "main.mp4", duration=1.0)
    extra = make_video(tmp_path / "park.mp4", duration=1.0)
    ws = Workspace.at(tmp_path / "edit")
    stage_ingest(main, ws)
    transcript = ws.transcript_for("main")
    transcript.write_text('{"keep": true}', encoding="utf-8")
    state = ws.state.read_text(encoding="utf-8")

    result = CliRunner().invoke(
        app, ["sources", "add", str(extra), "-w", str(ws.root), "--id", "plener", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["sources"][0]["status"] == "added"
    manifest = load_artifact(SourceManifest, ws.source_manifest)
    assert manifest.ids == ["main", "plener"]
    assert transcript.read_text(encoding="utf-8") == '{"keep": true}'
    assert ws.state.read_text(encoding="utf-8") == state
    # A recording added under an id is transcribed under that id.
    assert source_id_for(extra, ws) == "plener"
    # Re-running ingest for the main file keeps the added one.
    stage_ingest(main, ws)
    assert load_artifact(SourceManifest, ws.source_manifest).ids == ["plener", "main"]
