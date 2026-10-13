"""2.2 reel check: short-form practices that measure, as advisory findings."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from social_video.cli import app
from social_video.profiles import load_platform
from social_video.qa.reel import check_reel
from social_video.schemas.base import save_artifact
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord
from social_video.schemas.edl import EDL, EDLRange
from social_video.schemas.motion import MotionElement, MotionPlan
from social_video.schemas.publish import PublishMetadata
from social_video.sources import build_manifest
from social_video.workspace.layout import Workspace
from tests.conftest import ffmpeg, requires_ffmpeg

pytestmark = requires_ffmpeg


def _video(path: Path, seconds: float, *, gap: tuple[float, float] | None = None) -> Path:
    """A moving picture over a tone, with an optional stretch of silence."""
    audio = f"sine=frequency=440:duration={seconds}"
    if gap:
        audio += f",volume=enable='between(t,{gap[0]},{gap[1]})':volume=0"
    ffmpeg("-f", "lavfi", "-i", f"testsrc=size=180x320:rate=30:duration={seconds}",
           "-f", "lavfi", "-i", audio, "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-shortest", str(path))  # fmt: skip
    return path


def _captions(start: float, end: float, step: float = 0.5) -> CaptionTrack:
    cues, index, at = [], 1, start
    while at < end - 1e-6:
        until = min(end, at + 2 * step)
        words = [
            CaptionWord(text="słowo", start=round(at, 3), end=round(at + step - 0.05, 3)),
            CaptionWord(text="dalej", start=round(at + step, 3), end=round(until, 3)),
        ]
        cues.append(CaptionCue(index=index, start=at, end=until, text="słowo dalej", words=words))
        index, at = index + 1, until
    return CaptionTrack(cues=cues)


def _by_name(result) -> dict:
    return {c.name: c for c in result.report.checks}


def test_a_reel_that_follows_the_practices_passes(tmp_path: Path) -> None:
    video = _video(tmp_path / "dobra.mp4", 20.0)
    edl = EDL(ranges=[EDLRange(source="a", start=4 * i, end=4 * i + 4) for i in range(5)])
    publish = PublishMetadata(platform="reels", language="pl", title="Granice",
                              cta="Wyślij to komuś, kto dziś usłyszy „pobaw się”.")  # fmt: skip

    result = check_reel(video, edl, captions=_captions(0.2, 19.6),
                        platforms=[load_platform("reels")], publish=publish,
                        analysis_dir=tmp_path / "a")  # fmt: skip

    assert result.passed == result.total, result.warnings
    assert (
        (tmp_path / "a" / "reel-check.md")
        .read_text(encoding="utf-8")
        .startswith(f"# Reel check: {result.total}/{result.total}")
    )


def test_a_reel_that_loses_viewers_is_told_why(tmp_path: Path) -> None:
    video = _video(tmp_path / "slaba.mp4", 70.0, gap=(10.0, 11.5))
    edl = EDL(ranges=[EDLRange(source="a", start=0, end=70.0)])
    plan = MotionPlan(
        rationale="r",
        elements=[
            MotionElement(type="end_card", start=64.0, end=70.0, text="Obserwuj", reason="r")
        ],
    )
    publish = PublishMetadata(platform="reels", language="pl", title="Granice",
                              description="Dzisiaj o granicach.")  # fmt: skip
    half = _captions(2.5, 30.0)
    last = CaptionWord(text="koniec", start=60.0, end=62.0)
    half.cues.append(CaptionCue(index=99, start=60.0, end=62.0, text="koniec", words=[last]))

    checks = _by_name(check_reel(video, edl, captions=half, plan=plan,
                                 platforms=[load_platform("reels"), load_platform("shorts")],
                                 publish=publish))  # fmt: skip

    failed = {name for name, check in checks.items() if not check.passed}
    assert failed == {
        "situation heard at once", "length suits reels", "length suits shorts",
        "no dead air inside the speech", "ends on the payoff",
        "the picture changes every few seconds", "no lingering end card",
        "captioned for sound off", "asks for a save or a send",
    }  # fmt: skip
    assert checks["situation heard at once"].measured == 2.5
    assert checks["no dead air inside the speech"].measured == pytest.approx(1.5, abs=0.1)
    assert checks["ends on the payoff"].measured == pytest.approx(8.0, abs=0.1)


def test_the_cli_writes_the_check_and_never_blocks(tmp_path: Path) -> None:
    ws = Workspace.at(tmp_path / "edit")
    ws.ensure()
    source = _video(tmp_path / "zrodlo.mp4", 8.0)
    save_artifact(build_manifest([source]), ws.source_manifest)
    save_artifact(EDL(ranges=[EDLRange(source="zrodlo", start=0, end=8.0)]), ws.edl)
    ws.previews.mkdir(parents=True, exist_ok=True)
    preview = _video(ws.previews / "preview.mp4", 8.0)

    result = CliRunner().invoke(app, ["reel-check", str(ws.root), "--platform", "tiktok"])

    assert result.exit_code == 0, result.output
    assert "advisory" in result.output
    assert (ws.analysis / "reel-check.json").is_file()
    assert preview.is_file()
