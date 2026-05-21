from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field

from paper_copilot.knowledge.embeddings_store import ChunkHit, EmbeddingsStore
from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.knowledge.hybrid_search import SearchResult, search
from paper_copilot.knowledge.meta import require_match
from paper_copilot.session.paths import default_root, embedding_cache_file
from paper_copilot.shared.embedder import EMBEDDING_DIM, MODEL_NAME, Embedder
from paper_copilot.shared.embedding_cache import CachedEmbedder, EmbeddingCache, EmbeddingEncoder
from paper_copilot.shared.errors import EvalError

_SEMANTIC_ANCHOR_THRESHOLD = 0.75
_SEMANTIC_WINDOW_TOKENS = 45
_SEMANTIC_WINDOW_STRIDE = 20
_TOKEN_RE = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
    r"|[A-Za-z0-9]+(?:[-_'][A-Za-z0-9]+)*"
    r"|[^\s]"
)

type AnchorMatcher = Callable[[EvidenceAnchor, ChunkHit], bool]


class RelevantPaper(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class EvidenceAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class RetrievalQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    relevant_papers: list[RelevantPaper] = Field(min_length=1)
    evidence_anchors: list[EvidenceAnchor] = Field(default_factory=list)
    snippet_hints: list[str] = Field(default_factory=list)


class RetrievalSuite(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    queries: list[RetrievalQuery] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    rank: int
    paper_id: str
    title: str
    year: int
    best_chunk_id: int
    rrf_score: float | None
    vector_rank: int | None
    bm25_rank: int | None


@dataclass(frozen=True, slots=True)
class RetrievalQueryResult:
    query_id: str
    query: str
    relevant_papers: tuple[str, ...]
    hits: tuple[RetrievalHit, ...]
    recall_at_5: float
    recall_at_10: float
    precision_at_5: float
    precision_at_10: float
    missed_at_5: tuple[str, ...]
    missed_at_10: tuple[str, ...]
    evidence_anchor_count: int = 0
    evidence_recall_at_5: float | None = None
    evidence_recall_at_10: float | None = None
    evidence_anchor_precision_at_5: float | None = None
    evidence_anchor_precision_at_10: float | None = None
    missed_evidence_at_5: tuple[str, ...] = ()
    missed_evidence_at_10: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RetrievalEvalResult:
    suite_name: str
    queries: tuple[RetrievalQueryResult, ...]

    @property
    def mean_recall_at_5(self) -> float:
        return _mean(q.recall_at_5 for q in self.queries)

    @property
    def mean_recall_at_10(self) -> float:
        return _mean(q.recall_at_10 for q in self.queries)

    @property
    def mean_precision_at_5(self) -> float:
        return _mean(q.precision_at_5 for q in self.queries)

    @property
    def mean_precision_at_10(self) -> float:
        return _mean(q.precision_at_10 for q in self.queries)

    @property
    def mean_evidence_recall_at_5(self) -> float | None:
        return _mean_optional(q.evidence_recall_at_5 for q in self.queries)

    @property
    def mean_evidence_recall_at_10(self) -> float | None:
        return _mean_optional(q.evidence_recall_at_10 for q in self.queries)

    @property
    def mean_evidence_anchor_precision_at_5(self) -> float | None:
        return _mean_optional(q.evidence_anchor_precision_at_5 for q in self.queries)

    @property
    def mean_evidence_anchor_precision_at_10(self) -> float | None:
        return _mean_optional(q.evidence_anchor_precision_at_10 for q in self.queries)


def load_retrieval_suite(path: Path) -> RetrievalSuite:
    if not path.exists():
        raise EvalError(f"retrieval suite file not found: {path}")
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise EvalError(f"retrieval suite must be a YAML mapping at top level: {path}")
    return RetrievalSuite.model_validate(raw)


def run_retrieval_eval(
    suite: RetrievalSuite,
    *,
    root: Path | None = None,
    k: int = 10,
) -> RetrievalEvalResult:
    if k < 10:
        raise EvalError("retrieval eval k must be >= 10 so recall@10 is defined")

    home = root if root is not None else default_root()
    fields_db = home / "fields.db"
    embeddings_db = home / "embeddings.db"
    meta_path = home / "embeddings_meta.json"
    if not fields_db.exists():
        raise EvalError(f"fields.db not found: {fields_db}")
    if not embeddings_db.exists():
        raise EvalError(f"embeddings.db not found: {embeddings_db}")
    require_match(meta_path, embedding_model=MODEL_NAME, embedding_dim=EMBEDDING_DIM)

    raw_embedder = Embedder()
    query_results: list[RetrievalQueryResult] = []
    with (
        FieldsStore.open(fields_db) as fields_store,
        EmbeddingsStore.open(embeddings_db, dim=EMBEDDING_DIM) as embeddings_store,
        EmbeddingCache.open(embedding_cache_file(home), dim=EMBEDDING_DIM) as embedding_cache,
    ):
        embedder = CachedEmbedder(raw_embedder, embedding_cache)
        for query in suite.queries:
            query_vec = embedder.encode([query.query])[0]
            hits = search(
                query_vec,
                fields_store=fields_store,
                embeddings_store=embeddings_store,
                k=k,
                query_text=query.query,
            )
            anchor_matcher = _build_semantic_anchor_matcher(
                tuple(query.evidence_anchors),
                hits[:10],
                embedder=embedder,
            )
            query_results.append(_score_query(query, hits, anchor_matcher=anchor_matcher))

    return RetrievalEvalResult(suite_name=suite.name, queries=tuple(query_results))


def _score_query(
    query: RetrievalQuery,
    hits: list[SearchResult],
    *,
    anchor_matcher: AnchorMatcher | None = None,
) -> RetrievalQueryResult:
    relevant = tuple(p.paper_id for p in query.relevant_papers)
    hit_rows = tuple(
        _hit_from_result(rank, result) for rank, result in enumerate(hits, start=1)
    )
    anchors = tuple(query.evidence_anchors)
    matcher = anchor_matcher if anchor_matcher is not None else _anchor_exact_match
    return RetrievalQueryResult(
        query_id=query.id,
        query=query.query,
        relevant_papers=relevant,
        hits=hit_rows,
        recall_at_5=_recall(relevant, hit_rows[:5]),
        recall_at_10=_recall(relevant, hit_rows[:10]),
        precision_at_5=_precision(relevant, hit_rows[:5]),
        precision_at_10=_precision(relevant, hit_rows[:10]),
        missed_at_5=_missed(relevant, hit_rows[:5]),
        missed_at_10=_missed(relevant, hit_rows[:10]),
        evidence_anchor_count=len(anchors),
        evidence_recall_at_5=_evidence_recall(anchors, hits[:5], matcher),
        evidence_recall_at_10=_evidence_recall(anchors, hits[:10], matcher),
        evidence_anchor_precision_at_5=_evidence_anchor_precision(
            anchors, hits[:5], matcher
        ),
        evidence_anchor_precision_at_10=_evidence_anchor_precision(
            anchors, hits[:10], matcher
        ),
        missed_evidence_at_5=_missed_evidence(anchors, hits[:5], matcher),
        missed_evidence_at_10=_missed_evidence(anchors, hits[:10], matcher),
    )


def _hit_from_result(rank: int, result: SearchResult) -> RetrievalHit:
    score = result.chunk_scores[0] if result.chunk_scores else None
    return RetrievalHit(
        rank=rank,
        paper_id=result.paper_id,
        title=result.title,
        year=result.year,
        best_chunk_id=result.best_chunk.chunk_id,
        rrf_score=score.rrf_score if score is not None else None,
        vector_rank=score.vector_rank if score is not None else None,
        bm25_rank=score.bm25_rank if score is not None else None,
    )


def _recall(relevant: tuple[str, ...], hits: tuple[RetrievalHit, ...]) -> float:
    relevant_set = set(relevant)
    hit_set = {hit.paper_id for hit in hits}
    return len(relevant_set & hit_set) / len(relevant_set)


def _precision(relevant: tuple[str, ...], hits: tuple[RetrievalHit, ...]) -> float:
    if not hits:
        return 0.0
    relevant_set = set(relevant)
    hit_set = {hit.paper_id for hit in hits}
    return len(relevant_set & hit_set) / len(hit_set)


def _missed(relevant: tuple[str, ...], hits: tuple[RetrievalHit, ...]) -> tuple[str, ...]:
    hit_set = {hit.paper_id for hit in hits}
    return tuple(paper_id for paper_id in relevant if paper_id not in hit_set)


def _evidence_recall(
    anchors: tuple[EvidenceAnchor, ...],
    hits: list[SearchResult],
    anchor_matcher: AnchorMatcher,
) -> float | None:
    if not anchors:
        return None
    matched = sum(1 for anchor in anchors if _anchor_hits(anchor, hits, anchor_matcher))
    return matched / len(anchors)


def _missed_evidence(
    anchors: tuple[EvidenceAnchor, ...],
    hits: list[SearchResult],
    anchor_matcher: AnchorMatcher,
) -> tuple[str, ...]:
    if not anchors:
        return ()
    return tuple(
        _anchor_label(anchor)
        for anchor in anchors
        if not _anchor_hits(anchor, hits, anchor_matcher)
    )


def _evidence_anchor_precision(
    anchors: tuple[EvidenceAnchor, ...],
    hits: list[SearchResult],
    anchor_matcher: AnchorMatcher,
) -> float | None:
    if not anchors:
        return None
    anchors_by_paper: dict[str, list[EvidenceAnchor]] = {}
    for anchor in anchors:
        anchors_by_paper.setdefault(anchor.paper_id, []).append(anchor)

    total = 0
    matched = 0
    seen: set[int] = set()
    for result in hits:
        paper_anchors = anchors_by_paper.get(result.paper_id)
        if paper_anchors is None:
            continue
        for chunk in _result_chunks(result):
            if chunk.chunk_id in seen:
                continue
            seen.add(chunk.chunk_id)
            total += 1
            if any(anchor_matcher(anchor, chunk) for anchor in paper_anchors):
                matched += 1
    if total == 0:
        return 0.0
    return matched / total


def _anchor_hits(
    anchor: EvidenceAnchor,
    hits: list[SearchResult],
    anchor_matcher: AnchorMatcher,
) -> bool:
    for result in hits:
        if result.paper_id != anchor.paper_id:
            continue
        for chunk in _result_chunks(result):
            if anchor_matcher(anchor, chunk):
                return True
    return False


def _anchor_exact_match(anchor: EvidenceAnchor, chunk: ChunkHit) -> bool:
    return _normalize_text(anchor.text) in _normalize_text(chunk.text)


def _build_semantic_anchor_matcher(
    anchors: tuple[EvidenceAnchor, ...],
    hits: list[SearchResult],
    *,
    embedder: EmbeddingEncoder,
    threshold: float = _SEMANTIC_ANCHOR_THRESHOLD,
) -> AnchorMatcher:
    if not anchors:
        return _anchor_exact_match

    chunks_by_paper: dict[str, list[ChunkHit]] = {}
    for result in hits:
        chunks_by_paper.setdefault(result.paper_id, []).extend(_result_chunks(result))

    semantic_matches: set[tuple[str, str, int]] = set()
    for anchor in anchors:
        candidates = chunks_by_paper.get(anchor.paper_id, [])
        if not candidates:
            continue

        window_texts: list[str] = []
        window_chunk_ids: list[int] = []
        for chunk in candidates:
            if _anchor_exact_match(anchor, chunk):
                semantic_matches.add(_anchor_key(anchor, chunk))
                continue
            for window in _semantic_windows(chunk.text):
                window_texts.append(window)
                window_chunk_ids.append(chunk.chunk_id)

        if not window_texts:
            continue
        vectors = embedder.encode([anchor.text, *window_texts])
        anchor_vec = vectors[0]
        window_vecs = vectors[1:]
        for chunk_id, similarity in zip(
            window_chunk_ids,
            _cosine_similarities(anchor_vec, window_vecs),
            strict=True,
        ):
            if similarity >= threshold:
                semantic_matches.add((anchor.paper_id, _normalize_text(anchor.text), chunk_id))

    def _matches(anchor: EvidenceAnchor, chunk: ChunkHit) -> bool:
        return _anchor_exact_match(anchor, chunk) or _anchor_key(anchor, chunk) in semantic_matches

    return _matches


def _anchor_key(anchor: EvidenceAnchor, chunk: ChunkHit) -> tuple[str, str, int]:
    return (anchor.paper_id, _normalize_text(anchor.text), chunk.chunk_id)


def _semantic_windows(text: str) -> list[str]:
    tokens = _TOKEN_RE.findall(text)
    if not tokens:
        return []
    if len(tokens) <= _SEMANTIC_WINDOW_TOKENS:
        return [" ".join(tokens)]

    windows: list[str] = []
    for start in range(0, len(tokens), _SEMANTIC_WINDOW_STRIDE):
        window = tokens[start : start + _SEMANTIC_WINDOW_TOKENS]
        if len(window) < 8 and windows:
            break
        windows.append(" ".join(window))
        if start + _SEMANTIC_WINDOW_TOKENS >= len(tokens):
            break
    return windows


def _cosine_similarities(anchor_vec: np.ndarray, window_vecs: np.ndarray) -> np.ndarray:
    anchor_norm = float(np.linalg.norm(anchor_vec))
    window_norms = np.linalg.norm(window_vecs, axis=1)
    return np.asarray((window_vecs @ anchor_vec) / (window_norms * anchor_norm))


def _result_chunks(result: SearchResult) -> tuple[ChunkHit, ...]:
    return result.chunks or (result.best_chunk,)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _anchor_label(anchor: EvidenceAnchor) -> str:
    text = _normalize_text(anchor.text)
    if len(text) > 64:
        text = f"{text[:61]}..."
    return f"{anchor.paper_id}:{text}"


def _mean(values: Iterable[float]) -> float:
    nums = list(values)
    if not nums:
        return 0.0
    return sum(nums) / len(nums)


def _mean_optional(values: Iterable[float | None]) -> float | None:
    nums = [value for value in values if value is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)
