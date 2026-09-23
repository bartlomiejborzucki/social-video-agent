from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from social_video.cli import workflow as cli


@pytest.mark.parametrize(
    ("stage", "openai_model", "claude_model"),
    [
        ("stage_4_finalization", "Sol", "Claude Sonnet 5"),
        ("stage_5_delivery", "Luna", "Claude Haiku 4.5"),
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
