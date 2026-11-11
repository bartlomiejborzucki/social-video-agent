"""Measure and correct real pictures, and prove a good recording is left alone.

The unit tests pin the decisions; these run the ffmpeg chain those decisions
produce and measure the frames that come out. A correction selected correctly
and drawn wrongly would pass there and fail here.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from social_video.edl.picture import MAX_GAMMA, MAX_SHARPEN
from social_video.edl.render import DRAFT, render_edl
from social_video.ffmpeg.run import run_ffmpeg_bytes
from social_video.schemas.edl import EDL, EDLRange
from social_video.sources import build_manifest
from tests.conftest import ffmpeg, requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]

W, H = 270, 480


def _recording(
    path: Path, *, look: str = "", size: tuple[int, int] = (W, H), seconds: float = 2.0
) -> Path:
    """A soft grey scene with some detail in it; ``look`` is applied to the picture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    # A still diagonal ramp from shadow to highlight, with seeded grain: the
    # same picture every run, so what is measured is what was built.
    picture = (
        f"color=c=gray:s={width}x{height}:r=30:d={seconds},"
        "geq=lum='44+168*(X+Y)/(W+H)':cb=128:cr=128,noise=alls=5:allf=t:all_seed=7"
    )
    if look:
        picture += f",{look}"
    ffmpeg(
        "-f", "lavfi", "-i", picture,
        "-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-crf", "12",
        "-c:a", "aac", "-shortest", str(path),
    )  # fmt: skip
    return path


def _edl(*sources: str, seconds: float = 1.5) -> EDL:
    return EDL(
        output_width=W,
        output_height=H,
        ranges=[EDLRange(source=name, start=0.2, end=0.2 + seconds) for name in sources],
    )


def _luma(video: Path, at: float) -> np.ndarray:
    raw = run_ffmpeg_bytes(
        ["-v", "error", "-ss", f"{at}", "-i", str(video), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        desc="read a frame",
    )  # fmt: skip
    return np.frombuffer(raw, dtype=np.uint8).reshape(H, W).astype(float)


def _sharpness(frame: np.ndarray) -> float:
    inner = frame[1:-1, 1:-1]
    laplacian = -4 * inner + frame[:-2, 1:-1] + frame[2:, 1:-1] + frame[1:-1, :-2] + frame[1:-1, 2:]
    return float(laplacian.var())


def _both(tmp_path: Path, edl: EDL, manifest):
    plain = render_edl(edl, manifest, tmp_path / "plain.mp4", quality=DRAFT)
    fixed = render_edl(
        edl, manifest, tmp_path / "fixed.mp4", quality=DRAFT, picture_policy="measured"
    )
    return plain, fixed


def test_a_good_recording_is_rendered_untouched(tmp_path: Path) -> None:
    manifest = build_manifest([_recording(tmp_path / "okno.mp4")])
    plain, fixed = _both(tmp_path, _edl("okno"), manifest)

    assert plain.picture_policy == "none" and plain.picture_applied == {
        "changed": False,
        "sources": {},
        "limits": fixed.picture_applied["limits"],
    }
    evidence = fixed.picture_applied["sources"]["okno"]
    assert fixed.picture_policy == "measured" and not fixed.picture_applied["changed"]
    assert evidence["filters"] == "" and evidence["applied"] == []
    assert evidence["measured"]["frames_measured"] >= 1
    difference = np.abs(_luma(tmp_path / "plain.mp4", 0.7) - _luma(tmp_path / "fixed.mp4", 0.7))
    assert difference.mean() < 0.6, "the same picture, to encoder noise"


def test_a_dark_recording_is_measurably_lifted_within_its_ceiling(tmp_path: Path) -> None:
    manifest = build_manifest([_recording(tmp_path / "wieczor.mp4", look="eq=gamma=0.55")])
    _plain, fixed = _both(tmp_path, _edl("wieczor"), manifest)

    (exposure,) = [
        step
        for step in fixed.picture_applied["sources"]["wieczor"]["applied"]
        if step["name"] == "exposure"
    ]
    before = np.median(_luma(tmp_path / "plain.mp4", 0.7))
    after = np.median(_luma(tmp_path / "fixed.mp4", 0.7))
    assert 1.04 < exposure["gamma"] <= MAX_GAMMA
    assert after > before + 8, (before, after)
    assert after < 150, "lifted, not blown out"


def test_two_recordings_end_closer_in_brightness(tmp_path: Path) -> None:
    manifest = build_manifest(
        [
            _recording(tmp_path / "okno.mp4"),
            _recording(tmp_path / "wieczor.mp4", look="eq=gamma=0.6"),
        ]
    )
    _plain, fixed = _both(tmp_path, _edl("okno", "wieczor"), manifest)

    def gap(name: str) -> float:
        video = tmp_path / name
        return abs(np.median(_luma(video, 0.7)) - np.median(_luma(video, 2.2)))

    assert gap("fixed.mp4") < gap("plain.mp4") - 6
    assert not fixed.picture_applied["sources"]["okno"]["applied"], "the lit one is left alone"
    assert fixed.picture_applied["sources"]["wieczor"]["applied"]


def test_a_recording_the_edit_enlarges_is_sharpened(tmp_path: Path) -> None:
    small = _recording(tmp_path / "maly.mp4", size=(90, 160))
    manifest = build_manifest([small])
    _plain, fixed = _both(tmp_path, _edl("maly"), manifest)

    (sharpen,) = [
        step
        for step in fixed.picture_applied["sources"]["maly"]["applied"]
        if step["name"] == "sharpen"
    ]
    assert sharpen["sharpen"] == MAX_SHARPEN
    assert fixed.picture_applied["sources"]["maly"]["measured"]["enlargement"] == 3.0
    assert _sharpness(_luma(tmp_path / "fixed.mp4", 0.7)) > 1.3 * _sharpness(
        _luma(tmp_path / "plain.mp4", 0.7)
    )


def test_a_required_correction_stops_when_the_picture_cannot_be_measured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from social_video.errors import ValidationError

    manifest = build_manifest([_recording(tmp_path / "okno.mp4")])
    monkeypatch.setattr("social_video.edl.render.measure_sources", lambda edl, infos: {})

    with pytest.raises(ValidationError, match="picture_policy is 'required'"):
        render_edl(
            _edl("okno"), manifest, tmp_path / "out.mp4", quality=DRAFT, picture_policy="required"
        )
    measured = render_edl(
        _edl("okno"), manifest, tmp_path / "out.mp4", quality=DRAFT, picture_policy="measured"
    )
    assert measured.picture_applied["sources"] == {}, "left as recorded, and recorded as such"
