from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from social_video.cli import workflow as cli


@pytest.mark.parametrize(
    ("stage", "openai_model", "claude_model"),
    [
        ("stage_4_finalization", "Sol", "Claude Sonnet 5.5"),
        ("stage_5_delivery", "Luna", "Claude Haiku 5.5"),
    ],
)
def test_workflow_output_lists_both_model_recommendations(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    openai_model: str,
    claude_model: str,
) -> None:
    stream = StringIO()
    monkeypatch.setattr(
        cli,
        "console",
        Console(file=stream, force_terminal=False, color_system=None),
    )
    payload = {
        "language": "pl",
        "current_stage": stage,
        "missing_artifacts": [],
        "handoff_required": True,
        "next_model": openai_model,
        "next_models": {"openai": openai_model, "claude": claude_model},
        "reasoning_effort": "medium",
        "reason": "Następny etap.",
        "next_prompt": "Kontynuuj.",
    }

    cli._print_workflow(payload, as_json=False)

    output = stream.getvalue()
    assert "Zalecane modele" in output
    assert f"OpenAI: {openai_model}" in output
    assert f"Claude: {claude_model}" in output


def test_an_output_that_is_a_source_under_another_name_is_caught(tmp_path) -> None:
    import os

    from social_video.cli._common import overwrites_a_source

    source = tmp_path / "kamera.mp4"
    source.write_bytes(b"recording")
    linked = tmp_path / "wynik.mp4"
    os.link(source, linked)

    assert overwrites_a_source(source, [source])
    assert overwrites_a_source(tmp_path / "." / "kamera.mp4", [source])
    # One file under two names, as on a case-insensitive Windows drive.
    assert overwrites_a_source(linked, [source])
    assert not overwrites_a_source(tmp_path / "nowy.mp4", [source])


def test_a_guarded_command_shows_the_compositors_progress_on_a_terminal(monkeypatch) -> None:
    from social_video import remotion_node
    from social_video.cli import _common
    from social_video.remotion_node import RenderProgress

    stream = StringIO()
    monkeypatch.setattr(
        _common, "err_console", Console(file=stream, force_terminal=True, width=100)
    )

    def renders() -> str:
        sink = remotion_node._sink
        assert sink is not None
        sink(RenderProgress("bundle", 0.5))
        sink(RenderProgress("render", 0.3, rendered=3, total=10))
        return "done"

    assert _common._guard(renders) == "done"
    assert "frame 3 of 10" in stream.getvalue()
    assert remotion_node._sink is None, "the sink is removed when the command ends"


def test_without_a_terminal_a_guarded_command_draws_no_bar(monkeypatch) -> None:
    from social_video import remotion_node
    from social_video.cli import _common

    stream = StringIO()
    monkeypatch.setattr(_common, "err_console", Console(file=stream, force_terminal=False))

    assert _common._guard(lambda: remotion_node._sink) is None
    assert stream.getvalue() == ""
