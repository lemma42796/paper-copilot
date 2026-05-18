"""`paper-copilot research "<topic>"` subcommand."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markdown import Markdown

from paper_copilot.agents.llm_client import LLMClient
from paper_copilot.agents.research import ResearchToolContext, run_research
from paper_copilot.knowledge.embeddings_store import EmbeddingsStore
from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.knowledge.meta import require_match
from paper_copilot.session.paths import default_root
from paper_copilot.shared.embedder import EMBEDDING_DIM, MODEL_NAME, Embedder
from paper_copilot.shared.errors import KnowledgeError


def research(
    topic: Annotated[str, typer.Argument(help="Research question or topic")],
    pdf_dir: Annotated[
        Path | None,
        typer.Option("--pdf-dir", help="Optional directory of candidate PDFs to list."),
    ] = None,
    max_turns: Annotated[
        int,
        typer.Option("--max-turns", help="Maximum planner/tool loop turns."),
    ] = 12,
    budget_cny: Annotated[
        float,
        typer.Option("--budget-cny", help="Maximum LLM spend for the planner loop."),
    ] = 2.0,
    max_papers: Annotated[
        int,
        typer.Option("--max-papers", help="Maximum unique papers inspect/compare may touch."),
    ] = 5,
    root: Annotated[
        Path | None,
        typer.Option("--root", help="Override PAPER_COPILOT_HOME root"),
    ] = None,
) -> None:
    """Run a bounded research tool loop over the local library."""
    if max_turns <= 0:
        raise typer.BadParameter("--max-turns must be positive")
    if budget_cny <= 0:
        raise typer.BadParameter("--budget-cny must be positive")
    if max_papers <= 0:
        raise typer.BadParameter("--max-papers must be positive")
    if pdf_dir is not None and not pdf_dir.is_dir():
        raise typer.BadParameter(f"--pdf-dir is not a directory: {pdf_dir}")
    asyncio.run(_research_async(topic, pdf_dir, max_turns, budget_cny, max_papers, root))


async def _research_async(
    topic: str,
    pdf_dir: Path | None,
    max_turns: int,
    budget_cny: float,
    max_papers: int,
    root: Path | None,
) -> None:
    home = root if root is not None else default_root()
    fields_db = home / "fields.db"
    embeddings_db = home / "embeddings.db"
    meta_path = home / "embeddings_meta.json"
    if not fields_db.exists():
        typer.echo(
            f"index missing at {fields_db}. Run `paper-copilot reindex --pdf-dir <dir>` first.",
            err=True,
        )
        raise typer.Exit(code=1)

    console = Console()
    embedder: Embedder | None = None
    with ExitStack() as stack:
        fields_store = stack.enter_context(FieldsStore.open(fields_db))
        embeddings_store: EmbeddingsStore | None = None
        if embeddings_db.exists():
            try:
                require_match(meta_path, embedding_model=MODEL_NAME, embedding_dim=EMBEDDING_DIM)
            except KnowledgeError as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(code=2) from exc
            with console.status("[dim]loading bge-m3…[/dim]"):
                embedder = Embedder()
                embedder.warmup()
            embeddings_store = stack.enter_context(
                EmbeddingsStore.open(embeddings_db, dim=EMBEDDING_DIM)
            )

        context = ResearchToolContext(
            fields_store=fields_store,
            embeddings_store=embeddings_store,
            encode_query=(
                (lambda query: embedder.encode([query])[0]) if embedder is not None else None
            ),
            pdf_dir=pdf_dir,
            root=home,
            max_papers=max_papers,
        )
        run = await run_research(
            topic=topic,
            llm=LLMClient(),
            context=context,
            root=home,
            max_turns=max_turns,
            max_budget_cny=budget_cny,
        )

    report_path = run.session_path.parent / "research-report.md"
    report_path.write_text(run.report_markdown, encoding="utf-8")
    console.print(Markdown(run.report_markdown))
    console.print()
    console.print(f"[dim]session: {run.session_path}[/dim]")
    console.print(f"[dim]report:  {report_path}[/dim]")
    console.print(
        f"[dim]terminated: {run.termination_reason}; "
        f"cost: ¥{run.cost.cost_cny:.4f}; turns: {len(run.events)} events[/dim]"
    )
