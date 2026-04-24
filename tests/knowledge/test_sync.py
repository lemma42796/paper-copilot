from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.knowledge.sync import index_paper
from paper_copilot.schemas import Paper


def _paper_dict() -> dict[str, Any]:
    return {
        "meta": {
            "title": "FlashAttention",
            "authors": ["Tri Dao"],
            "arxiv_id": "2205.14135",
            "year": 2022,
            "venue": "NeurIPS 2022",
        },
        "contributions": [
            {
                "claim": "tiled softmax avoids materializing the attention matrix",
                "type": "novel_method",
                "evidence_type": "explicit_claim",
            }
        ],
        "methods": [
            {
                "name": "FlashAttention",
                "description": "blocks Q/K/V into SRAM, recomputes softmax per block",
                "key_formula": None,
                "novelty_vs_prior": "moves softmax normalization to block-level",
                "is_novel_to_this_paper": True,
            }
        ],
        "experiments": [],
        "limitations": [],
        "cross_paper_links": [],
    }


@pytest.fixture
def store(tmp_path: Path):
    s = FieldsStore.open(tmp_path / "fields.db")
    yield s
    s.close()


def test_index_paper_from_model(store: FieldsStore) -> None:
    paper = Paper.model_validate(_paper_dict())
    index_paper(paper, "pid1", store, indexed_at="t1")

    row = store.get("pid1")
    assert row is not None
    assert row.indexed_at == "t1"
    assert row.data["meta"]["title"] == "FlashAttention"


def test_index_paper_from_dict(store: FieldsStore) -> None:
    index_paper(_paper_dict(), "pid1", store, indexed_at="t1")
    assert [r.paper_id for r in store.query_contains("method", "flash")] == ["pid1"]


def test_index_paper_roundtrip_query(store: FieldsStore) -> None:
    index_paper(_paper_dict(), "pid1", store)
    hits = store.query_contains("contribution", "tiled softmax")
    assert [r.paper_id for r in hits] == ["pid1"]


def test_index_paper_updates_on_reindex(store: FieldsStore) -> None:
    d1 = _paper_dict()
    index_paper(d1, "pid1", store, indexed_at="t1")

    d2 = _paper_dict()
    d2["meta"]["title"] = "FlashAttention v2"
    index_paper(d2, "pid1", store, indexed_at="t2")

    row = store.get("pid1")
    assert row is not None
    assert row.data["meta"]["title"] == "FlashAttention v2"
    assert row.indexed_at == "t2"
    assert store.count() == 1
