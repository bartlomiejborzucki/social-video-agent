"""Command line interface.

Every command that produces information supports ``--json``, because the
primary user of this CLI is a coding agent, not a person reading a table.

The commands live in one module per group; importing them here registers them
on ``app``, in the order ``--help`` lists them.
"""

from __future__ import annotations

import logging
import sys

import typer

from social_video import __version__
from social_video.cli._apps import app
from social_video.cli._common import _guard, console


@app.callback()
def main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show progress detail."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Errors only."),
) -> None:
    level = logging.DEBUG if verbose else logging.ERROR if quiet else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(message)s", stream=sys.stderr)


@app.command()
def version() -> None:
    """Print the version."""
    from social_video.compatibility import validate_component_versions

    _guard(validate_component_versions)
    console.print(__version__)


# Registration order is the order ``--help`` lists commands in, so the
# imports stay in workflow order rather than alphabetical.
# isort: off
from social_video.cli import doctor  # noqa: E402
from social_video.cli import media  # noqa: E402
from social_video.cli import render  # noqa: E402
from social_video.cli import delivery  # noqa: E402
from social_video.cli import workflow  # noqa: E402
from social_video.cli import config  # noqa: E402
from social_video.cli import image  # noqa: E402
from social_video.cli import shorts  # noqa: E402
from social_video.cli import cuts  # noqa: E402
from social_video.cli import motion  # noqa: E402
from social_video.cli import broll  # noqa: E402
from social_video.cli import licensing  # noqa: E402

# isort: on

__all__ = [
    "app",
    "broll",
    "config",
    "cuts",
    "delivery",
    "doctor",
    "image",
    "licensing",
    "media",
    "motion",
    "render",
    "shorts",
    "workflow",
]
