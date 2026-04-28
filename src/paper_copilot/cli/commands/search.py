"""`paper-copilot search "<query>"` subcommand.

Cross-paper hybrid search. Structured filters (``--year``,
``--field``/``--contains``) narrow the candidate set via ``fields.db``,
then the query embedding scores chunks in ``embeddings.db`` restricted
to that set. One hit per paper, ranked by best chunk distance.

Fails loudly if ``embeddings_meta.json`` is missing or records a
different embedding model than the runtime — stale vectors would return
bogus distances otherwise.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel

from paper_copilot.knowledge.embeddings_store import EmbeddingsStore
from paper_copilot.knowledge.fields_store import FieldsStore, available_fields
from paper_copilot.knowledge.hybrid_search import ContainsFilter, SearchResult, search
from paper_copilot.knowledge.meta import require_match
from paper_copilot.session.paths import default_root
from paper_copilot.shared.embedder import EMBEDDING_DIM, MODEL_NAME, Embedder
from paper_copilot.shared.errors import KnowledgeError


def search_cmd(
    query: Annotated[str, typer.Argument(help="Natural-language query")],
    year: Annotated[
        int | None,
        typer.Option("--year", "-y", help="Only consider papers from this year"),
    ] = None,
    field: Annotated[
        str | None,
        typer.Option(
            "--field",
            "-f",
            help=(
                f"Pre-filter to papers whose <field> contains --contains "
                f"(one of: {', '.join(available_fields())}). Must be paired with --contains."
            ),
        ),
    ] = None,
    contains: Annotated[
        str | None,
        typer.Option(
            "--contains",
            "-c",
            help="Case-insensitive substring used with --field to pre-filter before vector search.",
        ),
    ] = None,
    k: Annotated[
        int,
        typer.Option("--k", help="Number of top-k papers to return."),
    ] = 10,
    root: Annotated[
        Path | None, typer.Option("--root", help="Override PAPER_COPILOT_HOME root")
    ] = None,
) -> None:
    """Top-k semantic search (sqlite-vec) over the local paper library; optional substring pre-filter."""
    if (field is None) != (contains is None):
        raise typer.BadParameter("--field and --contains must be used together")
    if field is not None and field not in available_fields():
        raise typer.BadParameter(
            f"unknown field {field!r}; choose from {', '.join(available_fields())}"
        )
    if k <= 0:
        raise typer.BadParameter("--k must be positive")

    home = root if root is not None else default_root()
    fields_db = home / "fields.db"
    embed_db = home / "embeddings.db"
    meta_path = home / "embeddings_meta.json"
    if not fields_db.exists() or not embed_db.exists():
        typer.echo(
            "index missing. Run `paper-copilot reindex --pdf-dir <dir>` first.",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        require_match(meta_path, embedding_model=MODEL_NAME, embedding_dim=EMBEDDING_DIM)
    except KnowledgeError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2) from e

    console = Console()
    with console.status("[dim]loading bge-m3…[/dim]"):
        embedder = Embedder()
        embedder.warmup()

    contains_filter = (
        ContainsFilter(field=field, term=contains)
        if field is not None and contains is not None
        else None
    )

    t0 = time.perf_counter()
    qvec = embedder.encode([query])[0]
    with (
        FieldsStore.open(fields_db) as fs,
        EmbeddingsStore.open(embed_db, dim=EMBEDDING_DIM) as es,
    ):
        results = search(
            qvec,
            fields_store=fs,
            embeddings_store=es,
            k=k,
            year=year,
            contains=contains_filter,
        )
    elapsed_ms = (time.perf_counter() - t0) * 1000

    _render(console, query, results, elapsed_ms=elapsed_ms)


def _render(
    console: Console,
    query: str,
    results: list[SearchResult],
    *,
    elapsed_ms: float,
) -> None:
    if not results:
        console.print("[yellow]no matches[/yellow]")
        return
    console.print(f'[bold]query:[/bold] "{query}"')
    console.print()
    for rank, r in enumerate(results, start=1):
        c = r.best_chunk
        page_range = (
            f"p.{c.page_start}" if c.page_start == c.page_end else f"p.{c.page_start}-{c.page_end}"
        )
        header = (
            f"[bold]{rank}. {r.title}[/bold]  "
            f"[dim]({r.year})  {r.paper_id}  d={c.distance:.3f}[/dim]"
        )
        body = f"[dim]{c.section}  {page_range}[/dim]\n{_truncate(c.text, 400)}"
        console.print(Panel.fit(body, title=header, border_style="dim"))
    console.print(f"[dim]{len(results)} match(es) in {elapsed_ms:.0f}ms[/dim]")


def _truncate(text: str, n: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= n else flat[: n - 1].rstrip() + "…"
