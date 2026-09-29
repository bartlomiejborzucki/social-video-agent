"""1.5: render timings on this machine, and the estimate they give."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from social_video import render_log
from social_video.render_log import estimate_render, read_renders, record_render


def _record(**overrides) -> None:
    entry = {
        "renderer": "remotion",
        "quality": "preview",
        "width": 1080,
        "height": 1920,
        "output_seconds": 30.0,
        "elapsed_seconds": 60.0,
    }
    entry.update(overrides)
    record_render(**entry)


def test_a_render_is_logged_without_paths(_private_render_log: Path):
    _record(motion_elements=4, captions=True)
    [entry] = read_renders()
    assert entry["elapsed_seconds"] == 60.0
    assert entry["motion_elements"] == 4
    text = _private_render_log.read_text("utf-8")
    assert "/" not in text.replace(entry["at"], "")


def test_no_history_gives_no_estimate():
    assert (
        estimate_render(
            renderer="remotion", quality="preview", width=1080, height=1920, output_seconds=30
        )
        is None
    )


def test_estimate_scales_with_duration_and_pixels():
    _record(elapsed_seconds=60.0)
    _record(elapsed_seconds=80.0)
    _record(elapsed_seconds=70.0)
    _record(renderer="ffmpeg", elapsed_seconds=5.0)  # not comparable
    same = estimate_render(
        renderer="remotion", quality="preview", width=1080, height=1920, output_seconds=60
    )
    assert same is not None
    assert same.samples == 3
    assert same.seconds == pytest.approx(140.0)
    half = estimate_render(
        renderer="remotion", quality="preview", width=540, height=960, output_seconds=30
    )
    assert half is not None
    assert half.seconds == pytest.approx(70.0 / 4)
    assert "earlier renders" in same.describe()


def test_damaged_lines_are_skipped(_private_render_log: Path):
    _record()
    with _private_render_log.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
        handle.write(json.dumps({"renderer": "remotion", "quality": "preview"}) + "\n")
    assert len(read_renders()) == 1


def test_the_log_can_be_turned_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SOCIAL_VIDEO_RENDER_LOG", "off")
    _record()
    assert render_log.log_path() is None
    assert read_renders() == []


def test_the_log_is_trimmed(monkeypatch: pytest.MonkeyPatch, _private_render_log: Path):
    monkeypatch.setattr(render_log, "KEEP", 3)
    for _ in range(7):
        _record()
    assert len(_private_render_log.read_text("utf-8").splitlines()) == 3


def test_describe_reads_like_a_clock():
    assert render_log.RenderEstimate(seconds=42, samples=1).describe().startswith("about 42 s")
    assert "2 min 05 s" in render_log.RenderEstimate(seconds=125, samples=2).describe()
