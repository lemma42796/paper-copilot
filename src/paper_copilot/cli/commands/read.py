"""`paper-copilot read <pdf>` subcommand."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Annotated, Literal, cast

import typer
from rich.console import Console
from rich.markdown import Markdown

from paper_copilot.agents.llm_client import LLMClient
from paper_copilot.agents.read_pipeline import run_read_pipeline
from paper_copilot.knowledge.embeddings_store import EmbeddingsStore
from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.session.paths import (
    compute_paper_id,
    default_root,
    embedding_cache_file,
    paper_dir,
)
from paper_copilot.shared.embedder import EMBEDDING_DIM, Embedder
from paper_copilot.shared.embedding_cache import CachedEmbedder, EmbeddingCache


def read(
    pdf_path: Annotated[Path, typer.Argument(help="Path to the paper PDF")],
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help=(
                "Re-run the pipeline and overwrite the existing session. "
                "Without --force, `read` just prints the existing report.md."
            ),
        ),
    ] = False,
    lang: Annotated[
        str,
        typer.Option(
            "--lang",
            "-l",
            help=(
                "Report language: en or zh. Narrative fields translate; "
                "dataset names, metrics, numbers, authors, raw quotes stay English."
            ),
        ),
    ] = "en",
) -> None:
    """Read a PDF end-to-end.

    Runs skim, deep, and related; writes report.md and updates indexes.
    """
    if lang not in ("en", "zh"):
        raise typer.BadParameter(f"unsupported language: {lang!r}; use 'en' or 'zh'")
    asyncio.run(_read_async(pdf_path, force, cast("Literal['en', 'zh']", lang)))


async def _read_async(pdf_path: Path, force: bool, language: Literal["en", "zh"]) -> None:
    if not pdf_path.exists():
        raise typer.BadParameter(f"PDF not found: {pdf_path}")

    pid = compute_paper_id(pdf_path)
    pdir = paper_dir(pid)
    if pdir.exists():
        if not force:
            report_path = pdir / "report.md"
            if not report_path.exists():
                raise typer.BadParameter(
                    f"session exists for paper_id={pid} at {pdir} but report.md "
                    "is missing. Rerun with --force to overwrite."
                )
            console = Console()
            console.print(Markdown(report_path.read_text(encoding="utf-8")))
            console.print()
            console.print(f"[dim]session: {pdir / 'session.jsonl'}[/dim]")
            console.print(f"[dim]report:  {report_path}[/dim]")
            console.print("[dim]已有结果 — 用 --force 重跑[/dim]")
            return
        shutil.rmtree(pdir)

    root = default_root()
    fields_db = root / "fields.db"
    embeddings_db = root / "embeddings.db"

    console = Console()
    with console.status("[dim]initializing text-embedding-v4…[/dim]"):
        raw_embedder = Embedder()

    with (
        FieldsStore.open(fields_db) as fields_store,
        EmbeddingsStore.open(embeddings_db, dim=EMBEDDING_DIM) as embeddings_store,
        EmbeddingCache.open(embedding_cache_file(root), dim=EMBEDDING_DIM) as embedding_cache,
    ):
        embedder = CachedEmbedder(raw_embedder, embedding_cache)
        run = await run_read_pipeline(
            pdf_path,
            client=LLMClient(),
            language=language,
            embedder=embedder,
            fields_store=fields_store,
            embeddings_store=embeddings_store,
            root=root,
        )

    console.print(Markdown(run.report_markdown))
    console.print()
    console.print(f"[dim]session: {run.session_path}[/dim]")
    console.print(f"[dim]report:  {run.report_path}[/dim]")
    if run.related_skipped_reason is not None:
        console.print(f"[dim]related: skipped ({run.related_skipped_reason})[/dim]")
    c = run.cost
    console.print(
        f"[dim]cost:    ¥{c.cost_cny:.4f} "
        f"(in={c.input_tokens}, out={c.output_tokens}, "
        f"cache_read={c.cache_read_tokens})[/dim]"
    )
