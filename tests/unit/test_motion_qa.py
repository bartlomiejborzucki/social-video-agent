"""1.5 measured motion QA: readability, captions, faces, budget and rhythm."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from social_video.cli import app
from social_video.project_config import compile_brand_contract
from social_video.qa.motion import (
    caption_band,
    check_motion,
    graphic_band,
    moment_verdicts,
)
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.brand import CaptionPosition, CaptionStyle
from social_video.schemas.captions import CaptionCue, CaptionTrack
from social_video.schemas.config import BrandContract
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import MotionElement, MotionElementType, MotionPlan, PunchIn
from social_video.schemas.motion_film import FilmSegment
from social_video.schemas.qa import QACheck, QAReport, QASeverity
from social_video.workspace.layout import Workspace
from tests.conftest import make_video, requires_ffmpeg


def _contract(tmp_path: Path, extra: str = "") -> BrandContract:
    project = tmp_path / "project"
    (project / "assets").mkdir(parents=True, exist_ok=True)
    (project / "assets" / "Lato.ttf").write_bytes(b"fixture-font")
    config = project / "social-video.yaml"
    config.write_text(
        f"schema_version: 1\nfont_file: assets/Lato.ttf\nmotion_energy: lively\n{extra}",
        encoding="utf-8",
    )
    return compile_brand_contract(config, Workspace.at(project / "edit"), project_root=project)


def _element(kind: str, start: float, end: float, **fields) -> MotionElement:
    return MotionElement(type=kind, start=start, end=end, reason="r", **fields)


def _edl(seconds: float = 20.0, cuts: int = 1) -> EDL:
    step = seconds / cuts
    return EDL(
        ranges=[
            EDLRange(source="a", start=round(i * step + i, 3), end=round((i + 1) * step + i, 3))
            for i in range(cuts)
        ]
    )


def _by_name(report: QAReport) -> dict[str, QACheck]:
    return {c.name: c for c in report.checks}


def _track(*spans: tuple[float, float]) -> CaptionTrack:
    cues = [
        CaptionCue(index=i, start=s, end=e, text="słowa") for i, (s, e) in enumerate(spans, start=1)
    ]
    return CaptionTrack(cues=cues)


def test_a_graphic_too_short_to_read_is_named_with_its_numbers(tmp_path: Path) -> None:
    long_quote = "To jest bardzo długi cytat, którego nikt nie zdąży przeczytać w dwie sekundy."
    plan = MotionPlan(
        rationale="r",
        elements=[
            _element("stat", 2.0, 3.5, text="73%"),
            _element("quote", 6.0, 8.0, text=long_quote),
            _element("progress", 0.0, 20.0),
        ],
    )

    checks = _by_name(check_motion(_edl(), plan, _contract(tmp_path)))

    assert checks["stat at 2.00s readable"].passed
    quote = checks["quote at 6.00s readable"]
    assert not quote.passed and quote.severity is QASeverity.WARNING
    assert quote.measured == 2.0
    assert quote.expected == pytest.approx(0.6 + len(long_quote) / 15, abs=0.01)
    assert not any(name.startswith("progress") for name in checks)


def test_a_graphic_over_spoken_captions_is_flagged(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    plan = MotionPlan(
        rationale="r",
        elements=[
            _element("lower_third", 1.0, 4.0, text="Ola", secondary_text="Redaktorka"),
            _element("chapter", 6.0, 8.0, text="Część druga"),
            _element("lower_third", 12.0, 14.0, text="Jan"),
        ],
    )

    checks = _by_name(check_motion(_edl(), plan, contract, captions=_track((2.0, 3.0), (6.5, 7.5))))

    covered = checks["lower_third at 1.00s clear of captions"]
    assert not covered.passed and covered.measured and covered.measured > 0
    assert checks["chapter at 6.00s clear of captions"].passed
    assert "lower_third at 12.00s clear of captions" not in checks  # nothing said then


def test_bands_follow_the_compositor_and_the_caption_position() -> None:
    margins = {"top": 6.0, "bottom": 22.0}

    assert graphic_band(MotionElementType.CHAPTER, margins) == pytest.approx((0.08, 0.20))
    _low, high = graphic_band(MotionElementType.CTA, margins)
    assert high == pytest.approx(1 - 0.22 - 0.16)
    assert caption_band(CaptionStyle(position=CaptionPosition.TOP, margin_pct=10))[0] == 0.10
    centre = caption_band(CaptionStyle(position=CaptionPosition.CENTER))
    assert centre[0] < 0.5 < centre[1]


def test_faces_under_graphics_are_measured_on_real_frames(tmp_path: Path) -> None:
    plan = MotionPlan(
        rationale="r",
        elements=[_element("stat", 2.0, 4.0, text="73%"), _element("chapter", 8.0, 10.0, text="A")],
    )
    segment = FilmSegment(
        film_id="f", scene_id="hook-card-1", element_type="hook_card", spec_sha256="a" * 64,
        source_path="x", source_sha256="a" * 64, path="y", sha256="a" * 64, width=1080,
        height=1920, fps="30/1", duration=1.8, start_in_output=0.0, offset_in_film=0.0,
        imported_at="t", font_used="Lato",
    )  # fmt: skip
    face = [(0.3, 0.35, 0.7, 0.6)]

    measured = _by_name(
        check_motion(_edl(), plan, None, film_segments=[segment], faces=lambda _t: face)
    )
    unmeasured = _by_name(check_motion(_edl(), plan, None, faces_note="no model"))

    stat = measured["stat at 2.00s clear of faces"]
    assert not stat.passed and stat.measured == pytest.approx(88.0)
    assert measured["chapter at 8.00s clear of faces"].passed
    assert not measured["motion film hook-card-1 at 0.00s hides the speaker"].passed
    assert "no model" in unmeasured["graphics clear of faces"].message


def test_too_many_accents_and_a_long_still_stretch_are_reported(tmp_path: Path) -> None:
    busy = MotionPlan(
        rationale="r",
        elements=[_element("callout", t, t + 1.0, text="?") for t in range(0, 20, 2)],
        punch_ins=[
            PunchIn(start=t + 1.2, end=t + 1.8, scale=1.1, reason="r") for t in range(0, 20, 2)
        ],
    )
    still = MotionPlan(rationale="r", elements=[_element("hook_card", 0.0, 1.8, text="Hook")])

    loud = _by_name(check_motion(_edl(), busy, _contract(tmp_path)))
    quiet = _by_name(check_motion(_edl(), still, _contract(tmp_path)))
    cut = _by_name(check_motion(_edl(20.0, cuts=5), still, _contract(tmp_path)))

    accents = loud["accents per minute"]
    assert not accents.passed and accents.measured == 60.0 and accents.expected == 12.5
    gap = quiet["something changes every few seconds"]
    assert not gap.passed and gap.measured == pytest.approx(18.2) and gap.at == 1.8
    assert cut["something changes every few seconds"].passed


def test_sheet_verdicts_follow_the_findings_near_each_moment() -> None:
    report = QAReport(
        output="o",
        checks=[
            QACheck(name="a", severity=QASeverity.WARNING, passed=False, message="m", at=2.0),
            QACheck(name="b", severity=QASeverity.ERROR, passed=False, message="m", at=6.0),
            QACheck(name="c", severity=QASeverity.INFO, passed=True, message="m", at=9.0),
        ],
    )

    assert moment_verdicts([(2.6, "stat"), (6.4, "x"), (9.3, "y")], report) == [
        "warning",
        "error",
        "ok",
    ]


@requires_ffmpeg
def test_the_cli_writes_motion_qa_and_colours_the_sheet(tmp_path: Path) -> None:
    ws = Workspace.at(tmp_path / "edit")
    ws.ensure()
    save_artifact(_edl(4.0), ws.edl)
    long_quote = "Cytat dużo za długi, żeby przeczytać go w tak krótkim czasie na ekranie."
    save_artifact(
        MotionPlan(rationale="r", elements=[_element("quote", 1.0, 2.0, text=long_quote)]),
        ws.motion_plan,
    )
    video = make_video(tmp_path / "preview.mp4", width=270, height=480, duration=4.0)
    runner = CliRunner()

    measured = runner.invoke(app, ["motion", "qa", "-w", str(ws.root), "--no-faces"])
    sheet = runner.invoke(app, ["motion", "sheet", "-w", str(ws.root), "--video", str(video)])

    assert measured.exit_code == 0, measured.output
    report = load_artifact(QAReport, ws.motion_qa)
    assert not _by_name(report)["quote at 1.00s readable"].passed
    assert "not measured: --no-faces" in measured.output
    assert sheet.exit_code == 0, sheet.output
    from PIL import Image

    with Image.open(ws.qa / "motion-sheet.png") as image:
        assert image.convert("RGB").getpixel((100, 10)) == (190, 120, 0)


def test_a_list_at_the_top_is_measured_at_the_top(tmp_path: Path) -> None:
    """2.3: a list moved over the face is not reported as covering the captions."""
    contract = _contract(tmp_path, "caption_style:\n  bottom_margin_pct: 22\n")
    items = {"items": ["Nazwij uczucie", "Daj wybór", "Wróć do zabawy"]}
    plan = MotionPlan(
        rationale="r",
        elements=[
            _element("list", 2.0, 8.0, **items, position="top"),
            _element("steps", 10.0, 16.0, **items, position="top"),
        ],
    )

    checks = _by_name(check_motion(_edl(), plan, contract, captions=_track((2.0, 16.0))))

    assert checks["list at 2.00s clear of captions"].passed
    assert checks["steps at 10.00s clear of captions"].passed


def test_a_cta_inside_a_scene_is_told_to_move_to_the_top(tmp_path: Path) -> None:
    contract = _contract(tmp_path, "label_style: scene_frame\n")
    plan = MotionPlan(
        rationale="r",
        elements=[
            _element("label", 0.0, 10.0, text="Spróbuj tak"),
            _element("cta", 6.0, 9.0, text="Zapisz na później"),
            _element("cta", 12.0, 15.0, text="Zapisz", position="top"),
        ],
    )

    report = check_motion(_edl(), plan, contract, captions=_track((0.0, 10.0)))
    checks = _by_name(report)

    framed = checks["cta at 6.00s clear of the scene frame"]
    assert not framed.passed and "position: top" in framed.message
    assert "cta at 12.00s clear of the scene frame" not in checks, "no scene on screen then"
    # The frame holds the captions by design; its label is not "over" them.
    assert "label at 0.00s clear of captions" not in checks
