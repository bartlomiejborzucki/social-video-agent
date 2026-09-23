"""Image provider detection, prompts, registration and plates."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.markup import escape

from social_video.cli._apps import (
    image_app,
)
from social_video.cli._common import _guard, console, err_console


@image_app.command("status")
def image_status(
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Report which image APIs this CLI can reach. It cannot see agent tools."""
    from social_video.imagegen import AGENT_MUST_DETERMINE, detect_image_provider

    status = detect_image_provider()
    if as_json:
        console.print_json(json.dumps(status.to_dict()))
        return
    state = (
        "[green]this CLI can generate[/green]"
        if status.available
        else "[yellow]this CLI cannot generate[/yellow]"
    )
    console.print(f"{state} host={status.host}")
    console.print(f"  {escape(status.reason)}", soft_wrap=True)
    if status.provider is not None:
        console.print(f"  cost: {escape(status.provider.cost_note)}", soft_wrap=True)
    console.print(
        "  [dim]checked: local API integrations only. A native image tool given to the "
        "agent by its host, and an MCP connection to Canva, are not visible from this "
        f"process: {', '.join(AGENT_MUST_DETERMINE)} must be established by the "
        "agent.[/dim]",
        soft_wrap=True,
    )


@image_app.command("prompt")
def image_prompt(
    description: str = typer.Option(..., "--prompt", help="What the background should show."),
) -> None:
    """Print the guarded prompt to pass to an image tool, verbatim.

    The agent's native tool cannot be called from here, so this is how the
    no-text guardrail still reaches it: fetch the prompt, pass it unchanged,
    then hand it back to `image register`.
    """
    from social_video.imagegen import build_prompt

    console.print(_guard(lambda: build_prompt(description)), soft_wrap=True)


@image_app.command("register")
def image_register(
    workspace_dir: Path = typer.Argument(..., help="Edit workspace."),
    file: Path = typer.Option(..., "--file", help="Image the agent's own tool produced."),
    prompt: str = typer.Option(..., "--prompt", help="The exact prompt that produced it."),
    kind: str = typer.Option("cover_plate", "--kind", help="cover_plate or end_card_plate."),
    provider: str = typer.Option(
        "chatgpt_native",
        "--provider",
        help="chatgpt_native (the host's own tool), openai_api or gemini_api.",
    ),
    model: str | None = typer.Option(
        None, "--model", help="Only if the tool reports one. Never invent a name."
    ),
    purpose: str = typer.Option("", "--purpose", help="What the plate is for in this edit."),
    allow_cloud_image: bool = typer.Option(
        False, "--allow-cloud-image", help="One-off consent for this image."
    ),
    user_request: bool = typer.Option(
        False,
        "--user-request",
        help="The user asked for this specific image. Does not cover the next one.",
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Adopt an image the agent's own tool drew, with its provenance.

    A native image tool belongs to the agent, not to this process, so this CLI
    does not pretend to have called it. Register the file instead: it is copied
    into the workspace, hashed, and recorded with the tool that really drew it.
    """
    from social_video.imagegen import register_visual
    from social_video.schemas.visuals import ImageProviderName, VisualKind
    from social_video.workspace.layout import Workspace

    visual_kind = _enum_option(VisualKind, kind, "plate kind")
    provider_name = _enum_option(ImageProviderName, provider, "provider")
    visual = _guard(
        lambda: register_visual(
            Workspace.at(workspace_dir),
            visual_kind,
            file,
            prompt=prompt,
            provider=provider_name,
            model=model,
            purpose=purpose,
            allow_flag=allow_cloud_image,
            user_request=user_request,
        )
    )
    if as_json:
        console.print_json(visual.to_json())
        return
    console.print(f"[green]registered[/green] {visual.path}", soft_wrap=True)
    console.print(
        f"  {visual.provider.value} via {visual.tool.value}"
        f"{f', model {visual.model}' if visual.model else ', model not reported'}"
        f", consent={visual.consent}"
    )
    console.print(f"  sha256={visual.sha256}")


@image_app.command("capabilities")
def image_capabilities(
    workspace_dir: Path = typer.Argument(..., help="Edit workspace."),
    chosen_source: str = typer.Option(
        ...,
        "--chosen-source",
        help="existing_asset, video_frame, canva, chatgpt_native, openai_api, "
        "gemini_api or local_composition.",
    ),
    reason: str = typer.Option(
        ..., "--reason", help="Why this source serves the edit, not that it was available."
    ),
    native_imagegen: str = typer.Option(
        "unknown_to_cli",
        "--native-imagegen",
        help="available or unavailable, as the agent observes its own tool list.",
    ),
    canva: str = typer.Option(
        "unknown_to_cli", "--canva", help="available or unavailable, per the MCP connection."
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Record what this session can do about imagery, and which source was chosen.

    The agent supplies what only it can see -- its native image tool and its
    Canva connection -- and the CLI fills in the API credentials it can check.
    """
    from social_video.imagegen import record_capabilities
    from social_video.schemas.visuals import CapabilityState, ImageSource
    from social_video.workspace.layout import Workspace

    source = _enum_option(ImageSource, chosen_source, "chosen source")
    record = _guard(
        lambda: record_capabilities(
            Workspace.at(workspace_dir),
            chosen_source=source,
            reason=reason,
            native_imagegen=_enum_option(CapabilityState, native_imagegen, "native-imagegen"),
            canva=_enum_option(CapabilityState, canva, "canva"),
        )
    )
    if as_json:
        console.print_json(record.to_json())
        return
    console.print(f"[green]recorded[/green] source={escape(record.chosen_source.value)}")
    for name in ("native_imagegen", "canva", "openai_api", "gemini_api"):
        console.print(f"  {name}: {getattr(record, name).value}")
    console.print(f"  policy: {record.policy}")
    console.print(f"  reason: {escape(record.reason)}", soft_wrap=True)


def _enum_option(enum, value: str, label: str):
    """Turn a CLI string into an enum member, or exit with the valid choices."""
    try:
        return enum(value)
    except ValueError:
        supported = ", ".join(item.value for item in enum)
        err_console.print(f"[red]error:[/red] unknown {label} {value!r}; expected {supported}")
        raise typer.Exit(1) from None


@image_app.command("plate")
def image_plate(
    workspace_dir: Path = typer.Argument(..., help="Edit workspace."),
    prompt: str = typer.Option(..., "--prompt", help="What the background should show."),
    kind: str = typer.Option("cover_plate", "--kind", help="cover_plate or end_card_plate."),
    purpose: str = typer.Option("", "--purpose", help="What the plate is for in this edit."),
    allow_cloud_image: bool = typer.Option(
        False,
        "--allow-cloud-image",
        help="One-off consent to send this prompt to a cloud image model.",
    ),
    user_request: bool = typer.Option(
        False,
        "--user-request",
        help="The user asked for this specific image. Does not cover the next one.",
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Generate one background plate here. The model draws no text: typography is local."""
    from social_video.imagegen import generate_workspace_plate
    from social_video.schemas.visuals import VisualKind
    from social_video.workspace.layout import Workspace

    visual_kind = _enum_option(VisualKind, kind, "plate kind")
    visual = _guard(
        lambda: generate_workspace_plate(
            Workspace.at(workspace_dir),
            visual_kind,
            prompt,
            purpose=purpose,
            allow_flag=allow_cloud_image,
            user_request=user_request,
        )
    )
    if as_json:
        console.print_json(visual.to_json())
        return
    console.print(f"[green]generated[/green] {visual.path}", soft_wrap=True)
    console.print(f"  {visual.provider.value} {visual.model}, consent={visual.consent}")
