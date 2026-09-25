"""The Typer application and its sub-command groups."""

from __future__ import annotations

import typer

app = typer.Typer(
    name="social-video-agent",
    help="Agent-native social video editor. Source media is never modified.",
    no_args_is_help=True,
    add_completion=False,
)
context_app = typer.Typer(help="Discover and cache target-project brand/editing context.")
workflow_app = typer.Typer(help="Persist and resume the guided multi-stage editing workflow.")
config_app = typer.Typer(help="Initialize and validate executable project branding.")
image_app = typer.Typer(help="Detect an image provider and draw cover/end-card plates.")
shorts_app = typer.Typer(help="Turn one long recording into several standalone shorts.")
cuts_app = typer.Typer(
    help="Find filler, stutter, false-start and pause candidates; accept the ones you agree with."
)
license_app = typer.Typer(
    help="Record, inspect, refresh or revoke this project's Remotion license declaration."
)
app.add_typer(context_app, name="context")
app.add_typer(workflow_app, name="workflow")
app.add_typer(config_app, name="config")
app.add_typer(image_app, name="image")
app.add_typer(shorts_app, name="shorts")
app.add_typer(cuts_app, name="cuts")
motion_app = typer.Typer(
    help="Propose accents (hook card, figures, steps, punch-ins, transitions) and sound under them."
)
app.add_typer(motion_app, name="motion")
broll_app = typer.Typer(help="Match clips from your own library to what is said, and cut them in.")
app.add_typer(broll_app, name="broll")
app.add_typer(license_app, name="remotion-license")
