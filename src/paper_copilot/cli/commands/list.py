"""`paper-copilot list` subcommand.

Query fields.db. Two filter modes, combinable with --year:

    paper-copilot list
    paper-copilot list --year 2023
    paper-copilot list --field method --contains contrastive
    paper-copilot list --field method --contains attention --year 2023
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from paper_copilot.knowledge.fields_store import (
    FieldsStore,
    PaperRow,
    available_fields,
)
from paper_copilot.session.paths import default_root
from paper_copilot.shared.errors import KnowledgeError


def list_(
    year: Annotated[
        int | None,
        typer.Option("--year", "-y", help="Filter by publication year"),
    ] = None,
    field: Annotated[
        str | None,
        typer.Option(
            "--field",
            "-f",
            help=(
                f"Field to substring-match (one of: {', '.join(available_fields())}). "
                "Must be paired with --contains."
            ),
        ),
    ] = None,
    contains: Annotated[
        str | None,
        typer.Option(
            "--contains",
            "-c",
            help="Case-insensitive substring to match in the chosen --field.",
        ),
    ] = None,
    format_: Annotated[
        str,
        typer.Option("--format", help="Output format: text (default, table) or json."),
    ] = "text",
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Override PAPER_COPILOT_HOME root"),
    ] = None,
) -> None:
    """List indexed papers from fields.db; filter by --year or --field/--contains substring (no LLM)."""
    if format_ not in ("text", "json"):
        raise typer.BadParameter(f"unsupported format: {format_!r}; use 'text' or 'json'")
    if (field is None) != (contains is None):
        raise typer.BadParameter("--field and --contains must be used together")
    if field is not None and field not in available_fields():
        raise typer.BadParameter(
            f"unknown field {field!r}; choose from {', '.join(available_fields())}"
        )

    home = root if root is not None else default_root()
    db_path = home / "fields.db"
    if not db_path.exists():
        typer.echo(f"no index at {db_path}. Run `paper-copilot reindex` first.", err=True)
        raise typer.Exit(code=1)

    with FieldsStore.open(db_path) as store:
        try:
            if field is not None and contains is not None:
                rows = store.query_contains(field, contains, year=year)
            else:
                rows = store.list_all(year=year)
        except KnowledgeError as e:
            raise typer.BadParameter(str(e)) from e

    if format_ == "json":
        _emit_json(rows)
    else:
        _emit_text(rows, year=year, field=field, contains=contains)


def _emit_text(
    rows: list[PaperRow],
    *,
    year: int | None,
    field: str | None,
    contains: str | None,
) -> None:
    console = Console()
    if not rows:
        console.print("[yellow]no matches[/yellow]")
        return

    bits: list[str] = []
    if field and contains:
        bits.append(f"{field} contains {contains!r}")
    if year is not None:
        bits.append(f"year={year}")
    subtitle = "  ".join(bits) if bits else "all indexed papers"

    table = Table(title=f"paper-copilot list — {subtitle}", show_lines=False)
    table.add_column("paper_id", style="bold")
    table.add_column("year", justify="right")
    table.add_column("title")
    table.add_column("authors", overflow="fold")
    table.add_column("venue")

    for r in rows:
        meta = r.data.get("meta", {})
        table.add_row(
            r.paper_id,
            str(meta.get("year", "?")),
            str(meta.get("title", "?")),
            _authors_short(meta.get("authors", [])),
            str(meta.get("venue") or ""),
        )
    console.print(table)
    console.print(f"[dim]{len(rows)} paper(s)[/dim]")


def _emit_json(rows: list[PaperRow]) -> None:
    out: list[dict[str, Any]] = [
        {
            "paper_id": r.paper_id,
            "indexed_at": r.indexed_at,
            "meta": r.data.get("meta", {}),
        }
        for r in rows
    ]
    typer.echo(json.dumps(out, indent=2, ensure_ascii=False))


def _authors_short(authors: list[str]) -> str:
    if not authors:
        return ""
    if len(authors) == 1:
        return authors[0]
    if len(authors) <= 3:
        return ", ".join(authors)
    return f"{authors[0]} et al. ({len(authors)} authors)"
