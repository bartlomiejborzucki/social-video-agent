"""The MCP server: every workflow stage as a tool, behind the CLI's own gates."""

from __future__ import annotations

import typer
from rich.markup import escape

from social_video.cli._apps import mcp_app
from social_video.cli._common import console, err_console


@mcp_app.command("serve")
def mcp_serve() -> None:
    """Serve the tools over stdio. Register it with your agent as a local MCP server."""
    try:
        import mcp  # noqa: F401
    except ImportError:
        err_console.print(
            "[red]error:[/red] the MCP server needs the `mcp` extra: "
            "pip install 'social-video-agent[mcp]'"
        )
        raise typer.Exit(1) from None
    from social_video.mcp_server import serve

    serve()


@mcp_app.command("tools")
def mcp_tools(as_json: bool = typer.Option(False, "--json")) -> None:
    """List the tools the server offers and the commands they run."""
    from social_video.mcp_server import TOOLS

    if as_json:
        console.print_json(
            data=[
                {"name": t.name, "command": list(t.command), "description": t.description,
                 "input_schema": t.schema()}
                for t in TOOLS
            ]
        )  # fmt: skip
        return
    for tool in TOOLS:
        console.print(
            f"  {tool.name:24} {escape(' '.join(tool.command)):28} {escape(tool.description)}"
        )
