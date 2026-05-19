"""Cross-paper hybrid search.

Pipeline: structured filter on ``fields.db`` produces a candidate
``paper_id`` set, then vector KNN and optional FTS5/BM25 search both run
on ``embeddings.db``. Chunk rankings are fused with RRF, then grouped by
paper so a single paper result is returned with its best chunk plus
nearby evidence chunks.

No reranker — ARCHITECTURE.md 135 defers that. ``overfetch`` controls
the initial pool width (``k * overfetch`` chunks); if grouping leaves
fewer than ``k`` unique papers and the pool was the bottleneck, the
search escalates once to the full chunk index and re-groups. Worst
case is one extra full-table KNN scan per query.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from paper_copilot.knowledge.embeddings_store import (
    ChunkHit,
    EmbeddingsStore,
    TextHit,
)
from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.shared.errors import KnowledgeError


@dataclass(frozen=True, slots=True)
class SearchResult:
    paper_id: str
    title: str
    year: int
    best_chunk: ChunkHit
    paper_data: dict[str, Any]
    chunks: tuple[ChunkHit, ...] = field(default_factory=tuple)
    chunk_scores: tuple[ChunkScore, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ChunkScore:
    chunk_id: int
    rrf_score: float
    vector_rank: int | None
    bm25_rank: int | None
    vector_distance: float | None
    bm25_score: float | None


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
    max_chunks_per_paper: int = 3,
    query_text: str | None = None,
    rrf_k: int = 60,
) -> list[SearchResult]:
    if k <= 0:
        return []
    if overfetch < 1:
        raise KnowledgeError("overfetch must be >= 1")
    if max_chunks_per_paper < 1:
        raise KnowledgeError("max_chunks_per_paper must be >= 1")
    if rrf_k < 1:
        raise KnowledgeError("rrf_k must be >= 1")

    candidates = _candidate_paper_ids(
        fields_store=fields_store, year=year, contains=contains
    )
    if candidates is not None and not candidates:
        return []

    paper_ids_arg = list(candidates) if candidates is not None else None
    pool = k * overfetch
    vector_hits = embeddings_store.knn(query_vec, k=pool, paper_ids=paper_ids_arg)
    bm25_hits = (
        embeddings_store.bm25(query_text, k=pool, paper_ids=paper_ids_arg)
        if query_text is not None
        else []
    )
    fused = _fuse_hits(vector_hits, bm25_hits, rrf_k=rrf_k)
    if not fused:
        return []

    chunks_per_paper = _group_chunks_per_paper(fused, limit=max_chunks_per_paper)

    if len(chunks_per_paper) < k and (
        len(vector_hits) == pool or len(bm25_hits) == pool
    ):
        # Top-k*overfetch chunks clustered into < k papers. Re-pull at the
        # full index size so the per-paper group-by has room to surface
        # papers whose best chunk was outranked by a popular paper's tail.
        ceiling = embeddings_store.count_chunks()
        if ceiling > pool:
            vector_hits = embeddings_store.knn(
                query_vec,
                k=ceiling,
                paper_ids=paper_ids_arg,
            )
            bm25_hits = (
                embeddings_store.bm25(query_text, k=ceiling, paper_ids=paper_ids_arg)
                if query_text is not None
                else []
            )
            fused = _fuse_hits(vector_hits, bm25_hits, rrf_k=rrf_k)
            chunks_per_paper = _group_chunks_per_paper(
                fused,
                limit=max_chunks_per_paper,
            )

    ordered = sorted(
        chunks_per_paper.values(),
        key=lambda chunks: (-chunks[0].score.rrf_score, chunks[0].sort_rank),
    )[:k]

    results: list[SearchResult] = []
    for candidates_for_paper in ordered:
        h = candidates_for_paper[0].chunk
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
                chunks=tuple(candidate.chunk for candidate in candidates_for_paper),
                chunk_scores=tuple(
                    candidate.score for candidate in candidates_for_paper
                ),
            )
        )
    return results


@dataclass(frozen=True, slots=True)
class _FusedChunk:
    chunk: ChunkHit
    score: ChunkScore
    sort_rank: int


def _fuse_hits(
    vector_hits: list[ChunkHit],
    bm25_hits: list[TextHit],
    *,
    rrf_k: int,
) -> list[_FusedChunk]:
    candidates: dict[int, _FusionCandidate] = {}
    for rank, hit in enumerate(vector_hits, start=1):
        candidate = candidates.setdefault(
            hit.chunk_id,
            _FusionCandidate(chunk=hit, sort_rank=rank),
        )
        candidate.vector_rank = rank
        candidate.vector_distance = hit.distance
        candidate.sort_rank = min(candidate.sort_rank, rank)
        candidate.rrf_score += _rrf(rank, rrf_k=rrf_k)

    for rank, hit in enumerate(bm25_hits, start=1):
        candidate = candidates.setdefault(
            hit.chunk_id,
            _FusionCandidate(chunk=_chunk_from_text_hit(hit), sort_rank=rank),
        )
        candidate.bm25_rank = rank
        candidate.bm25_score = hit.bm25
        candidate.sort_rank = min(candidate.sort_rank, rank)
        candidate.rrf_score += _rrf(rank, rrf_k=rrf_k)

    return [
        candidate.to_fused_chunk()
        for candidate in sorted(
            candidates.values(),
            key=lambda item: (-item.rrf_score, item.sort_rank),
        )
    ]


@dataclass(slots=True)
class _FusionCandidate:
    chunk: ChunkHit
    sort_rank: int
    rrf_score: float = 0.0
    vector_rank: int | None = None
    bm25_rank: int | None = None
    vector_distance: float | None = None
    bm25_score: float | None = None

    def to_fused_chunk(self) -> _FusedChunk:
        score = ChunkScore(
            chunk_id=self.chunk.chunk_id,
            rrf_score=self.rrf_score,
            vector_rank=self.vector_rank,
            bm25_rank=self.bm25_rank,
            vector_distance=self.vector_distance,
            bm25_score=self.bm25_score,
        )
        return _FusedChunk(chunk=self.chunk, score=score, sort_rank=self.sort_rank)


def _chunk_from_text_hit(hit: TextHit) -> ChunkHit:
    return ChunkHit(
        chunk_id=hit.chunk_id,
        paper_id=hit.paper_id,
        ord=hit.ord,
        section=hit.section,
        page_start=hit.page_start,
        page_end=hit.page_end,
        text=hit.text,
        distance=hit.bm25,
    )


def _rrf(rank: int, *, rrf_k: int) -> float:
    return 1.0 / (rrf_k + rank)


def _group_chunks_per_paper(
    hits: list[_FusedChunk],
    *,
    limit: int,
) -> dict[str, list[_FusedChunk]]:
    grouped: dict[str, list[_FusedChunk]] = {}
    for h in hits:
        chunks = grouped.setdefault(h.chunk.paper_id, [])
        if len(chunks) < limit:
            chunks.append(h)
    return grouped


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
