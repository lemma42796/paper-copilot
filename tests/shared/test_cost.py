import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from paper_copilot.shared.cost import (
    CostTracker,
    QwenFlashPricing,
    QwenPlusPricing,
    pricing_for_model,
)
from paper_copilot.shared.logging import configure_logging


def test_record_object_usage() -> None:
    tracker = CostTracker()
    tracker.record(SimpleNamespace(input_tokens=1000, output_tokens=500))
    assert tracker.total_input_tokens == 1000
    assert tracker.total_output_tokens == 500
    assert tracker.total_cache_read_tokens == 0
    assert tracker.total_cache_creation_tokens == 0


def test_record_dict_usage() -> None:
    tracker = CostTracker()
    tracker.record({"input_tokens": 2000, "output_tokens": 100})
    assert tracker.total_input_tokens == 2000
    assert tracker.total_output_tokens == 100
    assert tracker.total_cache_read_tokens == 0
    assert tracker.total_cache_creation_tokens == 0


def test_record_with_cache_fields() -> None:
    tracker = CostTracker()
    tracker.record(
        {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_input_tokens": 200,
            "cache_read_input_tokens": 300,
        }
    )
    assert tracker.total_cache_creation_tokens == 200
    assert tracker.total_cache_read_tokens == 300


def test_none_cache_fields_treated_as_zero() -> None:
    tracker = CostTracker()
    tracker.record(
        SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            cache_creation_input_tokens=None,
            cache_read_input_tokens=None,
        )
    )
    assert tracker.total_cache_creation_tokens == 0
    assert tracker.total_cache_read_tokens == 0


def test_cost_calculation_known_values() -> None:
    tracker = CostTracker()
    tracker.record(
        {
            "input_tokens": 1_000_000,
            "output_tokens": 1_000_000,
            "cache_creation_input_tokens": 1_000_000,
            "cache_read_input_tokens": 1_000_000,
        }
    )
    # 1.2 (input) + 7.2 (output) + 1.5 (cache-create) + 0.12 (cache-hit) = 10.02 CNY
    assert tracker.total_cost_cny == pytest.approx(10.02)


def test_plus_pricing_known_values() -> None:
    tracker = CostTracker(pricing=QwenPlusPricing())
    tracker.record(
        {
            "input_tokens": 1_000_000,
            "output_tokens": 1_000_000,
            "cache_creation_input_tokens": 1_000_000,
            "cache_read_input_tokens": 1_000_000,
        }
    )
    # 2.0 (input) + 12.0 (output) + 2.5 (cache-create) + 0.2 (cache-hit) = 16.7 CNY
    assert tracker.total_cost_cny == pytest.approx(16.7)


def test_pricing_for_model_routing() -> None:
    assert isinstance(pricing_for_model("qwen3.6-flash"), QwenFlashPricing)
    assert isinstance(pricing_for_model("qwen3.6-plus"), QwenPlusPricing)
    assert isinstance(pricing_for_model("qwen3.6-plus-2026-04-02"), QwenPlusPricing)
    with pytest.raises(ValueError, match="no pricing registered"):
        pricing_for_model("gpt-4o")


def test_context_manager_logs_summary(tmp_path: Path) -> None:
    configure_logging(log_dir=tmp_path, console=False)
    with CostTracker() as t:
        t.record({"input_tokens": 10, "output_tokens": 5})

    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    entries = [json.loads(line) for line in files[0].read_text().splitlines() if line]
    summary = [e for e in entries if e.get("event") == "cost.summary"]
    assert len(summary) == 1
    assert summary[0]["input_tokens"] == 10
    assert summary[0]["output_tokens"] == 5


def test_snapshot_is_frozen() -> None:
    tracker = CostTracker()
    tracker.record({"input_tokens": 1, "output_tokens": 1})
    snap = tracker.snapshot()
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.input_tokens = 99  # type: ignore[misc]
