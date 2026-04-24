"""Sync a validated ``Paper`` into the knowledge indexes.

Two entry points:
- ``index_paper``: writes ``fields.db`` from the Paper JSON.
- ``index_paper_embeddings``: chunks sections + encodes + upserts ``embeddings.db``.

The caller owns loading: online from ``MainAgent.run`` passes a fresh
``Paper`` object, batch reindex (see ``cli/commands/reindex.py``) passes
the raw JSON payload read from ``session.jsonl``. Both converge here so
the store stays ignorant of pydantic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from paper_copilot.schemas import Paper
from paper_copilot.shared.chunking import Section, chunk_sections
from paper_copilot.shared.embedder import Embedder

from .embeddings_store import ChunkRow, EmbeddingsStore
from .fields_store import FieldsStore


def index_paper(
    paper: Paper | dict[str, Any],
    paper_id: str,
    store: FieldsStore,
    *,
    indexed_at: str | None = None,
) -> None:
    payload = paper.model_dump(mode="json") if isinstance(paper, Paper) else paper
    ts = indexed_at if indexed_at is not None else datetime.now(UTC).isoformat()
    store.upsert(paper_id, payload, ts)


def index_paper_embeddings(
    paper_id: str,
    sections: list[Section],
    *,
    store: EmbeddingsStore,
    embedder: Embedder,
    max_tokens: int = 512,
    overlap_tokens: int = 64,
    batch_size: int = 32,
) -> int:
    """Chunk + encode + replace_paper. Returns chunk count written."""
    chunks = chunk_sections(
        sections,
        token_spans=embedder.token_spans,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
    )
    if not chunks:
        store.delete_paper(paper_id)
        return 0
    texts = [c.text for c in chunks]
    vecs = embedder.encode(texts, batch_size=batch_size)
    rows = [
        ChunkRow(
            chunk_id=0,
            paper_id=paper_id,
            ord=c.ord,
            section=c.section_title,
            page_start=c.page_start,
            page_end=c.page_end,
            text=c.text,
        )
        for c in chunks
    ]
    store.replace_paper(paper_id, rows, vecs)
    return len(chunks)
