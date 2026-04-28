"""Typer application entry point."""

from __future__ import annotations

import typer

from paper_copilot.cli.commands.compare import compare
from paper_copilot.cli.commands.doctor import doctor
from paper_copilot.cli.commands.eval import app as eval_app
from paper_copilot.cli.commands.list import list_
from paper_copilot.cli.commands.read import read
from paper_copilot.cli.commands.reindex import reindex
from paper_copilot.cli.commands.search import search_cmd

app = typer.Typer(
    name="paper-copilot",
    help=(
        "Local-first paper reading copilot.\n\n"
        "Reads PDFs through a skim → deep → related agent pipeline, writes a "
        "Markdown report, and indexes structured fields + embeddings on disk so "
        "you can later list / search / compare across the whole library. "
        "Eval and doctor commands cover regression and cost observability.\n\n"
        "Data lives in $PAPER_COPILOT_HOME (default ~/.paper-copilot/). "
        "Per-command details: `pc <command> --help`."
    ),
    add_completion=False,
    no_args_is_help=True,
)
app.command()(read)
app.command()(doctor)
app.command()(reindex)
app.command(name="list")(list_)
app.command(name="search")(search_cmd)
app.command()(compare)
app.add_typer(eval_app, name="eval")


if __name__ == "__main__":
    app()
