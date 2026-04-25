from __future__ import annotations

import pytest

from paper_copilot.eval.assertions import (
    FieldFailure,
    assert_budget,
    assert_contributions,
    assert_experiments,
    assert_field,
    assert_meta,
    assert_methods,
)
from paper_copilot.shared.errors import EvalError


def _meta(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "title": "Attention Is All You Need",
        "year": 2017,
        "arxiv_id": "1706.03762",
        "authors": ["A", "B", "C", "D", "E", "F", "G", "H"],
        "venue": "NeurIPS 2017",
    }
    base.update(overrides)
    return base


def _method(name: str, *, novel: bool = True) -> dict[str, object]:
    return {
        "name": name,
        "description": "...",
        "key_formula": None,
        "novelty_vs_prior": "...",
        "is_novel_to_this_paper": novel,
    }


def _contribution(type_: str = "novel_method") -> dict[str, object]:
    return {"claim": "...", "type": type_, "evidence_type": "explicit_claim"}


def _experiment(dataset: str, metric: str) -> dict[str, object]:
    return {
        "dataset": dataset,
        "metric": metric,
        "value": None,
        "unit": None,
        "raw": "...",
        "comparison_baseline": "none",
        "pages": [],
    }


# ---------- meta ----------


def test_meta_pass_on_identical() -> None:
    assert assert_meta(_meta(), _meta()) == []


def test_meta_year_drift_flagged() -> None:
    fails = assert_meta(_meta(), _meta(year=2018))
    assert len(fails) == 1
    assert fails[0].field == "meta.year"
    assert fails[0].kind == "value_mismatch"
    assert "2017" in fails[0].detail and "2018" in fails[0].detail


def test_meta_arxiv_id_none_vs_value_flagged() -> None:
    fails = assert_meta(_meta(), _meta(arxiv_id=None))
    assert len(fails) == 1
    assert fails[0].field == "meta.arxiv_id"


def test_meta_authors_length_mismatch_flagged() -> None:
    fails = assert_meta(_meta(), _meta(authors=["A", "B"]))
    assert len(fails) == 1
    assert fails[0].field == "meta.authors"
    assert "8" in fails[0].detail and "2" in fails[0].detail


# ---------- methods ----------


def test_methods_pass_on_superset() -> None:
    golden = [_method("Transformer")]
    output = [_method("Transformer"), _method("Multi-Head Attention")]
    assert assert_methods(golden, output) == []


def test_methods_naming_drift_silently_accepted() -> None:
    # LLM rephrases method names across runs — this is noise, not a
    # regression. M14 v1 chose to silently accept it.
    golden = [_method("Residual Learning Framework"), _method("Bottleneck Block")]
    output = [_method("Residual Block"), _method("Bottleneck Architecture")]
    assert assert_methods(golden, output) == []


def test_methods_novelty_flip_silently_accepted() -> None:
    # is_novel_to_this_paper also flips stochastically at the noise
    # floor; M14 v1 ignores it (M15 to revisit).
    golden = [_method("Transformer", novel=True)]
    output = [_method("Transformer", novel=False)]
    assert assert_methods(golden, output) == []


def test_methods_catastrophic_length_drop_flagged() -> None:
    golden = [_method(f"M{i}") for i in range(6)]
    output = [_method("M0"), _method("M1")]  # 2/6 < 50%
    fails = assert_methods(golden, output)
    assert len(fails) == 1
    assert fails[0].kind == "len_short"
    assert fails[0].field == "methods"


def test_methods_50pc_or_above_passes() -> None:
    golden = [_method(f"M{i}") for i in range(4)]
    output = [_method("M0"), _method("M1")]  # 2/4 = 50% -> pass
    assert assert_methods(golden, output) == []


# ---------- contributions ----------


def test_contributions_pass_on_equal_count() -> None:
    golden = [_contribution("novel_method"), _contribution("novel_result")]
    output = [_contribution("novel_method"), _contribution("novel_result")]
    assert assert_contributions(golden, output) == []


def test_contributions_type_drift_silently_accepted() -> None:
    # LLM picks `type` differently across reruns; this is noise.
    golden = [_contribution("novel_method"), _contribution("novel_result")]
    output = [_contribution("novel_method"), _contribution("analysis")]
    assert assert_contributions(golden, output) == []


def test_contributions_catastrophic_length_drop_flagged() -> None:
    golden = [_contribution() for _ in range(5)]
    output = [_contribution()]  # 1/5 < 50%
    fails = assert_contributions(golden, output)
    assert len(fails) == 1
    assert fails[0].kind == "len_short"
    assert fails[0].field == "contributions"


def test_contributions_50pc_or_above_passes() -> None:
    golden = [_contribution() for _ in range(4)]
    output = [_contribution(), _contribution()]  # 2/4 = 50%
    assert assert_contributions(golden, output) == []


# ---------- experiments ----------


def test_experiments_pass_when_all_golden_present() -> None:
    golden = [_experiment("ImageNet", "top-1 accuracy")]
    output = [
        _experiment("ImageNet", "top-1 accuracy"),
        _experiment("CIFAR-10", "top-1 accuracy"),
    ]
    assert assert_experiments(golden, output) == []


def test_experiments_missing_dataset_metric_flagged() -> None:
    golden = [
        _experiment("ImageNet", "top-1 accuracy"),
        _experiment("CIFAR-100", "top-5 accuracy"),
    ]
    output = [_experiment("ImageNet", "top-1 accuracy")]
    fails = assert_experiments(golden, output)
    assert len(fails) == 1
    assert "CIFAR-100" in fails[0].field and "top-5 accuracy" in fails[0].field


def test_experiments_match_case_insensitive() -> None:
    golden = [_experiment("ImageNet", "top-1 accuracy")]
    output = [_experiment("imagenet", "Top-1 Accuracy")]
    assert assert_experiments(golden, output) == []


# ---------- budget ----------


def test_budget_pass_within_factor() -> None:
    fails = assert_budget(
        golden_cost_cny=0.10,
        output_cost_cny=0.14,
        golden_latency_s=10.0,
        output_latency_s=12.0,
    )
    assert fails == []


def test_budget_cost_exceeded_flagged() -> None:
    fails = assert_budget(
        golden_cost_cny=0.10,
        output_cost_cny=0.20,
        golden_latency_s=10.0,
        output_latency_s=10.0,
    )
    assert len(fails) == 1
    assert fails[0].field == "budget.cost_cny"
    assert fails[0].kind == "budget_exceeded"


def test_budget_latency_exceeded_flagged() -> None:
    fails = assert_budget(
        golden_cost_cny=0.10,
        output_cost_cny=0.10,
        golden_latency_s=10.0,
        output_latency_s=20.0,
    )
    assert len(fails) == 1
    assert fails[0].field == "budget.latency_s"


# ---------- dispatch ----------


def test_assert_field_dispatches_to_meta() -> None:
    fails = assert_field("meta", _meta(), _meta(year=2018))
    assert len(fails) == 1
    assert fails[0].field == "meta.year"


def test_assert_field_unknown_raises() -> None:
    with pytest.raises(EvalError, match="no assertion registered"):
        assert_field("limitations", [], [])


def test_field_failure_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    f = FieldFailure(field="x", kind="missing", detail="y")
    with pytest.raises(FrozenInstanceError):
        f.field = "z"  # type: ignore[misc]
