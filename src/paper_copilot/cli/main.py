"""Typer application entry point."""

from __future__ import annotations

import typer

from paper_copilot.cli.commands.doctor import doctor
from paper_copilot.cli.commands.list import list_
from paper_copilot.cli.commands.read import read
from paper_copilot.cli.commands.reindex import reindex
from paper_copilot.cli.commands.search import search_cmd

app = typer.Typer(
    name="paper-copilot",
    help="Local-first paper reading copilot.",
    add_completion=False,
    no_args_is_help=True,
)
app.command()(read)
app.command()(doctor)
app.command()(reindex)
app.command(name="list")(list_)
app.command(name="search")(search_cmd)


if __name__ == "__main__":
    app()
