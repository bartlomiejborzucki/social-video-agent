"""1.6 caption translation: the agent translates, the CLI checks and burns."""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import pytest
from typer.testing import CliRunner

from social_video.captions.ass import write_ass
from social_video.captions.translate import (
    apply_translation,
    estimated_words,
    export_for_translation,
    translated_paths,
)
from social_video.cli import app
from social_video.errors import ValidationError
from social_video.schemas.base import load_artifact, save_artifact
from social_video.schemas.brand import CaptionStyle
from social_video.schemas.captions import CaptionCue, CaptionTrack
from social_video.schemas.edl import EDL, EDLRange
from social_video.workspace.layout import Workspace

STYLE = CaptionStyle(max_chars_per_cue=32)


def _track() -> CaptionTrack:
    return CaptionTrack(
        language="pl",
        cues=[
            CaptionCue(index=1, start=0.0, end=1.5, text="Trzy błędy zabijają zasięgi"),
            CaptionCue(index=2, start=1.6, end=3.0, text="Po pierwsze napisy", speaker="A"),
        ],
    )


def _filled(**changes) -> dict:
    data = export_for_translation(_track(), "en", STYLE)
    data["cues"][0]["translation"] = "Three mistakes kill your reach"
    data["cues"][1]["translation"] = "First, captions"
    for key, value in changes.items():
        data[key] = value
    return data


def test_the_export_carries_every_cue_and_the_line_limit() -> None:
    data = export_for_translation(_track(), "en", STYLE)

    assert data["source_language"] == "pl" and data["target_language"] == "en"
    assert data["max_chars_per_cue"] == 32
    assert [c["index"] for c in data["cues"]] == [1, 2]
    assert all(c["translation"] == "" for c in data["cues"])


def test_a_complete_translation_keeps_the_timings_and_estimates_words() -> None:
    track = apply_translation(_track(), _filled(), STYLE, language="en")

    assert track.language == "en" and track.word_timing == "estimated"
    assert [(c.start, c.end) for c in track.cues] == [(0.0, 1.5), (1.6, 3.0)]
    assert track.cues[1].speaker == "A"
    words = track.cues[0].words
    assert [w.text for w in words] == ["Three", "mistakes", "kill", "your", "reach"]
    assert words[0].start == 0.0 and words[-1].end == pytest.approx(1.5, abs=1e-3)
    assert all(a.end <= b.start + 1e-3 for a, b in pairwise(words))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["cues"].pop(), r"keep every cue and add none; missing \[2\]"),
        (lambda d: d["cues"].append({**d["cues"][0], "index": 9}), r"unknown \[9\]"),
        (lambda d: d["cues"][0].update(start=0.2), "cue 1 was retimed"),
        (lambda d: d["cues"][1].update(translation="  "), "cue 2 has no translation"),
        (lambda d: d["cues"][0].update(translation="x" * 40), "40 characters; the limit is 32"),
        (lambda d: d["cues"][0].update(index="1"), "integer index"),
        (lambda d: d.update(target_language="de"), "into 'de', not 'en'"),
    ],
)
def test_a_translation_that_changed_the_cues_is_refused(change, message) -> None:
    data = _filled()
    change(data)

    with pytest.raises(ValidationError, match=message):
        apply_translation(_track(), data, STYLE, language="en")


def test_a_language_limit_can_be_set_per_language_and_codes_are_checked() -> None:
    data = _filled()
    data["cues"][0]["translation"] = "Drei Fehler töten deine Reichweite"

    track = apply_translation(_track(), data, STYLE, language="en", max_chars=40)

    assert track.cues[0].text.startswith("Drei")
    with pytest.raises(ValidationError, match="not a language code"):
        apply_translation(_track(), _filled(), STYLE, language="english")


def test_estimated_words_fill_the_cue_in_proportion_to_their_length() -> None:
    words = estimated_words("a bbbbbbb", 0.0, 1.0)

    assert words[0].end == pytest.approx(0.2)
    assert words[1].end == pytest.approx(1.0)
    assert estimated_words("", 0.0, 1.0) == []


def _workspace(tmp_path: Path) -> Workspace:
    ws = Workspace.at(tmp_path / "edit")
    ws.ensure()
    track = _track()
    save_artifact(track, ws.captions / "main.json")
    ass = write_ass(track, STYLE, ws.captions / "main.ass", width=540, height=960)
    save_artifact(
        EDL(output_width=540, output_height=960, captions=str(ass),
            ranges=[EDLRange(source="a", start=0, end=3)]),
        ws.edl,
    )  # fmt: skip
    return ws


def test_the_cli_exports_then_applies_a_translation(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    runner = CliRunner()
    root = str(ws.root)

    exported = runner.invoke(app, ["captions", "translate", "-w", root, "--to", "en"])
    again = runner.invoke(app, ["captions", "translate", "-w", root, "--to", "en"])
    empty = runner.invoke(app, ["captions", "apply", "-w", root, "--to", "en"])
    paths = translated_paths(ws.captions, "main", "en")
    request = json.loads(paths["request"].read_text(encoding="utf-8"))
    request["cues"][0]["translation"] = "Three mistakes kill your reach"
    request["cues"][1]["translation"] = "First, captions"
    paths["request"].write_text(json.dumps(request), encoding="utf-8")
    applied = runner.invoke(app, ["captions", "apply", "-w", root, "--to", "en"])

    assert exported.exit_code == 0, exported.output
    assert again.exit_code == 1 and "--force" in again.output
    assert empty.exit_code == 1 and "has no translation" in empty.output
    assert applied.exit_code == 0, applied.output
    assert load_artifact(CaptionTrack, paths["json"]).language == "en"
    assert "First, captions" in paths["srt"].read_text(encoding="utf-8")
    assert "WEBVTT" in paths["vtt"].read_text(encoding="utf-8")
    assert "Three mistakes" in paths["ass"].read_text(encoding="utf-8")


def test_the_cli_needs_captions_to_translate(tmp_path: Path) -> None:
    ws = Workspace.at(tmp_path / "edit")
    ws.ensure()
    save_artifact(EDL(ranges=[EDLRange(source="a", start=0, end=3)]), ws.edl)

    result = CliRunner().invoke(app, ["captions", "translate", "-w", str(ws.root), "--to", "en"])

    assert result.exit_code == 1 and "no captions to translate" in result.output
