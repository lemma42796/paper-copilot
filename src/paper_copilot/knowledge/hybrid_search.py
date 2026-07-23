"""Cross-paper hybrid search.

Pipeline: structured filter on ``fields.db`` produces a candidate
``paper_id`` set, then vector KNN and optional FTS5/BM25 search both run
on ``embeddings.db``. Chunk rankings are fused with RRF, then grouped by
paper to fix the top paper order. Each selected paper then gets a
paper-local evidence pool, so the returned evidence chunks are not limited
to the first global chunk pool.

No reranker — ARCHITECTURE.md 135 defers that. ``overfetch`` controls
the initial pool width (``k * overfetch`` chunks); if grouping leaves
fewer than ``k`` unique papers and the pool was the bottleneck, the
search escalates once to the full chunk index and re-groups. Worst
case is one extra full-table KNN scan per query.
"""

from __future__ import annotations

import re
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

_TOKEN_RE = re.compile(r"[\w]+", flags=re.UNICODE)
_QUERY_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "also",
        "and",
        "are",
        "can",
        "did",
        "does",
        "for",
        "from",
        "how",
        "into",
        "its",
        "paper",
        "papers",
        "show",
        "shows",
        "that",
        "the",
        "their",
        "this",
        "use",
        "used",
        "uses",
        "using",
        "what",
        "when",
        "where",
        "which",
        "with",
    }
)
_SELECTOR_LEXICAL_WEIGHT = 0.006
_SELECTOR_BM25_WEIGHT = 0.004
_SELECTOR_BOTH_MODALITY_BONUS = 0.002
_SELECTOR_SECTION_WEIGHT = 0.002
_SELECTOR_REFERENCE_PENALTY = 0.004
_SELECTOR_REDUNDANCY_WEIGHT = 0.008


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
    query_vec: np.ndarray | None,
    *,
    fields_store: FieldsStore,
    embeddings_store: EmbeddingsStore,
    k: int = 10,
    year: int | None = None,
    contains: ContainsFilter | None = None,
    overfetch: int = 5,
    max_chunks_per_paper: int = 3,
    evidence_pool_per_paper: int = 20,
    query_text: str | None = None,
    paper_ids: list[str] | set[str] | None = None,
    rrf_k: int = 60,
) -> list[SearchResult]:
    if k <= 0:
        return []
    if overfetch < 1:
        raise KnowledgeError("overfetch must be >= 1")
    if max_chunks_per_paper < 1:
        raise KnowledgeError("max_chunks_per_paper must be >= 1")
    if evidence_pool_per_paper < 1:
        raise KnowledgeError("evidence_pool_per_paper must be >= 1")
    if rrf_k < 1:
        raise KnowledgeError("rrf_k must be >= 1")
    if query_vec is None and query_text is None:
        raise KnowledgeError("query_vec or query_text is required")

    candidates = _candidate_paper_ids(
        fields_store=fields_store, year=year, contains=contains
    )
    if paper_ids is not None:
        explicit_candidates = set(paper_ids)
        candidates = (
            explicit_candidates
            if candidates is None
            else candidates & explicit_candidates
        )
    if candidates is not None and not candidates:
        return []

    paper_ids_arg = list(candidates) if candidates is not None else None
    pool = k * overfetch
    vector_hits = (
        embeddings_store.knn(query_vec, k=pool, paper_ids=paper_ids_arg)
        if query_vec is not None
        else []
    )
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
        (query_vec is not None and len(vector_hits) == pool)
        or len(bm25_hits) == pool
    ):
        # Top-k*overfetch chunks clustered into < k papers. Re-pull at the
        # full index size so the per-paper group-by has room to surface
        # papers whose best chunk was outranked by a popular paper's tail.
        ceiling = embeddings_store.count_chunks()
        if ceiling > pool:
            vector_hits = (
                embeddings_store.knn(
                    query_vec,
                    k=ceiling,
                    paper_ids=paper_ids_arg,
                )
                if query_vec is not None
                else []
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
        paper_id = candidates_for_paper[0].chunk.paper_id
        refined = _paper_local_chunks(
            query_vec,
            embeddings_store=embeddings_store,
            paper_id=paper_id,
            query_text=query_text,
            pool=max(evidence_pool_per_paper, max_chunks_per_paper),
            limit=max_chunks_per_paper,
            rrf_k=rrf_k,
        )
        selected_chunks = refined or candidates_for_paper
        h = selected_chunks[0].chunk
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
                chunks=tuple(candidate.chunk for candidate in selected_chunks),
                chunk_scores=tuple(
                    candidate.score for candidate in selected_chunks
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
    for rank, vector_hit in enumerate(vector_hits, start=1):
        candidate = candidates.setdefault(
            vector_hit.chunk_id,
            _FusionCandidate(chunk=vector_hit, sort_rank=rank),
        )
        candidate.vector_rank = rank
        candidate.vector_distance = vector_hit.distance
        candidate.sort_rank = min(candidate.sort_rank, rank)
        candidate.rrf_score += _rrf(rank, rrf_k=rrf_k)

    for rank, text_hit in enumerate(bm25_hits, start=1):
        candidate = candidates.setdefault(
            text_hit.chunk_id,
            _FusionCandidate(chunk=_chunk_from_text_hit(text_hit), sort_rank=rank),
        )
        candidate.bm25_rank = rank
        candidate.bm25_score = text_hit.bm25
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


def _paper_local_chunks(
    query_vec: np.ndarray | None,
    *,
    embeddings_store: EmbeddingsStore,
    paper_id: str,
    query_text: str | None,
    pool: int,
    limit: int,
    rrf_k: int,
) -> list[_FusedChunk]:
    vector_hits = (
        embeddings_store.knn(query_vec, k=pool, paper_ids=[paper_id])
        if query_vec is not None
        else []
    )
    bm25_hits = (
        embeddings_store.bm25(query_text, k=pool, paper_ids=[paper_id])
        if query_text is not None
        else []
    )
    candidates = _fuse_hits(vector_hits, bm25_hits, rrf_k=rrf_k)
    return _select_evidence_chunks(candidates, query_text=query_text, limit=limit)


def _select_evidence_chunks(
    candidates: list[_FusedChunk],
    *,
    query_text: str | None,
    limit: int,
) -> list[_FusedChunk]:
    if limit <= 0:
        return []
    if len(candidates) <= limit:
        return candidates[:limit]

    query_terms = _content_terms(query_text or "")
    terms_by_chunk = {
        candidate.chunk.chunk_id: _content_terms(candidate.chunk.text)
        for candidate in candidates
    }
    remaining = list(candidates)
    selected: list[_FusedChunk] = []
    while remaining and len(selected) < limit:
        chosen = max(
            remaining,
            key=lambda candidate: (
                _selector_score(
                    candidate,
                    query_terms=query_terms,
                    chunk_terms=terms_by_chunk[candidate.chunk.chunk_id],
                )
                - _redundancy_penalty(
                    candidate,
                    selected=selected,
                    terms_by_chunk=terms_by_chunk,
                ),
                -candidate.sort_rank,
            ),
        )
        selected.append(chosen)
        remaining.remove(chosen)
    return selected


def _selector_score(
    candidate: _FusedChunk,
    *,
    query_terms: frozenset[str],
    chunk_terms: frozenset[str],
) -> float:
    score = candidate.score.rrf_score
    if query_terms and chunk_terms:
        score += (
            _SELECTOR_LEXICAL_WEIGHT
            * len(query_terms & chunk_terms)
            / len(query_terms)
        )
    if candidate.score.bm25_rank is not None:
        score += _rank_bonus(candidate.score.bm25_rank, _SELECTOR_BM25_WEIGHT)
    if candidate.score.vector_rank is not None and candidate.score.bm25_rank is not None:
        score += _SELECTOR_BOTH_MODALITY_BONUS
    score += _section_bonus(candidate.chunk.section)
    return score


def _rank_bonus(rank: int, max_bonus: float) -> float:
    return float(max_bonus / (rank**0.5))


def _section_bonus(section: str) -> float:
    normalized = section.casefold()
    if "reference" in normalized or "acknowledg" in normalized:
        return -_SELECTOR_REFERENCE_PENALTY
    evidence_sections = (
        "ablation",
        "analysis",
        "approach",
        "evaluation",
        "experiment",
        "framework",
        "method",
        "model",
        "result",
    )
    if any(term in normalized for term in evidence_sections):
        return _SELECTOR_SECTION_WEIGHT
    return 0.0


def _redundancy_penalty(
    candidate: _FusedChunk,
    *,
    selected: list[_FusedChunk],
    terms_by_chunk: dict[int, frozenset[str]],
) -> float:
    if not selected:
        return 0.0
    candidate_terms = terms_by_chunk[candidate.chunk.chunk_id]
    if not candidate_terms:
        return 0.0
    max_overlap = max(
        _jaccard(candidate_terms, terms_by_chunk[item.chunk.chunk_id])
        for item in selected
    )
    return _SELECTOR_REDUNDANCY_WEIGHT * max_overlap


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _content_terms(text: str) -> frozenset[str]:
    return frozenset(
        token
        for token in _TOKEN_RE.findall(text.casefold())
        if len(token) >= 3 and token not in _QUERY_STOPWORDS
    )


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
