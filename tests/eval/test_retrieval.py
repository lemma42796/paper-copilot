from __future__ import annotations

import pytest

from paper_copilot.eval.retrieval import (
    EvidenceAnchor,
    RelevantPaper,
    RetrievalQuery,
    _score_query,
)
from paper_copilot.knowledge.embeddings_store import ChunkHit
from paper_copilot.knowledge.hybrid_search import SearchResult


def _chunk(
    paper_id: str,
    chunk_id: int,
    text: str,
) -> ChunkHit:
    return ChunkHit(
        chunk_id=chunk_id,
        paper_id=paper_id,
        ord=chunk_id,
        section="Abstract",
        page_start=1,
        page_end=1,
        text=text,
        distance=0.1,
    )


def _result(
    paper_id: str,
    *,
    chunk_id: int,
    text: str,
) -> SearchResult:
    chunk = _chunk(paper_id, chunk_id, text)
    return SearchResult(
        paper_id=paper_id,
        title=f"Paper {paper_id}",
        year=2026,
        best_chunk=chunk,
        paper_data={"meta": {"title": f"Paper {paper_id}", "year": 2026}},
        chunks=(chunk,),
    )


def test_score_query_computes_evidence_anchor_recall() -> None:
    query = RetrievalQuery(
        id="q1",
        query="residual learning",
        intent="exact_method_lookup",
        relevant_papers=[RelevantPaper(paper_id="p1", reason="target")],
        evidence_anchors=[
            EvidenceAnchor(paper_id="p1", text="deep residual learning framework"),
            EvidenceAnchor(paper_id="p2", text="missing anchor"),
        ],
    )

    result = _score_query(
        query,
        [
            _result(
                "p1",
                chunk_id=7,
                text="We introduce a deep residual learning framework for image recognition.",
            ),
        ],
    )

    assert result.recall_at_5 == 1.0
    assert result.precision_at_5 == 1.0
    assert result.evidence_anchor_count == 2
    assert result.evidence_recall_at_5 == pytest.approx(0.5)
    assert result.evidence_recall_at_10 == pytest.approx(0.5)
    assert result.evidence_anchor_precision_at_5 == pytest.approx(1.0)
    assert result.evidence_anchor_precision_at_10 == pytest.approx(1.0)
    assert result.missed_evidence_at_10 == ("p2:missing anchor",)


def test_score_query_accepts_semantic_anchor_matcher() -> None:
    query = RetrievalQuery(
        id="q1",
        query="residual learning",
        intent="exact_method_lookup",
        relevant_papers=[RelevantPaper(paper_id="p1", reason="target")],
        evidence_anchors=[
            EvidenceAnchor(paper_id="p1", text="deep residual learning framework"),
        ],
    )

    result = _score_query(
        query,
        [
            _result(
                "p1",
                chunk_id=7,
                text="The paper proposes shortcut connections for very deep networks.",
            ),
        ],
        anchor_matcher=lambda anchor, chunk: (
            anchor.paper_id == chunk.paper_id and chunk.chunk_id == 7
        ),
    )

    assert result.evidence_recall_at_5 == pytest.approx(1.0)
    assert result.evidence_anchor_precision_at_5 == pytest.approx(1.0)
    assert result.missed_evidence_at_10 == ()


def test_score_query_computes_paper_precision() -> None:
    query = RetrievalQuery(
        id="q1",
        query="residual learning",
        intent="exact_method_lookup",
        relevant_papers=[
            RelevantPaper(paper_id="p1", reason="target"),
            RelevantPaper(paper_id="p2", reason="target"),
        ],
    )

    result = _score_query(
        query,
        [
            _result("p1", chunk_id=7, text="target"),
            _result("p3", chunk_id=8, text="distractor"),
        ],
    )

    assert result.recall_at_5 == pytest.approx(0.5)
    assert result.precision_at_5 == pytest.approx(0.5)


def test_score_query_keeps_evidence_recall_empty_without_anchors() -> None:
    query = RetrievalQuery(
        id="q1",
        query="residual learning",
        intent="exact_method_lookup",
        relevant_papers=[RelevantPaper(paper_id="p1", reason="target")],
    )

    result = _score_query(query, [_result("p1", chunk_id=7, text="any text")])

    assert result.evidence_anchor_count == 0
    assert result.evidence_recall_at_5 is None
    assert result.evidence_recall_at_10 is None
    assert result.evidence_anchor_precision_at_5 is None
    assert result.evidence_anchor_precision_at_10 is None
    assert result.missed_evidence_at_10 == ()
