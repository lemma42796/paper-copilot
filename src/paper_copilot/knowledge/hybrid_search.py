"""Cross-paper hybrid search.

Pipeline: structured filter on ``fields.db`` produces a candidate
``paper_id`` set, then the query vector runs KNN on ``embeddings.db``
restricted to that set, then chunks are grouped by paper so a single
hit per paper is returned with the best-matching chunk.

No reranker — ARCHITECTURE.md 135 defers that. The only tuning knob is
``overfetch``, which widens the KNN pool before the per-paper group-by
so a paper isn't missed when one bad chunk outranks its own best chunk.
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

    hits = embeddings_store.knn(
        query_vec,
        k=k * overfetch,
        paper_ids=list(candidates) if candidates is not None else None,
    )
    if not hits:
        return []

    best_per_paper: dict[str, ChunkHit] = {}
    for h in hits:
        prev = best_per_paper.get(h.paper_id)
        if prev is None or h.distance < prev.distance:
            best_per_paper[h.paper_id] = h

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
