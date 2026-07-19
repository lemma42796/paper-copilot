from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from paper_copilot.eval.assertions import FieldFailure
from paper_copilot.eval.retrieval import (
    RetrievalEvalResult,
    RetrievalHit,
    RetrievalQueryResult,
)
from paper_copilot.eval.runs import (
    RunRow,
    _cache_hit_ratio,
    load_history,
    make_run_id,
    write_research_quality_run,
    write_retrieval_run,
    write_run,
)
from paper_copilot.eval.suite import FieldResult, PaperResult, SuiteResult
from paper_copilot.session import SessionStore
from paper_copilot.shared.cost import CostSnapshot
from paper_copilot.shared.errors import EvalError


def _paper(
    paper_id: str,
    *,
    cost_cny: float = 0.05,
    input_tokens: int = 10000,
    cache_read: int = 1500,
    cache_create: int = 1500,
    fields: tuple[FieldResult, ...] = (),
    budget_failures: tuple[FieldFailure, ...] = (),
) -> PaperResult:
    cost = CostSnapshot(
        input_tokens=input_tokens,
        output_tokens=2000,
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_create,
        cost_cny=cost_cny,
    )
    return PaperResult(
        paper_id=paper_id,
        pdf=Path(f"/tmp/{paper_id}.pdf"),
        cost=cost,
        latency_s=12.5,
        fields=fields,
        budget_failures=budget_failures,
    )


def test_cache_hit_ratio_disjoint_accounting() -> None:
    # 2000 cached / (8000 + 2000 + 1000) = 2000 / 11000
    assert _cache_hit_ratio(8000, 2000, 1000) == pytest.approx(2000 / 11000)


def test_cache_hit_ratio_zero_division_safe() -> None:
    assert _cache_hit_ratio(0, 0, 0) == 0.0


def test_make_run_id_is_filename_safe() -> None:
    rid = make_run_id(datetime(2026, 4, 27, 15, 30, 45, tzinfo=UTC))
    assert rid == "2026-04-27T15-30-45Z"
    assert ":" not in rid  # so it stays a valid filename on every fs


def test_write_run_emits_one_row_per_field(tmp_path: Path) -> None:
    fields_a = (
        FieldResult(paper_id="aaa", field="methods", failures=tuple()),
        FieldResult(paper_id="aaa", field="contributions", failures=tuple()),
    )
    fields_b = (
        FieldResult(
            paper_id="bbb",
            field="methods",
            failures=(FieldFailure(field="methods", kind="len_short", detail="x"),),
        ),
        FieldResult(paper_id="bbb", field="contributions", failures=tuple()),
    )
    result = SuiteResult(
        suite_name="smoke",
        papers=(_paper("aaa", fields=fields_a), _paper("bbb", fields=fields_b)),
    )
    path = write_run(result, runs_dir=tmp_path, run_id="run1", git_sha="cafe")

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 4

    parsed = [json.loads(line) for line in lines]
    assert {(r["paper_id"], r["field"]) for r in parsed} == {
        ("aaa", "methods"),
        ("aaa", "contributions"),
        ("bbb", "methods"),
        ("bbb", "contributions"),
    }
    bbb_methods = next(r for r in parsed if r["paper_id"] == "bbb" and r["field"] == "methods")
    assert bbb_methods["field_passed"] is False
    assert bbb_methods["field_n_failures"] == 1
    assert bbb_methods["budget_passed"] is True
    assert bbb_methods["git_sha"] == "cafe"
    assert bbb_methods["run_id"] == "run1"


def _trivial_result(suite_name: str = "smoke") -> SuiteResult:
    fr = FieldResult(paper_id="aaa", field="methods", failures=())
    return SuiteResult(
        suite_name=suite_name,
        papers=(_paper("aaa", fields=(fr,)),),
    )


def test_write_run_refuses_overwrite(tmp_path: Path) -> None:
    result = _trivial_result()
    write_run(result, runs_dir=tmp_path, run_id="dup", git_sha="x")
    with pytest.raises(EvalError, match="already exists"):
        write_run(result, runs_dir=tmp_path, run_id="dup", git_sha="x")


def test_load_history_chronological(tmp_path: Path) -> None:
    base = datetime(2026, 4, 27, 10, 0, 0, tzinfo=UTC)
    for i in range(3):
        rid = make_run_id(base + timedelta(hours=i))
        write_run(_trivial_result(), runs_dir=tmp_path, run_id=rid, git_sha=f"sha{i}")

    rows = load_history(runs_dir=tmp_path)
    assert len(rows) == 3
    assert [r.git_sha for r in rows] == ["sha0", "sha1", "sha2"]


def test_load_history_filters_by_suite_then_truncates(tmp_path: Path) -> None:
    base = datetime(2026, 4, 27, 10, 0, 0, tzinfo=UTC)
    for i, suite in enumerate(["smoke", "deep", "smoke", "smoke"]):
        rid = make_run_id(base + timedelta(hours=i))
        write_run(_trivial_result(suite), runs_dir=tmp_path, run_id=rid, git_sha=f"sha{i}")

    # ``last`` must filter by suite *first* so we get the 2 most recent
    # smoke runs, not zero rows from the most-recent-2 files filtered to smoke.
    rows = load_history(runs_dir=tmp_path, suite_name="smoke", last=2)
    assert len(rows) == 2
    assert [r.git_sha for r in rows] == ["sha2", "sha3"]


def test_load_history_missing_dir_returns_empty(tmp_path: Path) -> None:
    assert load_history(runs_dir=tmp_path / "nope") == []


def test_run_row_roundtrip() -> None:
    row = RunRow(
        run_id="r1",
        suite_name="s",
        git_sha="g",
        paper_id="p",
        field="methods",
        field_passed=True,
        field_n_failures=0,
        cost_cny=0.05,
        latency_s=12.5,
        cache_hit_ratio=0.2,
        budget_passed=True,
        evidence_ref_count=3,
        findings_claim_count=4,
        findings_inline_ref_count=1,
        claims_without_refs_count=1,
        evidence_coverage_ratio=0.75,
        retrieval_query="residual connections",
        retrieval_relevant_count=2,
        retrieval_recall_at_5=0.5,
        retrieval_recall_at_10=1.0,
        retrieval_precision_at_5=0.5,
        retrieval_precision_at_10=0.2,
        retrieval_missed_at_5=("p2",),
        retrieval_missed_at_10=(),
        retrieval_top_papers=("p1", "p2"),
        retrieval_evidence_anchor_count=2,
        retrieval_evidence_recall_at_5=0.5,
        retrieval_evidence_recall_at_10=1.0,
        retrieval_evidence_anchor_precision_at_5=0.25,
        retrieval_evidence_anchor_precision_at_10=0.2,
        retrieval_missed_evidence_at_5=("p2:anchor",),
        retrieval_missed_evidence_at_10=(),
    )
    assert RunRow.from_json(row.to_json()) == row


def test_run_row_reads_legacy_json_without_quality_fields() -> None:
    row = RunRow.from_json(
        {
            "run_id": "r1",
            "suite_name": "s",
            "git_sha": "g",
            "paper_id": "p",
            "field": "methods",
            "field_passed": True,
            "field_n_failures": 0,
            "cost_cny": 0.05,
            "latency_s": 12.5,
            "cache_hit_ratio": 0.2,
            "budget_passed": True,
        }
    )

    assert row.evidence_ref_count is None
    assert row.evidence_coverage_ratio is None
    assert row.retrieval_recall_at_10 is None
    assert row.retrieval_precision_at_10 is None
    assert row.retrieval_evidence_recall_at_10 is None


def test_write_research_quality_run_records_final_output_quality(tmp_path: Path) -> None:
    store = SessionStore.create(
        "research-session",
        model="qwen",
        agent="PaperCopilot",
        root=tmp_path,
    )
    store.append_final_output(
        {
            "quality": {
                "evidence_ref_count": 2,
                "findings_claim_count": 4,
                "findings_inline_ref_count": 1,
                "claims_without_refs_count": 1,
                "evidence_coverage_ratio": 0.5,
            },
            "cost": {
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_read_tokens": 30,
                "cache_creation_tokens": 10,
                "cost_cny": 0.0123,
            },
        }
    )

    path = write_research_quality_run(
        store.path,
        runs_dir=tmp_path / "runs",
        run_id="research1",
        git_sha="sha",
    )

    row = RunRow.from_json(json.loads(path.read_text(encoding="utf-8")))
    assert row.run_id == "research1"
    assert row.suite_name == "research"
    assert row.paper_id == "research"
    assert row.field == "research_quality"
    assert row.field_passed is False
    assert row.field_n_failures == 1
    assert row.cost_cny == 0.0123
    assert row.cache_hit_ratio == pytest.approx(30 / 140)
    assert row.evidence_ref_count == 2
    assert row.findings_claim_count == 4
    assert row.findings_inline_ref_count == 1
    assert row.claims_without_refs_count == 1
    assert row.evidence_coverage_ratio == 0.5


def test_write_retrieval_run_records_one_row_per_query(tmp_path: Path) -> None:
    result = RetrievalEvalResult(
        suite_name="retrieval_seed",
        queries=(
            RetrievalQueryResult(
                query_id="q1",
                query="residual connections",
                relevant_papers=("p1", "p2"),
                hits=(
                    RetrievalHit(
                        rank=1,
                        paper_id="p1",
                        title="paper 1",
                        year=2016,
                        best_chunk_id=3,
                        rrf_score=0.5,
                        vector_rank=1,
                        bm25_rank=None,
                    ),
                    RetrievalHit(
                        rank=8,
                        paper_id="p2",
                        title="paper 2",
                        year=2017,
                        best_chunk_id=4,
                        rrf_score=0.2,
                        vector_rank=None,
                        bm25_rank=2,
                    ),
                ),
                recall_at_5=0.5,
                recall_at_10=1.0,
                precision_at_5=0.5,
                precision_at_10=0.2,
                missed_at_5=("p2",),
                missed_at_10=(),
                evidence_anchor_count=2,
                evidence_recall_at_5=0.5,
                evidence_recall_at_10=1.0,
                evidence_anchor_precision_at_5=0.25,
                evidence_anchor_precision_at_10=0.2,
                missed_evidence_at_5=("p2:anchor",),
                missed_evidence_at_10=(),
            ),
        ),
    )

    path = write_retrieval_run(result, runs_dir=tmp_path, run_id="retrieval1", git_sha="sha")

    row = RunRow.from_json(json.loads(path.read_text(encoding="utf-8")))
    assert row.run_id == "retrieval1"
    assert row.suite_name == "retrieval_seed"
    assert row.paper_id == "q1"
    assert row.field == "retrieval_recall"
    assert row.field_passed is True
    assert row.field_n_failures == 0
    assert row.retrieval_query == "residual connections"
    assert row.retrieval_relevant_count == 2
    assert row.retrieval_recall_at_5 == 0.5
    assert row.retrieval_recall_at_10 == 1.0
    assert row.retrieval_precision_at_5 == 0.5
    assert row.retrieval_precision_at_10 == 0.2
    assert row.retrieval_missed_at_5 == ("p2",)
    assert row.retrieval_missed_at_10 == ()
    assert row.retrieval_top_papers == ("p1", "p2")
    assert row.retrieval_evidence_anchor_count == 2
    assert row.retrieval_evidence_recall_at_5 == 0.5
    assert row.retrieval_evidence_recall_at_10 == 1.0
    assert row.retrieval_evidence_anchor_precision_at_5 == 0.25
    assert row.retrieval_evidence_anchor_precision_at_10 == 0.2
    assert row.retrieval_missed_evidence_at_5 == ("p2:anchor",)
    assert row.retrieval_missed_evidence_at_10 == ()
