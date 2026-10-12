"""2.0 MCP server: the stages as tools, behind the CLI's own gates."""

from __future__ import annotations

import json
import subprocess

import pytest
import typer.main

from social_video.cli import app
from social_video.mcp_server import (
    BY_NAME,
    TOOLS,
    ToolInputError,
    argv_for,
    call_tool,
)


def _commands() -> dict[tuple[str, ...], object]:
    found: dict[tuple[str, ...], object] = {}

    def walk(cmd, prefix: tuple[str, ...]) -> None:
        if hasattr(cmd, "commands"):
            for name, sub in cmd.commands.items():
                walk(sub, (*prefix, name))
        else:
            found[prefix] = cmd

    walk(typer.main.get_command(app), ())
    return found


def test_every_tool_runs_a_real_command_with_real_options() -> None:
    commands = _commands()

    for tool in TOOLS:
        command = commands.get(tool.command)
        assert command is not None, f"{tool.name}: no command {' '.join(tool.command)}"
        options = {opt for p in command.params for opt in getattr(p, "opts", [])}
        options |= {opt for p in command.params for opt in getattr(p, "secondary_opts", [])}
        arguments = [p for p in command.params if p.param_type_name == "argument"]
        for param in tool.params:
            for flag in (param.flag, param.negative):
                if flag:
                    assert flag in options, f"{tool.name}: {flag} is not an option"
        positional = [p for p in tool.params if p.flag is None and p.negative is None]
        assert len(positional) <= len(arguments), tool.name
        if tool.json_flag:
            assert "--json" in options, f"{tool.name}: the command has no --json"


def test_the_users_own_acts_are_not_tools() -> None:
    commands = {tool.command for tool in TOOLS}
    params = {p.name for tool in TOOLS for p in tool.params}

    for forbidden in (
        ("remotion-license", "attest"),
        ("remotion-license", "refresh"),
        ("remotion-license", "revoke"),
        ("fetch",),
        ("image", "plate"),
        ("image", "register"),
    ):
        assert forbidden not in commands
    assert "allow_brand_upload" not in params
    assert len(BY_NAME) == len(TOOLS)


def test_schemas_are_closed_objects_that_name_their_required_inputs() -> None:
    for tool in TOOLS:
        schema = tool.schema()
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        assert set(schema["required"]) <= set(schema["properties"])
    film = BY_NAME["motion_film_import"].schema()
    assert film["required"] == ["export", "workspace", "film_id", "font_used"]
    assert film["properties"]["scene"] == {
        "type": "array",
        "description": "",
        "items": {"type": "string"},
    }


def test_arguments_become_the_cli_arguments() -> None:
    deliver = argv_for(
        BY_NAME["deliver"],
        {"workspace": "edit", "output": "out", "srt": True, "vtt": False,
         "language": ["en", "de"]},
    )  # fmt: skip
    faces_off = argv_for(BY_NAME["motion_qa"], {"workspace": "edit", "faces": False})
    faces_on = argv_for(BY_NAME["motion_qa"], {"workspace": "edit", "faces": True})
    pack = argv_for(BY_NAME["pack"], {"workspace": "edit"})
    complete = argv_for(BY_NAME["workflow_complete"], {"stage": 2, "workspace": "edit"})

    assert deliver == ["deliver", "edit", "--output", "out", "--srt", "--language", "en",
                       "--language", "de", "--json"]  # fmt: skip
    assert faces_off == ["motion", "qa", "--workspace", "edit", "--no-faces", "--json"]
    assert faces_on == ["motion", "qa", "--workspace", "edit", "--json"]
    assert pack == ["pack", "edit"]
    assert complete == ["workflow", "complete", "2", "--workspace", "edit", "--json"]


@pytest.mark.parametrize(
    ("name", "arguments", "message"),
    [
        ("render", {}, "render needs workspace"),
        ("render", {"workspace": "e", "colour": "red"}, "takes no colour"),
        ("deliver", {"workspace": "e", "srt": "yes"}, "true or false"),
        ("deliver", {"workspace": "e", "language": "en"}, "is a list"),
    ],
)
def test_arguments_that_do_not_fit_are_refused(name, arguments, message) -> None:
    with pytest.raises(ToolInputError, match=message):
        argv_for(BY_NAME[name], arguments)


def _runner(code: int, out: str = "", err: str = ""):
    def run(argv):
        return subprocess.CompletedProcess(argv, code, stdout=out, stderr=err)

    return run


def test_a_call_reports_parsed_results_text_and_errors() -> None:
    parsed = call_tool("platforms", runner=_runner(0, '[{"name": "reels"}]'))
    text = call_tool("pack", {"workspace": "e"}, runner=_runner(0, "written takes-packed.md"))
    failed = call_tool("render", {"workspace": "e"}, runner=_runner(1, "", "error: no EDL"))
    refused = call_tool("render", {}, runner=_runner(0))
    unknown = call_tool("dance")

    assert parsed == {"ok": True, "command": ["platforms", "--json"], "result": [{"name": "reels"}]}
    assert text["output"] == "written takes-packed.md"
    assert failed["ok"] is False and failed["error"] == "error: no EDL"
    assert refused == {"ok": False, "error": "render needs workspace"}
    assert "no tool 'dance'" in unknown["error"]


def test_a_real_call_runs_the_cli_in_a_child_process() -> None:
    result = call_tool("platforms")

    assert result["ok"], result
    assert {spec["name"] for spec in result["result"]} >= {"reels", "shorts", "tiktok"}


def test_the_server_lists_and_calls_tools_over_the_protocol() -> None:
    pytest.importorskip("mcp")
    import anyio
    from mcp.client import Client

    from social_video.mcp_server import build_server

    async def session() -> tuple[list[str], dict, bool]:
        async with Client(build_server()) as client:
            listed = await client.list_tools()
            called = await client.call_tool("platforms", {})
            return (
                [t.name for t in listed.tools],
                json.loads(called.content[0].text),
                called.is_error,
            )

    names, payload, is_error = anyio.run(session)

    assert names == [tool.name for tool in TOOLS]
    assert payload["ok"] and not is_error


def test_the_server_speaks_over_real_stdio() -> None:
    pytest.importorskip("mcp")
    import sys

    import anyio
    from mcp import StdioServerParameters
    from mcp.client import Client

    params = StdioServerParameters(
        command=sys.executable, args=["-m", "social_video", "mcp", "serve"]
    )

    async def session() -> tuple[int, bool]:
        async with Client(params) as client:
            listed = await client.list_tools()
            called = await client.call_tool("workflow_status", {"workspace": "/nonexistent"})
            return len(listed.tools), called.is_error

    count, is_error = anyio.run(session)

    assert count == len(TOOLS)
    assert is_error, "a missing workspace is reported as a tool error, not a crash"
