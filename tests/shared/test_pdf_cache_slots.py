"""Slot bbox marker behavior for the formula-aware text cache."""

from __future__ import annotations

import pytest

from paper_copilot.agents.formula_ocr_tool import FormulaOCRInput
from paper_copilot.shared.pdf_cache import (
    _SLOT_BBOX_PATTERN,
    _contains_extraction_garble,
    _formula_aware_text,
    _garbled_line_bboxes,
    _ocr_start_marker,
    _render_text_page,
    _slot_block_count,
)

_GARBLE = "\uf8eb"
_PAPER_ID = "90137160c572"

_BBOX_PAGE_TEMPLATE = """<doc>
  <page width="612.000000" height="792.000000">
{words}
  </page>
</doc>
"""


def _word(x_min: float, y_min: float, x_max: float, y_max: float, text: str) -> str:
    return (
        f'    <word xMin="{x_min:.6f}" yMin="{y_min:.6f}" '
        f'xMax="{x_max:.6f}" yMax="{y_max:.6f}">{text}</word>\n'
    )


def _alexnet_like_page() -> str:
    """Two garbled delimiter halves, the formula body, and a limit row below."""
    words = [
        _word(108.0, 149.8, 504.0, 162.1, "prose line above the formula"),
        _word(262.2, 172.4, 271.0, 183.2, _GARBLE),
        _word(290.0, 174.0, 396.0, 181.0, "bix,y aix,y"),
        _word(211.0, 185.3, 396.0, 199.1, f"k \u03b1 ajx,y 2 {_GARBLE}"),
        # Summation lower limit: not garbled, inside the formula span, just below.
        _word(298.0, 202.7, 357.0, 208.9, "j=max(0,i-n/2)"),
        _word(108.0, 225.3, 504.0, 234.2, "prose line below the formula"),
    ]
    return _BBOX_PAGE_TEMPLATE.format(words="".join(words))


def test_garbled_line_bboxes_merges_clusters_and_absorbs_limits() -> None:
    result = _garbled_line_bboxes(_alexnet_like_page())
    assert result is not None
    boxes, garbled_cluster_count = result
    # Both garbled lines belong to one formula: one box for the whole group.
    assert len(boxes) == 1
    assert garbled_cluster_count == 2
    x1, y1, x2, y2 = boxes[0]
    # The crop must span the formula body plus the absorbed limit row.
    assert x1 < 298.0 / 612.0
    assert x2 > 396.0 / 612.0
    assert y1 < 172.4 / 792.0
    assert y2 > 208.9 / 792.0
    # Prose lines above and below stay outside the crop.
    assert y1 > 162.1 / 792.0
    assert y2 < 225.3 / 792.0


def test_garbled_line_bboxes_bridges_interleaved_clean_limit_rows() -> None:
    # LRN shape: garbled delimiter rows with clean summation rows between.
    words = [
        _word(108.0, 149.8, 504.0, 162.1, "prose line above the formula"),
        _word(300.0, 172.4, 396.0, 183.2, _GARBLE),
        _word(262.2, 190.0, 357.0, 196.2, "min(N-1,i+n/2)"),
        _word(298.0, 202.7, 310.0, 208.9, "X"),
        _word(211.0, 215.3, 396.0, 226.1, f"bix,y = aix,y / k {_GARBLE}"),
        _word(298.0, 232.0, 357.0, 238.9, "j=max(0,i-n/2)"),
        _word(108.0, 260.3, 504.0, 268.2, "prose line below the formula"),
    ]
    result = _garbled_line_bboxes(_BBOX_PAGE_TEMPLATE.format(words="".join(words)))
    assert result is not None
    boxes, garbled_cluster_count = result
    assert garbled_cluster_count == 2
    assert len(boxes) == 1
    _x1, y1, _x2, y2 = boxes[0]
    # The crop must span both garbled rows including the clean rows between.
    assert y1 < 172.4 / 792.0
    assert y2 > 226.1 / 792.0
    # Surrounding prose stays outside the crop.
    assert y1 > 162.1 / 792.0
    assert y2 < 260.3 / 792.0


def test_garbled_line_bboxes_keeps_distant_formulas_separate() -> None:
    words = [
        _word(262.2, 172.4, 396.0, 183.2, _GARBLE),
        _word(108.0, 300.0, 504.0, 308.9, "prose line between the formulas"),
        _word(108.0, 320.0, 504.0, 328.9, "second prose line separator"),
        _word(108.0, 340.0, 504.0, 348.9, "third prose line separator"),
        _word(262.2, 420.5, 396.0, 431.7, _GARBLE),
    ]
    result = _garbled_line_bboxes(_BBOX_PAGE_TEMPLATE.format(words="".join(words)))
    assert result is not None
    boxes, garbled_cluster_count = result
    assert garbled_cluster_count == 2
    assert len(boxes) == 2
    assert boxes[0] != boxes[1]


def test_garbled_line_bboxes_returns_empty_when_nothing_is_garbled() -> None:
    html = _BBOX_PAGE_TEMPLATE.format(
        words=_word(108.0, 149.8, 504.0, 162.1, "clean prose only")
    )
    assert _garbled_line_bboxes(html) == ((), 0)


@pytest.mark.parametrize("html", ["", "<doc>no page</doc>"])
def test_garbled_line_bboxes_rejects_unparseable_pages(html: str) -> None:
    assert _garbled_line_bboxes(html) is None


def test_render_text_page_writes_bbox_marker_when_coordinates_exist() -> None:
    text = f"clean line\ngarbled {_GARBLE} formula\n"
    rendered = _render_text_page(text, 4, ((0.3384, 0.2126, 0.6602, 0.2688),))
    assert (
        "[[paper-copilot-ocr:start slot=page-0004-formula-0001 page=4 "
        "bbox=0.3384,0.2126,0.6602,0.2688]]"
    ) in rendered
    assert "[[paper-copilot-ocr:end slot=page-0004-formula-0001]]" in rendered


def test_render_text_page_keeps_plain_marker_without_coordinates() -> None:
    rendered = _render_text_page(f"garbled {_GARBLE} line\n", 4, ())
    assert (
        "[[paper-copilot-ocr:start slot=page-0004-formula-0001 page=4]]"
    ) in rendered
    assert "bbox=" not in rendered


def test_render_text_page_groups_consecutive_garbled_lines_into_one_slot() -> None:
    text = f"garbled {_GARBLE} one\ngarbled {_GARBLE} two\nclean line\n"
    rendered = _render_text_page(text, 4, ((0.2, 0.3, 0.8, 0.4),))
    assert rendered.count("[[paper-copilot-ocr:start") == 1
    assert "slot=page-0004-formula-0001 page=4 bbox=0.2000,0.3000,0.8000,0.4000" in rendered
    assert f"原始提取：garbled {_GARBLE} one" in rendered  # noqa: RUF001
    assert f"原始提取：garbled {_GARBLE} two" in rendered  # noqa: RUF001
    assert "formula-0002" not in rendered


def test_render_text_page_bridges_interleaved_clean_lines_into_one_slot() -> None:
    # LRN shape: clean summation rows between two garbled rows.
    text = (
        f"garbled {_GARBLE} delimiter\n"
        "min(N-1,i+n/2)\n"
        "X\n"
        f"bix,y garbled {_GARBLE} body\n"
        "j=max(0,i-n/2)\n"
        "prose after the formula\n"
    )
    rendered = _render_text_page(text, 4, ((0.2, 0.3, 0.8, 0.4),))
    assert rendered.count("[[paper-copilot-ocr:start") == 1
    assert f"原始提取：garbled {_GARBLE} delimiter" in rendered  # noqa: RUF001
    assert "原始提取：min(N-1,i+n/2)" in rendered  # noqa: RUF001
    assert f"原始提取：bix,y garbled {_GARBLE} body" in rendered  # noqa: RUF001
    # The trailing clean row after the last garbled line stays outside.
    assert "原始提取：j=max(0,i-n/2)" not in rendered  # noqa: RUF001
    assert "j=max(0,i-n/2)" in rendered
    assert "prose after the formula" in rendered


def test_render_text_page_splits_slots_at_long_clean_gaps() -> None:
    text = (
        f"garbled {_GARBLE} one\n"
        "clean line\n"
        "clean line two\n"
        "clean line three\n"
        f"garbled {_GARBLE} two\n"
    )
    rendered = _render_text_page(
        text,
        4,
        ((0.2, 0.3, 0.8, 0.4), (0.2, 0.6, 0.8, 0.7)),
    )
    assert rendered.count("[[paper-copilot-ocr:start") == 2
    assert "slot=page-0004-formula-0001" in rendered
    assert "slot=page-0004-formula-0002" in rendered
    # The unbridged clean gap stays outside both slots as plain text.
    assert "原始提取：clean line" not in rendered  # noqa: RUF001
    assert "clean line\nclean line two\nclean line three" in rendered


def test_garble_detection_covers_control_characters() -> None:
    # C0 codes (math glyphs mapped to raw glyph indices) are damage signals.
    assert _contains_extraction_garble("0.9 \u000f wi")
    assert _contains_extraction_garble("\x7f")
    # Layout whitespace is not damage.
    assert not _contains_extraction_garble("a\tb")
    assert not _contains_extraction_garble("clean prose line")


def test_render_text_page_visualizes_control_characters_in_slot() -> None:
    text = "the update rule for weight w was\nvi+1 := 0.9 \x0f wi\nwhere i is the index"
    rendered = _render_text_page(text, 6)
    # The C0 line opens a slot and its residue becomes a visible control picture.
    assert "formula-0001" in rendered
    assert "\u240f" in rendered
    assert "\x0f" not in rendered
    # Clean anchors stay outside the slot body.
    assert "原始提取：the update rule" not in rendered  # noqa: RUF001
    assert "原始提取：where i is the index" not in rendered  # noqa: RUF001


def test_slot_block_count_matches_slot_grouping() -> None:
    interleaved = (
        f"garbled {_GARBLE} one\n"
        "clean line\n"
        "clean line two\n"
        f"garbled {_GARBLE} two\n"
    )
    assert _slot_block_count(interleaved) == 1
    separated = (
        f"garbled {_GARBLE} one\n"
        "clean line\n"
        "clean line two\n"
        "clean line three\n"
        f"garbled {_GARBLE} two\n"
    )
    assert _slot_block_count(separated) == 2
    assert _slot_block_count("clean only\n") == 0


def test_formula_aware_text_aligns_bboxes_to_garbled_lines() -> None:
    # The raw page text (before rendering) drives slot counts.
    raw_pages = b"clean page\n" + b"\f" + f"garble {_GARBLE} here\n".encode()
    text_bytes, boundaries = _formula_aware_text(
        raw_pages,
        2,
        {2: ((0.1, 0.2, 0.3, 0.4),)},
    )
    text = text_bytes.decode("utf-8")
    assert "bbox=0.1000,0.2000,0.3000,0.4000" in text
    assert len(boundaries) == 2


def test_slot_bbox_pattern_parses_marker_fields() -> None:
    marker = _ocr_start_marker("page-0004-formula-0002", 4, (0.3384, 0.2126, 0.6602, 0.2688))
    match = _SLOT_BBOX_PATTERN.search(marker)
    assert match is not None
    assert match.group(1) == "page-0004-formula-0002"
    assert match.group(2) == "4"
    assert tuple(float(match.group(index)) for index in range(3, 7)) == (
        0.3384,
        0.2126,
        0.6602,
        0.2688,
    )
    # Markers without coordinates carry no bbox field.
    plain = _ocr_start_marker("page-0004-formula-0002", 4, None)
    assert _SLOT_BBOX_PATTERN.search(plain) is None


def _recognize(**overrides: object) -> FormulaOCRInput:
    payload: dict[str, object] = {
        "operation": "recognize",
        "paper_id": _PAPER_ID,
        "page": 4,
        "purpose": "LRN formula",
        "cache_slot": "page-0004-formula-0001",
    }
    payload.update(overrides)
    return FormulaOCRInput.model_validate(payload)


def test_recognize_accepts_cache_slot_alone() -> None:
    assert _recognize().cache_slot == "page-0004-formula-0001"


def test_recognize_still_accepts_region_or_label_alone() -> None:
    with_region = _recognize(
        cache_slot=None,
        region={"x1": 0.2, "y1": 0.2, "x2": 0.8, "y2": 0.3},
    )
    assert with_region.region is not None
    with_label = _recognize(cache_slot=None, equation_label="3")
    assert with_label.equation_label == "3"


def test_recognize_rejects_missing_locator() -> None:
    with pytest.raises(ValueError, match="requires equation_label, region, or cache_slot"):
        _recognize(cache_slot=None)


def test_recognize_rejects_label_and_region_together() -> None:
    with pytest.raises(ValueError, match="at most one"):
        _recognize(
            equation_label="3",
            region={"x1": 0.2, "y1": 0.2, "x2": 0.8, "y2": 0.3},
        )


def test_accept_tolerates_echoed_locator_fields() -> None:
    payload: dict[str, object] = {
        "operation": "accept",
        "paper_id": _PAPER_ID,
        "page": 4,
        "candidate_id": f"formula-candidate-{'a' * 32}",
        # Models commonly echo these back; the frozen candidate stays the
        # only trust anchor, so they must not fail validation.
        "cache_slot": "page-0004-formula-0001",
        "purpose": "LRN formula",
        "region": {"x1": 0.2, "y1": 0.2, "x2": 0.8, "y2": 0.3},
    }
    accepted = FormulaOCRInput.model_validate(payload)
    assert accepted.candidate_id is not None


def test_accept_still_requires_candidate_id() -> None:
    with pytest.raises(ValueError, match="requires candidate_id"):
        FormulaOCRInput.model_validate(
            {"operation": "accept", "paper_id": _PAPER_ID, "page": 4}
        )
