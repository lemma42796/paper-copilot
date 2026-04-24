from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.shared.errors import KnowledgeError


def _payload(
    *,
    title: str,
    year: int,
    method_name: str = "Baseline",
    method_desc: str = "vanilla transformer",
    contribution: str = "generic claim",
    limitation: str = "",
) -> dict[str, Any]:
    return {
        "meta": {
            "title": title,
            "authors": ["A. Author"],
            "arxiv_id": None,
            "year": year,
            "venue": None,
        },
        "contributions": [
            {"claim": contribution, "type": "novel_method", "evidence_type": "explicit_claim"}
        ],
        "methods": [
            {
                "name": method_name,
                "description": method_desc,
                "key_formula": None,
                "novelty_vs_prior": "differs from baseline",
                "is_novel_to_this_paper": True,
            }
        ],
        "experiments": [
            {
                "dataset": "ImageNet",
                "metric": "top-1",
                "value": 80.0,
                "unit": "%",
                "raw": "80% top-1 on ImageNet",
                "comparison_baseline": "ResNet-50",
                "pages": [5],
            }
        ],
        "limitations": (
            [{"type": "scope", "description": limitation}] if limitation else []
        ),
        "cross_paper_links": [],
    }


@pytest.fixture
def store(tmp_path: Path):
    s = FieldsStore.open(tmp_path / "fields.db")
    yield s
    s.close()


def test_upsert_and_get(store: FieldsStore) -> None:
    store.upsert("pid1", _payload(title="Paper A", year=2023), "2026-04-24T00:00:00+00:00")
    row = store.get("pid1")
    assert row is not None
    assert row.paper_id == "pid1"
    assert row.data["meta"]["title"] == "Paper A"


def test_upsert_is_idempotent(store: FieldsStore) -> None:
    store.upsert("pid1", _payload(title="first", year=2023), "t1")
    store.upsert("pid1", _payload(title="second", year=2023), "t2")
    assert store.count() == 1
    row = store.get("pid1")
    assert row is not None
    assert row.data["meta"]["title"] == "second"
    assert row.indexed_at == "t2"


def test_list_all_sorted_by_year_desc(store: FieldsStore) -> None:
    store.upsert("old", _payload(title="old", year=2015), "t")
    store.upsert("new", _payload(title="new", year=2023), "t")
    store.upsert("mid", _payload(title="mid", year=2019), "t")
    ids = [r.paper_id for r in store.list_all()]
    assert ids == ["new", "mid", "old"]


def test_list_all_year_filter(store: FieldsStore) -> None:
    store.upsert("a", _payload(title="a", year=2023), "t")
    store.upsert("b", _payload(title="b", year=2022), "t")
    store.upsert("c", _payload(title="c", year=2023), "t")
    rows = store.list_all(year=2023)
    assert sorted(r.paper_id for r in rows) == ["a", "c"]


def test_query_contains_method_name_case_insensitive(store: FieldsStore) -> None:
    store.upsert(
        "flash",
        _payload(title="f", year=2023, method_name="FlashAttention", method_desc="tiling"),
        "t",
    )
    store.upsert(
        "other",
        _payload(title="o", year=2023, method_name="BaselineMLP", method_desc="dense"),
        "t",
    )
    assert [r.paper_id for r in store.query_contains("method", "flash")] == ["flash"]
    assert [r.paper_id for r in store.query_contains("method", "FLASH")] == ["flash"]


def test_query_contains_method_description_hit(store: FieldsStore) -> None:
    store.upsert(
        "p1",
        _payload(
            title="p1", year=2023, method_name="Foo", method_desc="uses contrastive loss"
        ),
        "t",
    )
    store.upsert("p2", _payload(title="p2", year=2023, method_name="Bar"), "t")
    assert [r.paper_id for r in store.query_contains("method", "contrastive")] == ["p1"]


def test_query_contains_contribution(store: FieldsStore) -> None:
    store.upsert(
        "p1",
        _payload(title="p1", year=2023, contribution="novel sparse attention"),
        "t",
    )
    store.upsert(
        "p2",
        _payload(title="p2", year=2023, contribution="scaling laws study"),
        "t",
    )
    assert [r.paper_id for r in store.query_contains("contribution", "sparse")] == ["p1"]


def test_query_contains_limitation(store: FieldsStore) -> None:
    store.upsert(
        "p1",
        _payload(title="p1", year=2023, limitation="single seed evaluation"),
        "t",
    )
    store.upsert("p2", _payload(title="p2", year=2023), "t")
    rows = store.query_contains("limitation", "single seed")
    assert [r.paper_id for r in rows] == ["p1"]


def test_query_contains_year_filter(store: FieldsStore) -> None:
    store.upsert(
        "old",
        _payload(title="old", year=2015, method_name="Foo", method_desc="contrastive"),
        "t",
    )
    store.upsert(
        "new",
        _payload(title="new", year=2023, method_name="Foo", method_desc="contrastive"),
        "t",
    )
    rows = store.query_contains("method", "contrastive", year=2023)
    assert [r.paper_id for r in rows] == ["new"]


def test_query_contains_unknown_field(store: FieldsStore) -> None:
    with pytest.raises(KnowledgeError):
        store.query_contains("bogus", "x")


def test_query_contains_empty_term(store: FieldsStore) -> None:
    with pytest.raises(KnowledgeError):
        store.query_contains("method", "")


def test_query_contains_deduplicates_across_subfields(store: FieldsStore) -> None:
    # Paper where both name and description match — must appear once.
    store.upsert(
        "p1",
        _payload(
            title="p1", year=2023, method_name="contrastive-head", method_desc="contrastive loss"
        ),
        "t",
    )
    rows = store.query_contains("method", "contrastive")
    assert [r.paper_id for r in rows] == ["p1"]


def test_year_filter_uses_integer_comparison(store: FieldsStore) -> None:
    # Ensure CAST to INTEGER works even if JSON stores year as a number.
    store.upsert("a", _payload(title="a", year=2023), "t")
    store.upsert("b", _payload(title="b", year=2099), "t")
    assert [r.paper_id for r in store.list_all(year=2023)] == ["a"]
    assert [r.paper_id for r in store.list_all(year=2099)] == ["b"]
    assert store.list_all(year=1900) == []
