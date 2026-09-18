from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from social_video.errors import ValidationError
from social_video.remotion import render_motion_design
from social_video.schemas.motion import MotionElement, MotionElementType, MotionPlan

ROOT = Path(__file__).resolve().parents[2]


def test_motion_element_must_fit_timeline(tmp_path: Path) -> None:
    source = tmp_path / "Mój film.mp4"
    source.write_bytes(b"video")
    plan = MotionPlan(
        rationale="Timeline validation.",
        elements=[
            MotionElement(
                type=MotionElementType.CALLOUT,
                start=0,
                end=3,
                text="Poza osią",
                reason="Regression fixture.",
            )
        ],
    )

    with pytest.raises(ValidationError, match="ends after the video timeline"):
        render_motion_design(
            source,
            tmp_path / "output.mp4",
            plan,
            duration_in_frames=60,
            fps=30,
            width=360,
            height=640,
            staging_root=tmp_path / "cache",
        )


def test_bridge_uses_argument_array_and_never_mutates_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not (ROOT / "node_modules/remotion").is_dir():
        pytest.skip("Remotion dependencies not installed")
    source = tmp_path / "Mój film źródłowy.mp4"
    source.write_bytes(b"immutable")
    before = source.read_bytes()
    captured: list[str] = []

    def fake_run(args, **kwargs):
        assert isinstance(args, list)
        assert "shell" not in kwargs
        captured.extend(args)
        Path(args[-1]).write_bytes(b"rendered")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("social_video.remotion._verify_staged_output", lambda *args, **kwargs: None)
    render_motion_design(
        source,
        tmp_path / "wynik z odstępem.mp4",
        MotionPlan(rationale="Safe bridge test."),
        duration_in_frames=30,
        fps=30,
        width=360,
        height=640,
        staging_root=tmp_path / "cache",
    )

    assert source.read_bytes() == before
    assert captured[0].endswith("node")
    assert (tmp_path / "wynik z odstępem.mp4").read_bytes() == b"rendered"


def test_a_missing_end_card_plate_is_a_plan_error_not_a_toolchain_error(tmp_path: Path) -> None:
    source = tmp_path / "base.mp4"
    source.write_bytes(b"video")
    plan = MotionPlan(
        rationale="End card over a generated plate.",
        elements=[
            MotionElement(
                type=MotionElementType.END_CARD,
                start=0,
                end=1,
                text="Domknięcie",
                reason="Regression fixture.",
                image_asset=str(tmp_path / "nie-ma-mnie.png"),
            )
        ],
    )

    with pytest.raises(ValidationError, match="image_asset does not exist"):
        render_motion_design(
            source,
            tmp_path / "output.mp4",
            plan,
            duration_in_frames=60,
            fps=30,
            width=360,
            height=640,
            staging_root=tmp_path / "cache",
        )


def test_an_end_card_plate_is_staged_under_a_neutral_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not (ROOT / "node_modules/remotion").is_dir():
        pytest.skip("Remotion dependencies not installed")
    from PIL import Image

    source = tmp_path / "base.mp4"
    source.write_bytes(b"video")
    plate = tmp_path / "prywatna nazwa projektu.png"
    Image.new("RGB", (64, 64)).save(plate)
    plan = MotionPlan(
        rationale="End card over a generated plate.",
        elements=[
            MotionElement(
                type=MotionElementType.END_CARD,
                start=0,
                end=1,
                text="Domknięcie",
                reason="Regression fixture.",
                image_asset=str(plate),
            )
        ],
    )
    props: dict = {}

    def fake_run(args, **kwargs):
        props.update(json.loads(Path(args[-2]).read_text(encoding="utf-8")))
        Path(args[-1]).write_bytes(b"rendered")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("social_video.remotion._verify_staged_output", lambda *a, **k: None)
    render_motion_design(
        source,
        tmp_path / "output.mp4",
        plan,
        duration_in_frames=30,
        fps=30,
        width=360,
        height=640,
        staging_root=tmp_path / "cache",
    )
    element = props["elements"][0]
    assert element["image_source"] == "motion-plate-0.png"
    assert "image_asset" not in element
