"""A component written for one reel: what it may import, how it is checked, where it draws."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from social_video.cli import app
from social_video.motion.custom import (
    TEMPLATE,
    check_components,
    component_path,
    scan_source,
    without_rejected,
)
from social_video.motion.layout import element_band
from social_video.remotion import _element_payload
from social_video.schemas.base import save_artifact
from social_video.schemas.captions import CaptionCue, CaptionTrack, CaptionWord
from social_video.schemas.motion import MotionElement, MotionPlan

ROOT = Path(__file__).resolve().parents[2]
HAS_TSC = (ROOT / "node_modules" / ".bin" / "tsc").is_file() and (
    ROOT / "node_modules" / "@types" / "react"
).is_dir()


def _custom(**fields) -> MotionElement:
    values = {"start": 2.0, "end": 4.0, "component": "evening-clock",
              "reason": "No element says 'the evening runs out'."}  # fmt: skip
    values.update(fields)
    return MotionElement(type="custom", **values)


def test_the_template_passes_its_own_checks() -> None:
    assert scan_source(TEMPLATE) == []


@pytest.mark.parametrize(
    ("line", "found"),
    [
        ("import _ from 'lodash';", "imports 'lodash'"),
        ("import {Img} from 'remotion';", "takes Img from remotion"),
        ("import {staticFile, spring} from 'remotion';", "takes staticFile"),
        ("import * as R from 'remotion';", "import remotion by name"),
        ("import './styles.css';", "side-effect import"),
        ("export * from 'remotion';", "re-exporting"),
        ("const r = fetch('/x');", "uses fetch()"),
        ("const m = import('react');", "a dynamic import()"),
        ("const m = require('fs');", "require()"),
        ("const u = 'https://example.com/a.png';", "uses a URL"),
        ("const s = localStorage.getItem('a');", "browser storage"),
    ],
)
def test_a_component_may_only_draw(line: str, found: str) -> None:
    problems = scan_source(TEMPLATE + "\n" + line + "\n")
    assert any(found in problem for problem in problems), problems


def test_a_component_is_the_default_export() -> None:
    assert any("default export" in p for p in scan_source("import React from 'react';\n"))


def test_a_custom_element_names_its_component_and_is_not_for_a_sensitive_reel() -> None:
    element = _custom()
    assert element.placement is not None and element.placement.value == "top"
    with pytest.raises(ValidationError, match="names its component"):
        _custom(component=None)
    with pytest.raises(ValidationError, match="pattern"):
        _custom(component="../escape")
    with pytest.raises(ValidationError, match=r"0\.6-8 s"):
        _custom(end=12.0)
    with pytest.raises(ValidationError, match="carries no text"):
        _custom(text="Wieczór")
    with pytest.raises(ValidationError, match="only used by a custom element"):
        MotionElement(type="callout", start=1, end=3, text="?", component="x", reason="r")
    with pytest.raises(ValidationError, match="remove custom"):
        MotionPlan(rationale="r", sensitive_topic=True, elements=[element])


def test_it_draws_in_its_zone_with_its_words_and_nothing_else() -> None:
    element = _custom()
    top, bottom = element_band(element, height=1920, margins={"top": 10})
    assert top == pytest.approx(0.1 + 10 / 1920) and bottom - top == pytest.approx(0.24)
    words = [CaptionWord(text="wieczór", start=1.0, end=1.5),
             CaptionWord(text="ucieka", start=2.5, end=3.0),
             CaptionWord(text="szybko", start=4.2, end=4.6)]  # fmt: skip
    track = CaptionTrack(cues=[CaptionCue(index=1, start=1, end=4.6, text="x", words=words)])
    payload = _element_payload(
        element, MotionPlan(rationale="r"), {}, margins={"top": 10, "left": 8, "right": 8},
        captions=track,
    )  # fmt: skip
    assert payload["custom_words"] == [{"text": "ucieka", "start": 0.5, "end": 1.0}]
    assert payload["zone"]["left"] == pytest.approx(1080 * 0.08)
    assert payload["zone"]["width"] == pytest.approx(1080 * 0.84)


def _write(workspace: Path, name: str, source: str) -> Path:
    path = component_path(workspace, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def test_a_failing_component_is_left_out_and_the_rest_kept(tmp_path: Path) -> None:
    _write(tmp_path, "good", TEMPLATE)
    lodash = TEMPLATE.replace("from 'react';", "from 'react';\nimport _ from 'lodash';")
    _write(tmp_path, "bad", lodash)
    plan = MotionPlan(
        rationale="r",
        elements=[_custom(component="good"), _custom(component="bad", start=5.0, end=6.0),
                  _custom(component="missing", start=7.0, end=8.0)],
    )  # fmt: skip
    checked = check_components(plan, tmp_path, typecheck=False)
    assert set(checked.accepted()) == {"good"}
    assert any("lodash" in p for p in checked.problems["bad"])
    assert checked.problems["missing"][0].startswith("no component at")
    applied, rejected = checked.evidence()
    assert [a["component"] for a in applied] == ["good"] and len(applied[0]["sha256"]) == 64
    assert [r["component"] for r in rejected] == ["bad", "missing"]
    kept = without_rejected(plan, checked)
    assert [e.component for e in kept.elements] == ["good"]


@pytest.mark.skipif(not HAS_TSC, reason="TypeScript and React types not installed")
def test_tsc_checks_a_component_against_the_props_it_is_given(tmp_path: Path) -> None:
    _write(tmp_path, "good", TEMPLATE)
    _write(tmp_path, "typo", TEMPLATE.replace("color: brand.accent", "color: brand.acent"))
    plan = MotionPlan(
        rationale="r",
        elements=[_custom(component="good"), _custom(component="typo", start=5.0, end=6.0)],
    )
    checked = check_components(plan, tmp_path)
    assert set(checked.accepted()) == {"good"}
    assert any("acent" in p and p.startswith("line ") for p in checked.problems["typo"])


def test_the_cli_writes_the_template_and_reports_what_it_refuses(tmp_path: Path) -> None:
    runner = CliRunner()
    ws = tmp_path / "edit"
    result = runner.invoke(app, ["motion", "custom", "init", "evening-clock", "-w", str(ws)])
    assert result.exit_code == 0, result.output
    assert component_path(ws, "evening-clock").read_text(encoding="utf-8") == TEMPLATE
    again = runner.invoke(app, ["motion", "custom", "init", "evening-clock", "-w", str(ws)])
    assert again.exit_code != 0 and "--force" in again.output
    component_path(ws, "evening-clock").write_text(
        TEMPLATE + "\nconst u = 'https://example.com';\n", encoding="utf-8"
    )
    save_artifact(MotionPlan(rationale="r", elements=[_custom()]), ws / "motion-plan.json")
    checked = runner.invoke(
        app, ["motion", "custom", "check", "evening-clock", "-w", str(ws), "--no-render"]
    )
    assert checked.exit_code == 1 and "uses a URL" in checked.output
