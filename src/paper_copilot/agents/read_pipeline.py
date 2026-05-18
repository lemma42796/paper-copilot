"""Reusable single-paper read pipeline for CLI and ResearchAgent tools."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from paper_copilot.agents.llm_client import LLMClient
from paper_copilot.agents.loop import LLMResponse
from paper_copilot.agents.main import MainAgent
from paper_copilot.knowledge.embeddings_store import EmbeddingsStore
from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.knowledge.graph_store import append_links
from paper_copilot.knowledge.meta import IndexMeta, write_meta
from paper_copilot.knowledge.sync import index_paper, index_paper_embeddings
from paper_copilot.retrieval.sections import split_by_sections
from paper_copilot.session.paths import compute_paper_id, default_root, paper_dir
from paper_copilot.shared.chunking import Section
from paper_copilot.shared.cost import CostSnapshot
from paper_copilot.shared.embedder import EMBEDDING_DIM, MODEL_NAME, Embedder
from paper_copilot.shared.render import to_markdown

__all__ = ["ReadPipelineRun", "run_read_pipeline"]


@dataclass(frozen=True, slots=True)
class ReadPipelineRun:
    paper_id: str
    title: str
    report_markdown: str
    report_path: Path
    session_path: Path
    cost: CostSnapshot
    chunks_indexed: int
    related_skipped_reason: str | None
    llm_responses: tuple[LLMResponse, ...]


async def run_read_pipeline(
    pdf_path: Path,
    *,
    client: LLMClient,
    fields_store: FieldsStore,
    embeddings_store: EmbeddingsStore,
    embedder: Embedder,
    root: Path | None = None,
    language: Literal["en", "zh"] = "en",
) -> ReadPipelineRun:
    paper_id = compute_paper_id(pdf_path)
    home = root if root is not None else default_root()

    agent = MainAgent(client, root=home)
    run = await agent.run(
        pdf_path,
        language=language,
        embedder=embedder,
        fields_store=fields_store,
        embeddings_store=embeddings_store,
    )

    report_markdown = to_markdown(run.paper, language=language)
    report_path = paper_dir(paper_id, home) / "report.md"
    report_path.write_text(report_markdown, encoding="utf-8")

    index_paper(run.paper, paper_id, fields_store)

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
    chunks_indexed = index_paper_embeddings(
        paper_id,
        sections,
        store=embeddings_store,
        embedder=embedder,
    )
    write_meta(
        home / "embeddings_meta.json",
        IndexMeta.fresh(embedding_model=MODEL_NAME, embedding_dim=EMBEDDING_DIM).with_counts(
            n_papers=embeddings_store.count_papers(),
            n_chunks=embeddings_store.count_chunks(),
        ),
    )

    if run.paper.cross_paper_links:
        append_links(paper_id, list(run.paper.cross_paper_links), root=home)

    responses = [
        *run.skim_run.responses,
        *run.deep_run.responses,
        *(run.related_run.responses if run.related_run is not None else ()),
    ]
    return ReadPipelineRun(
        paper_id=paper_id,
        title=run.paper.meta.title,
        report_markdown=report_markdown,
        report_path=report_path,
        session_path=run.session_path,
        cost=run.cost,
        chunks_indexed=chunks_indexed,
        related_skipped_reason=(
            run.related_run.skipped_reason if run.related_run is not None else None
        ),
        llm_responses=tuple(responses),
    )
