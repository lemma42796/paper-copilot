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
from paper_copilot.agents.main import MainAgent
from paper_copilot.cli.render import to_markdown
from paper_copilot.knowledge.embeddings_store import EmbeddingsStore
from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.knowledge.graph_store import append_links
from paper_copilot.knowledge.meta import IndexMeta, write_meta
from paper_copilot.knowledge.sync import index_paper, index_paper_embeddings
from paper_copilot.retrieval.sections import split_by_sections
from paper_copilot.session.paths import compute_paper_id, default_root, paper_dir
from paper_copilot.shared.chunking import Section
from paper_copilot.shared.embedder import EMBEDDING_DIM, MODEL_NAME, Embedder


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
    """Read a PDF end-to-end (skim → deep → related); write report.md and index fields + embeddings."""
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
    meta_path = root / "embeddings_meta.json"

    console = Console()
    with console.status("[dim]loading bge-m3 (first run downloads)…[/dim]"):
        embedder = Embedder()

    with (
        FieldsStore.open(fields_db) as fields_store,
        EmbeddingsStore.open(embeddings_db, dim=EMBEDDING_DIM) as embeddings_store,
    ):
        agent = MainAgent(LLMClient())
        run = await agent.run(
            pdf_path,
            language=language,
            embedder=embedder,
            fields_store=fields_store,
            embeddings_store=embeddings_store,
        )

        md = to_markdown(run.paper, language=language)
        report_path = pdir / "report.md"
        report_path.write_text(md, encoding="utf-8")

        index_paper(run.paper, pid, fields_store)

        raw_sections = split_by_sections(pdf_path, run.skim_run.result.skeleton)
        sections = [
            Section(
                title=s.title,
                page_start=s.page_start,
                page_end=s.page_end,
                text=s.text,
            )
            for s in raw_sections
        ]
        index_paper_embeddings(pid, sections, store=embeddings_store, embedder=embedder)
        write_meta(
            meta_path,
            IndexMeta.fresh(embedding_model=MODEL_NAME, embedding_dim=EMBEDDING_DIM).with_counts(
                n_papers=embeddings_store.count_papers(),
                n_chunks=embeddings_store.count_chunks(),
            ),
        )

    if run.paper.cross_paper_links:
        append_links(pid, list(run.paper.cross_paper_links), root=root)

    console.print(Markdown(md))
    console.print()
    console.print(f"[dim]session: {run.session_path}[/dim]")
    console.print(f"[dim]report:  {report_path}[/dim]")
    if run.related_run is not None and run.related_run.skipped_reason is not None:
        console.print(f"[dim]related: skipped ({run.related_run.skipped_reason})[/dim]")
    c = run.cost
    console.print(
        f"[dim]cost:    ¥{c.cost_cny:.4f} "
        f"(in={c.input_tokens}, out={c.output_tokens}, "
        f"cache_read={c.cache_read_tokens})[/dim]"
    )
