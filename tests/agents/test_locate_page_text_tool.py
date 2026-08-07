"""Text-layer anchor search behavior for locate_page_text."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pymupdf
import pytest

from paper_copilot.agents.locate_page_text_tool import (
    LocatePageTextInput,
    _search_page_text,
    run_locate_page_text,
)
from paper_copilot.shared.errors import KnowledgeError

_UPPER = "The update rule for weight w was"
_LOWER = "where i is the iteration index"


def _make_anchored_pdf(path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72.0, 100.0), _UPPER)
    page.insert_text((72.0, 300.0), _LOWER)
    document.save(path)
    document.close()


def _input(paper_id: str, query: str, page: int = 1) -> LocatePageTextInput:
    return LocatePageTextInput(
        paper_id=paper_id,
        page=page,
        query=query,
        purpose="anchor a formula crop",
    )


def test_search_page_text_returns_phrase_and_line_rects(tmp_path: Path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    _make_anchored_pdf(pdf_path)
    matches = _search_page_text(pdf_path, 1, "update rule")
    assert len(matches) == 1
    phrase = matches[0]["phrase"]
    line = matches[0]["line"]
    # Normalized page-relative coordinates.
    assert all(0.0 <= value <= 1.0 for value in phrase.values())
    # The containing line spans the whole text row, wider than the phrase.
    assert line["x1"] <= phrase["x1"]
    assert line["x2"] >= phrase["x2"]
    # The anchor row sits above the second prose row.
    assert line["y2"] < 300.0 / 842.0


def test_search_page_text_no_match_is_empty(tmp_path: Path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    _make_anchored_pdf(pdf_path)
    assert _search_page_text(pdf_path, 1, "absent phrase") == []


def test_search_page_text_rejects_page_outside_range(tmp_path: Path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    _make_anchored_pdf(pdf_path)
    with pytest.raises(KnowledgeError):
        _search_page_text(pdf_path, 2, "update rule")


def test_run_locate_page_text_end_to_end(tmp_path: Path) -> None:
    library = tmp_path / "library"
    library.mkdir()
    pdf_path = library / "paper.pdf"
    _make_anchored_pdf(pdf_path)
    paper_id = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

    async def run() -> dict[str, object]:
        result = await run_locate_page_text(_input(paper_id, _LOWER), library)
        return result.output

    output = asyncio.run(run())
    assert output["status"] == "ok"
    assert output["match_count"] == 1
    assert isinstance(output["matches"], list) and output["matches"]


def test_run_locate_page_text_no_match_adds_note(tmp_path: Path) -> None:
    library = tmp_path / "library"
    library.mkdir()
    pdf_path = library / "paper.pdf"
    _make_anchored_pdf(pdf_path)
    paper_id = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

    async def run() -> dict[str, object]:
        result = await run_locate_page_text(_input(paper_id, "absent phrase"), library)
        return result.output

    output = asyncio.run(run())
    assert output["match_count"] == 0
    assert "note" in output


def test_run_locate_page_text_requires_library(tmp_path: Path) -> None:
    async def run() -> None:
        await run_locate_page_text(
            _input("a" * 64, "update rule"), tmp_path / "missing"
        )

    with pytest.raises(KnowledgeError):
        asyncio.run(run())
