from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from paper_copilot.knowledge.embeddings_store import (
    ChunkRow,
    EmbeddingsStore,
)
from paper_copilot.shared.errors import KnowledgeError

DIM = 4


def _row(paper_id: str, ord_: int, text: str = "t") -> ChunkRow:
    return ChunkRow(
        chunk_id=0,
        paper_id=paper_id,
        ord=ord_,
        section="Intro",
        page_start=1,
        page_end=1,
        text=text,
    )


def _vecs(*rows: list[float]) -> np.ndarray:
    return np.array(rows, dtype=np.float32)


def test_replace_and_count(tmp_path: Path) -> None:
    with EmbeddingsStore.open(tmp_path / "e.db", dim=DIM) as store:
        store.replace_paper(
            "pA",
            [_row("pA", 0, "intro chunk"), _row("pA", 1, "method chunk")],
            _vecs([1, 0, 0, 0], [0, 1, 0, 0]),
        )
        assert store.count_chunks() == 2
        assert store.count_papers() == 1


def test_replace_is_idempotent(tmp_path: Path) -> None:
    with EmbeddingsStore.open(tmp_path / "e.db", dim=DIM) as store:
        store.replace_paper("pA", [_row("pA", 0)], _vecs([1, 0, 0, 0]))
        store.replace_paper(
            "pA",
            [_row("pA", 0), _row("pA", 1)],
            _vecs([1, 0, 0, 0], [0, 1, 0, 0]),
        )
        assert store.count_chunks() == 2  # old row replaced, not appended


def test_delete_paper(tmp_path: Path) -> None:
    with EmbeddingsStore.open(tmp_path / "e.db", dim=DIM) as store:
        store.replace_paper("pA", [_row("pA", 0)], _vecs([1, 0, 0, 0]))
        store.replace_paper("pB", [_row("pB", 0)], _vecs([0, 1, 0, 0]))
        assert store.delete_paper("pA") == 1
        assert store.count_chunks() == 1
        assert store.count_papers() == 1


def test_knn_orders_by_distance(tmp_path: Path) -> None:
    with EmbeddingsStore.open(tmp_path / "e.db", dim=DIM) as store:
        store.replace_paper(
            "pA",
            [_row("pA", 0, "hit"), _row("pA", 1, "miss")],
            _vecs([1, 0, 0, 0], [0, 1, 0, 0]),
        )
        hits = store.knn(np.array([1, 0.01, 0, 0], dtype=np.float32), k=2)
        assert [h.text for h in hits] == ["hit", "miss"]
        assert hits[0].distance < hits[1].distance


def test_knn_filters_by_paper_ids(tmp_path: Path) -> None:
    with EmbeddingsStore.open(tmp_path / "e.db", dim=DIM) as store:
        store.replace_paper("pA", [_row("pA", 0, "A")], _vecs([1, 0, 0, 0]))
        store.replace_paper("pB", [_row("pB", 0, "B")], _vecs([1, 0, 0, 0]))
        hits = store.knn(
            np.array([1, 0, 0, 0], dtype=np.float32), k=5, paper_ids=["pB"]
        )
        assert [h.paper_id for h in hits] == ["pB"]


def test_empty_paper_ids_returns_empty(tmp_path: Path) -> None:
    with EmbeddingsStore.open(tmp_path / "e.db", dim=DIM) as store:
        store.replace_paper("pA", [_row("pA", 0)], _vecs([1, 0, 0, 0]))
        assert store.knn(np.array([1, 0, 0, 0], dtype=np.float32), k=5, paper_ids=[]) == []


def test_dim_mismatch_raises(tmp_path: Path) -> None:
    with EmbeddingsStore.open(tmp_path / "e.db", dim=DIM) as store:
        with pytest.raises(KnowledgeError):
            store.replace_paper("pA", [_row("pA", 0)], np.zeros((1, DIM + 1), dtype=np.float32))
        with pytest.raises(KnowledgeError):
            store.knn(np.zeros(DIM + 1, dtype=np.float32), k=1)


def test_rows_count_mismatch_raises(tmp_path: Path) -> None:
    with (
        EmbeddingsStore.open(tmp_path / "e.db", dim=DIM) as store,
        pytest.raises(KnowledgeError),
    ):
        store.replace_paper(
            "pA", [_row("pA", 0), _row("pA", 1)], np.zeros((1, DIM), dtype=np.float32)
        )
