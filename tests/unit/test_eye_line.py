"""Framing on the eye line, and zooms that push in on the face."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from social_video.edl.picture import shown_region
from social_video.edl.render import _reframe_filter
from social_video.reframe import plan as planner
from social_video.reframe.detect import Face, FrameFaces
from social_video.reframe.plan import EYE_LINE, plan_reframe
from social_video.schemas.edl import EDLRange, ReframeMode, ReframePlan


def _face(cx: float, eye_y: float, height: float = 200.0) -> Face:
    """A face with its eyes at ``eye_y``; the box is centred a little below them."""
    width = height * 0.8
    return Face(
        x=cx - width / 2,
        y=eye_y - height * 0.4,
        width=width,
        height=height,
        confidence=0.95,
        landmarks=((cx - 30, eye_y), (cx + 30, eye_y), (cx, eye_y + 40), (cx - 25, eye_y + 80),
                   (cx + 25, eye_y + 80)),
    )  # fmt: skip


def _source(monkeypatch, size: tuple[int, int], faces: list[Face | None]) -> None:
    video = SimpleNamespace(display_size=size)
    monkeypatch.setattr(planner, "probe", lambda _path: SimpleNamespace(video=video))
    samples = [
        FrameFaces(t=index * 0.5, faces=(face,) if face else ()) for index, face in enumerate(faces)
    ]
    monkeypatch.setattr(planner, "detect_faces", lambda *_a, **_k: samples)


def test_the_eyes_go_on_the_eye_line_where_the_crop_has_room(monkeypatch) -> None:
    """A tall recording cropped to a wider frame: the crop is placed by the eyes."""
    _source(monkeypatch, (1080, 1920), [_face(540, 700)] * 6)

    framed = plan_reframe(Path("kamera.mp4"), start=0, end=3, out_width=1080, out_height=1350)

    crop_h = framed.crop_height
    assert crop_h == 1350 and framed.keyframes
    top = framed.keyframes[0].y
    assert (700 - top) / crop_h == pytest.approx(EYE_LINE, abs=0.01)
    assert framed.focus_y == pytest.approx(EYE_LINE, abs=0.01)
    assert framed.focus_x == pytest.approx(0.5, abs=0.01)
    assert framed.face_height == pytest.approx(200 / 1350, abs=0.005)
    assert "eyes at 30% of the frame height" in framed.reason


def test_the_crop_stays_inside_the_recording_when_the_eyes_are_near_its_top(monkeypatch) -> None:
    _source(monkeypatch, (1080, 1920), [_face(540, 150)] * 4)

    framed = plan_reframe(Path("kamera.mp4"), start=0, end=2, out_width=1080, out_height=1350)

    assert framed.keyframes[0].y == 0
    assert framed.focus_y == pytest.approx(150 / 1350, abs=0.01), "measured where it really is"


def test_a_recording_shown_whole_still_records_where_the_face_is(monkeypatch) -> None:
    _source(monkeypatch, (1080, 1920), [_face(600, 520, height=420), None, _face(600, 530, 420)])

    framed = plan_reframe(Path("kamera.mp4"), start=0, end=1.5, out_width=1080, out_height=1920)

    assert framed.mode is ReframeMode.FIT and framed.crop_width is None
    assert framed.focus_x == pytest.approx(600 / 1080, abs=0.01)
    assert framed.focus_y == pytest.approx(530 / 1920, abs=0.01)
    assert framed.face_height == pytest.approx(420 / 1920, abs=0.005)
    assert "no crop needed; eyes at 28% of the frame height, face 22% of it" in framed.reason


def test_no_face_and_fit_leave_the_plan_as_it_was(monkeypatch) -> None:
    _source(monkeypatch, (1080, 1920), [None, None])

    empty = plan_reframe(Path("kamera.mp4"), start=0, end=1, out_width=1080, out_height=1920)
    asked = plan_reframe(
        Path("kamera.mp4"), start=0, end=1, out_width=1080, out_height=1920,
        mode=ReframeMode.FIT,
    )  # fmt: skip

    assert empty.focus_x is None and empty.reason.endswith("no crop needed")
    assert asked.focus_x is None


def _info(width: int = 1080, height: int = 1920):
    return SimpleNamespace(video=SimpleNamespace(display_size=(width, height)))


def test_a_zoom_pushes_in_on_the_eyes_and_keeps_them_where_they_were() -> None:
    plan = ReframePlan(mode=ReframeMode.FIT, focus_x=0.56, focus_y=0.28, face_height=0.22)
    rng = EDLRange(source="kamera", start=0, end=2, zoom=1.25, reframe=plan)

    graph = _reframe_filter(rng, _info(), (1080, 1920), ReframeMode.FACE)

    keep = 1 - 1 / 1.25
    assert f"crop=iw/1.2500:ih/1.2500:iw*{0.56 * keep:.5f}:ih*{0.28 * keep:.5f}" in graph
    # The eyes are at 28 % of the frame before the zoom and after it.
    top = 0.28 * keep
    assert (0.28 - top) / (1 / 1.25) == pytest.approx(0.28)


def test_without_a_measured_face_a_zoom_stays_centred() -> None:
    plain = EDLRange(source="kamera", start=0, end=2, zoom=1.1)

    graph = _reframe_filter(plain, _info(), (1080, 1920), ReframeMode.FIT)

    keep = 1 - 1 / 1.1
    assert f"iw*{0.5 * keep:.5f}:ih*{0.5 * keep:.5f}" in graph


def test_the_picture_is_measured_where_the_zoom_shows_it() -> None:
    plan = ReframePlan(mode=ReframeMode.FIT, focus_x=0.5, focus_y=0.2, face_height=0.2)
    rng = EDLRange(source="kamera", start=0, end=2, zoom=2.0, reframe=plan)

    width, height, x, y = shown_region(rng, _info(), (1080, 1920), ReframeMode.FACE)

    assert (width, height) == (540, 960)
    assert (x, y) == (270, 192), "pushed toward the eyes, not the middle (480)"


def _framed(focus_y: float, face: float, zoom: float = 1.0) -> EDLRange:
    plan = ReframePlan(mode=ReframeMode.FIT, focus_x=0.5, focus_y=focus_y, face_height=face)
    return EDLRange(source="kamera", start=0, end=2, zoom=zoom, reframe=plan)


def test_qa_says_when_two_ranges_frame_the_speaker_differently() -> None:
    from social_video.pipeline import _framing_checks
    from social_video.schemas.edl import EDL

    alike = _framing_checks(EDL(ranges=[_framed(0.28, 0.22), _framed(0.30, 0.24)]))
    apart = _framing_checks(EDL(ranges=[_framed(0.27, 0.14), _framed(0.41, 0.24)]))
    evened = _framing_checks(EDL(ranges=[_framed(0.28, 0.14, zoom=1.6), _framed(0.29, 0.24)]))

    assert alike[0].passed and "faces 22%-24%" in alike[0].message
    assert not apart[0].passed and apart[0].severity.value == "warning"
    assert "`zoom: 1.71` on the plan item of range 0" in apart[0].message
    assert "so they jump at the cut" in apart[0].message
    assert evened[0].passed, "a zoom enlarges the face and keeps the eyes where they were"
    assert _framing_checks(EDL(ranges=[_framed(0.3, 0.2)])) == []
    assert _framing_checks(EDL(ranges=[EDLRange(source="kamera", start=0, end=2)] * 2)) == []


def _other(focus_y: float, face: float, zoom: float = 1.0) -> EDLRange:
    plan = ReframePlan(mode=ReframeMode.FIT, focus_x=0.5, focus_y=focus_y, face_height=face)
    return EDLRange(source="druga", start=0, end=2, zoom=zoom, reframe=plan)


def test_a_punch_on_one_recording_is_not_a_framing_fault() -> None:
    from social_video.pipeline import _framing_checks
    from social_video.schemas.edl import EDL

    # The alternation that hides a jump cut: 1.0, 1.4, 1.0 on one recording.
    punched = _framing_checks(
        EDL(ranges=[_framed(0.3, 0.2), _framed(0.3, 0.2, zoom=1.4), _framed(0.3, 0.2)])
    )
    # The same enlargement across a cut to another recording is a real jump.
    across = _framing_checks(EDL(ranges=[_other(0.3, 0.2), _framed(0.3, 0.2, zoom=1.4)]))

    assert punched[0].passed
    assert not across[0].passed
    assert "`zoom: 1.40` on the plan item of range 0" in across[0].message
    assert "the picture softens" in across[0].message


def test_only_the_two_sides_of_a_cut_are_compared() -> None:
    from social_video.pipeline import _framing_checks
    from social_video.schemas.edl import EDL

    # The first and the last differ a lot; every cut between them is gentle.
    gradual = _framing_checks(
        EDL(ranges=[_framed(0.24, 0.16), _other(0.30, 0.20), _framed(0.36, 0.25)])
    )
    # A range without a measured face between two that have one: no cut to judge.
    unmeasured = EDLRange(source="kamera", start=0, end=2)
    apart = _framing_checks(EDL(ranges=[_framed(0.2, 0.1), unmeasured, _framed(0.5, 0.3)]))
    jump = _framing_checks(EDL(ranges=[_framed(0.34, 0.21), _other(0.2, 0.17)]))

    assert gradual[0].passed and "eyes at 24%-36%" in gradual[0].message
    assert apart == []
    assert not jump[0].passed
    assert "20% of the frame height in range 1 and at 34% in range 0" in jump[0].message
    assert "zoom" not in jump[0].message, "the faces are close enough in size"
