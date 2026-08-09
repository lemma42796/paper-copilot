"""Advisory formula hints and the model-facing Formula OCR contract."""

from __future__ import annotations

import pytest

from paper_copilot.agents.formula_ocr_tool import FormulaOCRInput
from paper_copilot.shared.pdf_cache import (
    _FormulaHint,
    _contains_extraction_garble,
    _formula_aware_text,
    _line_has_prose,
    _render_text_page,
    _repair_span_count,
)

_GARBLE = "\uf8eb"
_PAPER_ID = "90137160c572"


def _hint() -> _FormulaHint:
    return _FormulaHint(
        start_bbox=(0.33, 0.21, 0.35, 0.23),
        end_bbox=(0.65, 0.26, 0.67, 0.28),
        line_count=2,
    )


def test_render_text_page_preembeds_advisory_endpoints() -> None:
    rendered = _render_text_page(f"{_GARBLE}\n{_GARBLE}\n正文\n", 4, (_hint(),))
    assert "paper-copilot-formula:hint" in rendered
    assert "start_bbox=0.3300,0.2100,0.3500,0.2300" in rendered
    assert "end_bbox=0.6500,0.2600,0.6700,0.2800" in rendered
    assert "line_count=2 advisory=true" in rendered


def test_mixed_damaged_prose_line_is_not_hint_eligible() -> None:
    assert _contains_extraction_garble(f"正文 {_GARBLE}")
    assert _line_has_prose(f"正文 {_GARBLE}")
    assert _line_has_prose(f"broken word {_GARBLE}")
    assert not _line_has_prose(f"x + y {_GARBLE}")
    rendered = _render_text_page(f"正文 {_GARBLE}\n", 4)
    assert "repair_span_id" not in rendered


def test_render_text_page_marks_damage_without_a_replacement_identifier() -> None:
    rendered = _render_text_page(f"x {_GARBLE}\ny {_GARBLE}\nclean line\n", 4, (_hint(),))
    assert rendered.count("paper-copilot-formula:damaged page=4") == 1
    assert "repair_span_id" not in rendered
    assert "paper-copilot-formula:damaged-end" in rendered


def test_repair_spans_bridge_short_clean_formula_rows() -> None:
    text = (
        f"{_GARBLE}\n"
        "i=1\n"
        "N\n"
        f"x {_GARBLE}\n"
        "prose after\n"
    )
    assert _repair_span_count(text) == 1
    rendered = _render_text_page(text, 4)
    assert rendered.count("paper-copilot-formula:damaged page=4") == 1
    assert "原始提取：i=1" in rendered  # noqa: RUF001


def test_repair_spans_stop_before_mixed_prose() -> None:
    text = f"x {_GARBLE}\n正文 {_GARBLE}\ny {_GARBLE}\n"
    rendered = _render_text_page(text, 4)
    assert rendered.count("paper-copilot-formula:damaged page=4") == 2
    assert "原始提取：正文" not in rendered  # noqa: RUF001


def test_formula_aware_text_carries_page_hints() -> None:
    raw_pages = b"clean page\n" + b"\f" + f"{_GARBLE}\n".encode()
    text_bytes, boundaries = _formula_aware_text(raw_pages, 2, {2: (_hint(),)})
    assert "page-0002-hint-0001" in text_bytes.decode("utf-8")
    assert len(boundaries) == 2


def _recognize(**overrides: object) -> FormulaOCRInput:
    payload: dict[str, object] = {
        "operation": "recognize",
        "paper_id": _PAPER_ID,
        "page": 4,
        "purpose": "explain equation (3.5)",
        "formula_ref": "equation (3.5)",
        "region": {"x1": 0.2, "y1": 0.2, "x2": 0.8, "y2": 0.3},
    }
    payload.update(overrides)
    return FormulaOCRInput.model_validate(payload)


def test_recognize_requires_model_selected_region_and_stable_ref() -> None:
    assert _recognize().region is not None
    with pytest.raises(ValueError, match="explicit region"):
        _recognize(region=None)
    with pytest.raises(ValueError, match="formula_ref"):
        _recognize(formula_ref=None)


def test_recognize_rejects_legacy_replacement_targets() -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        _recognize(replacement_text="x+y")


def test_accept_requires_candidate_id() -> None:
    with pytest.raises(ValueError, match="requires candidate_id"):
        FormulaOCRInput.model_validate(
            {"operation": "accept", "paper_id": _PAPER_ID, "page": 4}
        )
