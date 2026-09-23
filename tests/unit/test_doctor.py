"""Doctor says what is wrong, how serious it is, and what to do about it."""

from __future__ import annotations

from pathlib import Path

import pytest

from social_video import doctor, remotion_runtime
from social_video.doctor import Check, DoctorReport, run_doctor
from social_video.remotion_runtime import ASSETS


@pytest.mark.parametrize(
    ("check", "status"),
    [
        (Check("ffmpeg", True, True), "OK"),
        (Check("optional: whisperx", False, False), "OPTIONAL"),
        (Check("gpu", False, False), "WARNING"),
        (Check("node", False, True, "not found"), "MISSING"),
        (Check("node", False, True, "v18 is too old"), "ERROR"),
    ],
)
def test_each_check_reports_its_severity(check: Check, status: str) -> None:
    assert check.status == status


def test_only_a_required_failure_makes_the_machine_not_ready() -> None:
    report = DoctorReport()
    report.add(Check("gpu", False, False))
    assert report.ok
    assert report.to_dict()["summary"] == "READY"

    report.add(Check("ffmpeg", False, True, "not found", "Install ffmpeg."))
    assert not report.ok
    assert report.to_dict()["summary"] == "NOT READY"
    assert [c.name for c in report.failures] == ["ffmpeg"]


def test_every_check_is_named_once_and_every_required_failure_has_a_remedy() -> None:
    report = run_doctor()

    names = [check.name for check in report.checks]
    assert len(names) == len(set(names))
    assert all(check.remedy for check in report.failures)


def test_missing_node_is_a_required_failure_with_an_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    report = DoctorReport()

    doctor._check_node(report)

    node = next(check for check in report.checks if check.name == "node")
    assert not node.ok and node.required
    assert "Node.js 20+" in node.remedy


def test_an_installed_package_points_at_the_remotion_installer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundled = tmp_path / "_remotion"
    for asset in ASSETS:
        (bundled / asset).parent.mkdir(parents=True, exist_ok=True)
        (bundled / asset).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(remotion_runtime, "_checkout_root", lambda: None)
    monkeypatch.setattr(remotion_runtime, "_BUNDLED", bundled)
    monkeypatch.setenv("SOCIAL_VIDEO_HOME", str(tmp_path / "home"))
    report = DoctorReport()

    doctor._check_node(report)

    remotion = next(check for check in report.checks if check.name == "remotion")
    assert not remotion.ok
    assert "doctor --install-remotion" in remotion.remedy
