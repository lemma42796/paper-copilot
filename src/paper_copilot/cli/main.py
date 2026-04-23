"""Typer application entry point."""

from __future__ import annotations

import typer

from paper_copilot.cli.commands.read import read

app = typer.Typer(
    name="paper-copilot",
    help="Local-first paper reading copilot.",
    add_completion=False,
    no_args_is_help=True,
)
app.command()(read)


if __name__ == "__main__":
    app()
