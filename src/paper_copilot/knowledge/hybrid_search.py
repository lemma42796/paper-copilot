"""Cross-paper hybrid search.

Pipeline: structured filter on ``fields.db`` produces a candidate
``paper_id`` set, then the query vector runs KNN on ``embeddings.db``
restricted to that set, then chunks are grouped by paper so a single
hit per paper is returned with the best-matching chunk.

No reranker — ARCHITECTURE.md 135 defers that. ``overfetch`` controls
the initial pool width (``k * overfetch`` chunks); if grouping leaves
fewer than ``k`` unique papers and the pool was the bottleneck, the
search escalates once to the full chunk index and re-groups. Worst
case is one extra full-table KNN scan per query.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from paper_copilot.knowledge.embeddings_store import ChunkHit, EmbeddingsStore
from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.shared.errors import KnowledgeError


@dataclass(frozen=True, slots=True)
class SearchResult:
    paper_id: str
    title: str
    year: int
    best_chunk: ChunkHit
    paper_data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ContainsFilter:
    field: str
    term: str


def search(
    query_vec: np.ndarray,
    *,
    fields_store: FieldsStore,
    embeddings_store: EmbeddingsStore,
    k: int = 10,
    year: int | None = None,
    contains: ContainsFilter | None = None,
    overfetch: int = 5,
) -> list[SearchResult]:
    if k <= 0:
        return []
    if overfetch < 1:
        raise KnowledgeError("overfetch must be >= 1")

    candidates = _candidate_paper_ids(
        fields_store=fields_store, year=year, contains=contains
    )
    if candidates is not None and not candidates:
        return []

    paper_ids_arg = list(candidates) if candidates is not None else None
    pool = k * overfetch
    hits = embeddings_store.knn(query_vec, k=pool, paper_ids=paper_ids_arg)
    if not hits:
        return []

    best_per_paper = _group_best_chunk_per_paper(hits)

    if len(best_per_paper) < k and len(hits) == pool:
        # Top-k*overfetch chunks clustered into < k papers. Re-pull at the
        # full index size so the per-paper group-by has room to surface
        # papers whose best chunk was outranked by a popular paper's tail.
        ceiling = embeddings_store.count_chunks()
        if ceiling > pool:
            hits = embeddings_store.knn(query_vec, k=ceiling, paper_ids=paper_ids_arg)
            best_per_paper = _group_best_chunk_per_paper(hits)

    ordered = sorted(best_per_paper.values(), key=lambda h: h.distance)[:k]

    results: list[SearchResult] = []
    for h in ordered:
        row = fields_store.get(h.paper_id)
        if row is None:
            continue  # indexed chunk without a fields row — stale; skip quietly
        meta = row.data.get("meta", {})
        results.append(
            SearchResult(
                paper_id=h.paper_id,
                title=str(meta.get("title", "")),
                year=int(meta.get("year", 0)),
                best_chunk=h,
                paper_data=row.data,
            )
        )
    return results


def _group_best_chunk_per_paper(hits: list[ChunkHit]) -> dict[str, ChunkHit]:
    best: dict[str, ChunkHit] = {}
    for h in hits:
        prev = best.get(h.paper_id)
        if prev is None or h.distance < prev.distance:
            best[h.paper_id] = h
    return best


def _candidate_paper_ids(
    *,
    fields_store: FieldsStore,
    year: int | None,
    contains: ContainsFilter | None,
) -> set[str] | None:
    if year is None and contains is None:
        return None  # no filter — let KNN span the whole index
    if contains is not None:
        rows = fields_store.query_contains(
            contains.field, contains.term, year=year
        )
    else:
        rows = fields_store.list_all(year=year)
    return {r.paper_id for r in rows}
