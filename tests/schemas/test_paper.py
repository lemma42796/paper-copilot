from typing import Any

import pytest
from pydantic import ValidationError

from paper_copilot.schemas import (
    Contribution,
    Paper,
    PaperMeta,
)


def _valid_contribution() -> dict[str, Any]:
    return {
        "claim": "introduces tiled attention with softmax recomputation",
        "type": "novel_method",
        "confidence": 0.9,
    }


def _valid_paper_dict() -> dict[str, Any]:
    return {
        "meta": {
            "id": "2205.14135",
            "title": "FlashAttention: Fast and Memory-Efficient Exact Attention",
            "authors": ["Tri Dao", "Daniel Y. Fu"],
            "arxiv_id": "2205.14135",
            "year": 2022,
            "venue": "NeurIPS 2022",
        },
        "contributions": [_valid_contribution()],
        "methods": [
            {
                "name": "FlashAttention",
                "description": (
                    "Tiles Q, K, V into blocks that fit in SRAM and recomputes "
                    "softmax normalization per block, avoiding materializing the "
                    "N x N attention matrix in HBM."
                ),
                "key_formula": None,
                "novelty_vs_prior": (
                    "replaces the dense attention read/write pattern with an "
                    "IO-aware tiled schedule"
                ),
            }
        ],
        "experiments": [
            {
                "dataset": "GPT-2 training",
                "metric": "wall-clock speedup",
                "value": 3.0,
                "unit": "x",
                "raw": "~3x end-to-end training speedup at matched perplexity",
                "comparison_baseline": "vanilla PyTorch attention",
            }
        ],
        "limitations": [
            {
                "type": "method",
                "description": "GPU-specific CUDA kernel; no optimized CPU path.",
            }
        ],
    }


def test_paper_json_roundtrip() -> None:
    paper = Paper.model_validate(_valid_paper_dict())
    restored = Paper.model_validate_json(paper.model_dump_json())
    assert restored == paper
    assert restored.cross_paper_links == []


def test_extra_field_rejected() -> None:
    bad = _valid_contribution() | {"confidence_score": 0.9}
    with pytest.raises(ValidationError) as exc:
        Contribution.model_validate(bad)
    errors = exc.value.errors()
    assert any(
        e["type"] == "extra_forbidden" and e["loc"] == ("confidence_score",)
        for e in errors
    )


def test_missing_required_field_rejected() -> None:
    bad = {"claim": "some claim", "confidence": 0.5}
    with pytest.raises(ValidationError) as exc:
        Contribution.model_validate(bad)
    errors = exc.value.errors()
    assert any(e["type"] == "missing" and e["loc"] == ("type",) for e in errors)


def test_type_mismatch_rejected() -> None:
    bad = dict(_valid_paper_dict()["meta"]) | {"year": "two thousand twenty-two"}
    with pytest.raises(ValidationError) as exc:
        PaperMeta.model_validate(bad)
    assert any(e["loc"] == ("year",) for e in exc.value.errors())


def test_nested_validation_loc_points_to_index() -> None:
    data = _valid_paper_dict()
    data["contributions"] = [
        _valid_contribution(),
        {"claim": "second claim", "confidence": 0.4},  # missing `type`
    ]
    with pytest.raises(ValidationError) as exc:
        Paper.model_validate(data)
    errors = exc.value.errors()
    assert any(
        e["loc"] == ("contributions", 1, "type") and e["type"] == "missing"
        for e in errors
    )


def test_empty_contributions_allowed() -> None:
    data = _valid_paper_dict()
    data["contributions"] = []
    paper = Paper.model_validate(data)
    assert paper.contributions == []


def test_confidence_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        Contribution.model_validate(
            {"claim": "x", "type": "novel_method", "confidence": 1.5}
        )
    with pytest.raises(ValidationError):
        Contribution.model_validate(
            {"claim": "x", "type": "novel_method", "confidence": -0.1}
        )


def test_year_out_of_range_rejected() -> None:
    base = _valid_paper_dict()["meta"]
    with pytest.raises(ValidationError):
        PaperMeta.model_validate(dict(base) | {"year": 20230})
    with pytest.raises(ValidationError):
        PaperMeta.model_validate(dict(base) | {"year": 1800})
