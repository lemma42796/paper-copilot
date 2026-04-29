from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from paper_copilot.knowledge.embeddings_store import ChunkRow, EmbeddingsStore
from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.knowledge.hybrid_search import ContainsFilter, search

DIM = 4


def _payload(title: str, year: int, method_name: str = "baseline") -> dict[str, Any]:
    return {
        "meta": {
            "title": title,
            "authors": ["A"],
            "arxiv_id": None,
            "year": year,
            "venue": None,
        },
        "contributions": [
            {"claim": "c", "type": "novel_method", "evidence_type": "explicit_claim"}
        ],
        "methods": [
            {
                "name": method_name,
                "description": "desc",
                "key_formula": None,
                "novelty_vs_prior": "n",
                "is_novel_to_this_paper": True,
            }
        ],
        "experiments": [],
        "limitations": [],
        "cross_paper_links": [],
    }


@pytest.fixture
def stores(tmp_path: Path):
    with (
        FieldsStore.open(tmp_path / "f.db") as fs,
        EmbeddingsStore.open(tmp_path / "e.db", dim=DIM) as es,
    ):
        now = datetime.now(UTC).isoformat()
        fs.upsert("pA", _payload("Paper A (2024)", 2024, "contrastive"), now)
        fs.upsert("pB", _payload("Paper B (2020)", 2020, "baseline"), now)

        def _row(pid: str, ord_: int, text: str) -> ChunkRow:
            return ChunkRow(
                chunk_id=0,
                paper_id=pid,
                ord=ord_,
                section="Intro",
                page_start=1,
                page_end=1,
                text=text,
            )

        es.replace_paper(
            "pA",
            [_row("pA", 0, "contrastive loss"), _row("pA", 1, "off-topic noise")],
            np.array([[1, 0, 0, 0], [0, 0, 1, 0]], dtype=np.float32),
        )
        es.replace_paper(
            "pB",
            [_row("pB", 0, "baseline softmax")],
            np.array([[0, 1, 0, 0]], dtype=np.float32),
        )
        yield fs, es


def test_search_returns_one_per_paper(stores) -> None:
    fs, es = stores
    results = search(
        np.array([1, 0.1, 0, 0], dtype=np.float32),
        fields_store=fs,
        embeddings_store=es,
        k=5,
    )
    paper_ids = [r.paper_id for r in results]
    assert paper_ids.count("pA") == 1
    assert paper_ids[0] == "pA"  # closest to query


def test_search_picks_best_chunk_per_paper(stores) -> None:
    fs, es = stores
    results = search(
        np.array([1, 0.1, 0, 0], dtype=np.float32),
        fields_store=fs,
        embeddings_store=es,
        k=5,
    )
    hit = next(r for r in results if r.paper_id == "pA")
    assert hit.best_chunk.text == "contrastive loss"  # not the noise chunk


def test_year_filter_narrows_candidates(stores) -> None:
    fs, es = stores
    results = search(
        np.array([1, 0, 0, 0], dtype=np.float32),
        fields_store=fs,
        embeddings_store=es,
        k=5,
        year=2020,
    )
    assert [r.paper_id for r in results] == ["pB"]


def test_contains_filter_narrows_candidates(stores) -> None:
    fs, es = stores
    results = search(
        np.array([0, 1, 0, 0], dtype=np.float32),  # closer to pB's chunk
        fields_store=fs,
        embeddings_store=es,
        k=5,
        contains=ContainsFilter("method", "contrastive"),
    )
    assert [r.paper_id for r in results] == ["pA"]


def test_empty_candidate_set_returns_empty(stores) -> None:
    fs, es = stores
    results = search(
        np.array([1, 0, 0, 0], dtype=np.float32),
        fields_store=fs,
        embeddings_store=es,
        k=5,
        year=1999,
    )
    assert results == []


def test_returned_metadata_is_populated(stores) -> None:
    fs, es = stores
    results = search(
        np.array([1, 0, 0, 0], dtype=np.float32),
        fields_store=fs,
        embeddings_store=es,
        k=1,
    )
    assert results[0].title == "Paper A (2024)"
    assert results[0].year == 2024


def test_search_escalates_pool_when_top_chunks_cluster(tmp_path: Path) -> None:
    # pA owns the 5 nearest chunks; pB and pC each have one chunk
    # that's farther but still relevant. With k=3, overfetch=1 the
    # initial pool of 3 is all-pA — escalation must re-pull at the
    # full ceiling so pB and pC surface.
    with (
        FieldsStore.open(tmp_path / "f.db") as fs,
        EmbeddingsStore.open(tmp_path / "e.db", dim=DIM) as es,
    ):
        now = datetime.now(UTC).isoformat()
        fs.upsert("pA", _payload("Paper A", 2024), now)
        fs.upsert("pB", _payload("Paper B", 2024), now)
        fs.upsert("pC", _payload("Paper C", 2024), now)

        def _row(pid: str, ord_: int) -> ChunkRow:
            return ChunkRow(
                chunk_id=0, paper_id=pid, ord=ord_, section="Intro",
                page_start=1, page_end=1, text=f"{pid}-{ord_}",
            )

        # pA: 5 chunks tightly hugging the query axis (all very near).
        es.replace_paper(
            "pA",
            [_row("pA", i) for i in range(5)],
            np.array(
                [[1, 0.01 * i, 0, 0] for i in range(5)],
                dtype=np.float32,
            ),
        )
        # pB and pC each have a single chunk farther away.
        es.replace_paper(
            "pB", [_row("pB", 0)],
            np.array([[1, 0.5, 0, 0]], dtype=np.float32),
        )
        es.replace_paper(
            "pC", [_row("pC", 0)],
            np.array([[1, 0.6, 0, 0]], dtype=np.float32),
        )

        results = search(
            np.array([1, 0, 0, 0], dtype=np.float32),
            fields_store=fs,
            embeddings_store=es,
            k=3,
            overfetch=1,
        )

    assert {r.paper_id for r in results} == {"pA", "pB", "pC"}
    assert results[0].paper_id == "pA"  # closest still ranks first
