"""The first second is measured, not just described in the skill."""

from __future__ import annotations

from social_video.qa.checks import _check_opening
from social_video.schemas.captions import CaptionCue, CaptionTrack
from social_video.schemas.qa import QAReport


def _report() -> QAReport:
    return QAReport(output="final.mp4")


def _named(report: QAReport, name: str):
    return next(check for check in report.checks if check.name == name)


def test_an_opening_fade_from_black_is_reported() -> None:
    report = _report()
    _check_opening(report, None, [(0.0, 0.8)])
    check = _named(report, "opens on an image")
    assert not check.passed
    assert "scrolled past" in check.message


def test_a_two_frame_flash_at_the_start_is_not_treated_as_a_dead_opening() -> None:
    report = _report()
    _check_opening(report, None, [(0.0, 0.06)])
    assert _named(report, "opens on an image").passed


def test_black_later_in_the_timeline_does_not_count_as_the_opening() -> None:
    report = _report()
    _check_opening(report, None, [(4.0, 6.0)])
    assert _named(report, "opens on an image").passed


def test_captions_that_start_late_are_flagged_for_muted_autoplay() -> None:
    track = CaptionTrack(cues=[CaptionCue(index=1, start=2.4, end=3.0, text="późno")])
    report = _report()
    _check_opening(report, track, [])
    check = _named(report, "captions start immediately")
    assert not check.passed
    assert check.measured == 2.4


def test_captions_from_the_first_moment_pass() -> None:
    track = CaptionTrack(cues=[CaptionCue(index=1, start=0.2, end=1.0, text="od razu")])
    report = _report()
    _check_opening(report, track, [])
    assert _named(report, "captions start immediately").passed


def test_a_clip_without_captions_gets_no_caption_timing_check() -> None:
    report = _report()
    _check_opening(report, None, [])
    assert not any(check.name == "captions start immediately" for check in report.checks)
