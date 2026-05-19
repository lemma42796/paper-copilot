from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from paper_copilot.knowledge.embeddings_store import EmbeddingsStore
from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.knowledge.hybrid_search import SearchResult, search
from paper_copilot.knowledge.meta import require_match
from paper_copilot.session.paths import default_root
from paper_copilot.shared.embedder import EMBEDDING_DIM, MODEL_NAME, Embedder
from paper_copilot.shared.errors import EvalError


class RelevantPaper(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class RetrievalQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    relevant_papers: list[RelevantPaper] = Field(min_length=1)
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
    missed_at_5: tuple[str, ...]
    missed_at_10: tuple[str, ...]


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

    embedder = Embedder()
    query_results: list[RetrievalQueryResult] = []
    with (
        FieldsStore.open(fields_db) as fields_store,
        EmbeddingsStore.open(embeddings_db, dim=EMBEDDING_DIM) as embeddings_store,
    ):
        for query in suite.queries:
            query_vec = embedder.encode([query.query])[0]
            hits = search(
                query_vec,
                fields_store=fields_store,
                embeddings_store=embeddings_store,
                k=k,
                query_text=query.query,
            )
            query_results.append(_score_query(query, hits))

    return RetrievalEvalResult(suite_name=suite.name, queries=tuple(query_results))


def _score_query(
    query: RetrievalQuery,
    hits: list[SearchResult],
) -> RetrievalQueryResult:
    relevant = tuple(p.paper_id for p in query.relevant_papers)
    hit_rows = tuple(
        _hit_from_result(rank, result) for rank, result in enumerate(hits, start=1)
    )
    return RetrievalQueryResult(
        query_id=query.id,
        query=query.query,
        relevant_papers=relevant,
        hits=hit_rows,
        recall_at_5=_recall(relevant, hit_rows[:5]),
        recall_at_10=_recall(relevant, hit_rows[:10]),
        missed_at_5=_missed(relevant, hit_rows[:5]),
        missed_at_10=_missed(relevant, hit_rows[:10]),
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


def _missed(relevant: tuple[str, ...], hits: tuple[RetrievalHit, ...]) -> tuple[str, ...]:
    hit_set = {hit.paper_id for hit in hits}
    return tuple(paper_id for paper_id in relevant if paper_id not in hit_set)


def _mean(values: Iterable[float]) -> float:
    nums = list(values)
    if not nums:
        return 0.0
    return sum(nums) / len(nums)
