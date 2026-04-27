from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from paper_copilot.eval.assertions import FieldFailure
from paper_copilot.eval.runs import (
    RunRow,
    _cache_hit_ratio,
    load_history,
    make_run_id,
    write_run,
)
from paper_copilot.eval.suite import FieldResult, PaperResult, SuiteResult
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
    )
    assert RunRow.from_json(row.to_json()) == row
