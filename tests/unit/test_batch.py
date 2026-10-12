"""1.6 batches: one edit workspace per recording under a parent."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from social_video.cli import app
from social_video.errors import ValidationError
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.config import BrandContract
from social_video.schemas.workflow import Renderer
from social_video.workflow.batch import batch_status, create_batch, recordings
from social_video.workspace.layout import Workspace


def _project(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "project"
    (project / "assets").mkdir(parents=True)
    (project / "assets" / "Lato.ttf").write_bytes(b"fixture-font")
    (project / "social-video.yaml").write_text(
        "schema_version: 1\nfont_file: assets/Lato.ttf\n", encoding="utf-8"
    )
    folder = tmp_path / "recordings"
    folder.mkdir()
    for name in ("Odcinek 2.mp4", "odcinek 1.MOV", "notes.txt", "odcinek-1.mp4"):
        (folder / name).write_bytes(b"fixture")
    return project, folder


def test_only_video_files_directly_in_the_folder_count(tmp_path: Path) -> None:
    _, folder = _project(tmp_path)
    (folder / "nested").mkdir()
    (folder / "nested" / "deep.mp4").write_bytes(b"x")

    assert [p.name for p in recordings(folder)] == [
        "Odcinek 2.mp4",
        "odcinek 1.MOV",
        "odcinek-1.mp4",
    ]
    with pytest.raises(ValidationError, match="no recordings"):
        recordings(tmp_path / "project")


def test_a_batch_gives_every_recording_its_own_workspace(tmp_path: Path) -> None:
    project, folder = _project(tmp_path)
    parent = Workspace.at(tmp_path / "batch")

    batch = create_batch(folder, parent, project_root=project, renderer=Renderer.FFMPEG)

    names = [Path(item.workspace).name for item in batch.items]
    assert names == ["odcinek-2", "odcinek-1", "odcinek-1-2"]
    assert all(Workspace.at(i.workspace).workflow_state.is_file() for i in batch.items)
    status = batch_status(parent)
    assert status["recordings"] == 3 and status["complete"] == 0
    assert status["by_stage"] == {"stage_1_editorial_plan": 3}
    assert status["shared_brand_contract"] is True
    assert status["next"] == batch.items[0].workspace
    with pytest.raises(ValidationError, match="already holds a batch"):
        create_batch(folder, parent, project_root=project, renderer=Renderer.FFMPEG)


def test_status_says_when_the_recordings_no_longer_share_a_brand(tmp_path: Path) -> None:
    project, folder = _project(tmp_path)
    parent = Workspace.at(tmp_path / "batch")
    batch = create_batch(folder, parent, project_root=project, renderer=Renderer.FFMPEG)
    child = Workspace.at(batch.items[1].workspace)
    contract = load_artifact(BrandContract, child.brand_contract)
    save_artifact(
        contract.model_copy(update={"project_config_sha256": "0" * 64}), child.brand_contract
    )

    status = batch_status(parent)

    assert status["shared_brand_contract"] is False
    assert len(status["brand_contracts"]) == 2


def test_workflow_status_on_a_parent_reports_the_batch(tmp_path: Path) -> None:
    project, folder = _project(tmp_path)
    parent = Workspace.at(tmp_path / "batch")
    create_batch(folder, parent, project_root=project, renderer=Renderer.FFMPEG)

    result = CliRunner().invoke(app, ["workflow", "status", str(parent.root)])

    assert result.exit_code == 0, result.output
    assert "0/3 recording(s) complete" in result.output
    assert "odcinek-1-2" in result.output
