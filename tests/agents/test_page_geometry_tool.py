"""Bounded text-layer exploration for formula coordinates."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pymupdf
import pytest

from paper_copilot.agents.page_geometry_tool import (
    PageGeometryInput,
    _query_geometry,
    run_page_geometry,
)
from paper_copilot.shared.errors import KnowledgeError

_UPPER = "The update rule for weight w was"
_FORMULA = "v(i+1) = 0.9 v(i)"
_LABEL = "(3.5)"


def _make_formula_pdf(path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72.0, 100.0), _UPPER)
    page.insert_text((160.0, 180.0), _FORMULA)
    page.insert_text((500.0, 180.0), _LABEL)
    document.save(path)
    document.close()


def _search_input(paper_id: str, query: str = _LABEL) -> PageGeometryInput:
    return PageGeometryInput(
        operation="search_text",
        paper_id=paper_id,
        page=1,
        query=query,
        purpose="locate the numbered display formula",
    )


def test_search_text_returns_phrase_and_containing_line(tmp_path: Path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    _make_formula_pdf(pdf_path)
    payload = _query_geometry(pdf_path, _search_input("a" * 64))
    assert payload["result_count"] == 1
    match = payload["matches"][0]
    assert match["line_text"] == _LABEL
    assert all(0.0 <= value <= 1.0 for value in match["phrase"].values())


def test_inspect_region_returns_character_coordinates(tmp_path: Path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    _make_formula_pdf(pdf_path)
    args = PageGeometryInput(
        operation="inspect_region",
        paper_id="a" * 64,
        page=1,
        region={"x1": 0.1, "y1": 0.15, "x2": 0.95, "y2": 0.3},
        purpose="find the first and last formula characters",
        max_characters=100,
    )
    payload = _query_geometry(pdf_path, args)
    assert payload["character_count"] > 0
    assert any(_FORMULA in line["text"] for line in payload["lines"])
    first = payload["lines"][0]["characters"][0]
    assert set(first["bbox"]) == {"x1", "y1", "x2", "y2"}


def test_search_text_no_match_is_inconclusive(tmp_path: Path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    _make_formula_pdf(pdf_path)
    payload = _query_geometry(pdf_path, _search_input("a" * 64, "absent"))
    assert payload["result_count"] == 0
    assert "note" in payload


def test_run_page_geometry_binds_result_to_pdf(tmp_path: Path) -> None:
    library = tmp_path / "library"
    library.mkdir()
    pdf_path = library / "paper.pdf"
    _make_formula_pdf(pdf_path)
    paper_id = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

    async def run() -> dict[str, object]:
        result = await run_page_geometry(_search_input(paper_id), library)
        return result.output

    output = asyncio.run(run())
    assert output["status"] == "ok"
    assert output["geometry_source"] == "pymupdf_rawdict"


def test_run_page_geometry_requires_library(tmp_path: Path) -> None:
    async def run() -> None:
        await run_page_geometry(_search_input("a" * 64), tmp_path / "missing")

    with pytest.raises(KnowledgeError):
        asyncio.run(run())
