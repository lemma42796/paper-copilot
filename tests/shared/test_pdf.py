from collections.abc import Callable
from pathlib import Path

import pymupdf
import pytest

from paper_copilot.shared.errors import PdfError
from paper_copilot.shared.pdf import extract_page_range, get_page_count


def _make_pdf(tmp_path: Path, pages: list[str]) -> Path:
    doc = pymupdf.open()
    for content in pages:
        page = doc.new_page()
        page.insert_text((50, 72), content)
    pdf_path = tmp_path / "test.pdf"
    doc.save(pdf_path)
    doc.close()
    return pdf_path


@pytest.fixture
def make_pdf(tmp_path: Path) -> Callable[[list[str]], Path]:
    def _make(pages: list[str]) -> Path:
        return _make_pdf(tmp_path, pages)

    return _make


def test_extract_page_range_single_page(make_pdf: Callable[[list[str]], Path]) -> None:
    pdf = make_pdf(["alpha page one", "beta page two", "gamma page three"])
    text = extract_page_range(pdf, 2, 2)
    assert "beta page two" in text
    assert "alpha" not in text
    assert "gamma" not in text


def test_extract_page_range_multi_page(make_pdf: Callable[[list[str]], Path]) -> None:
    pdf = make_pdf(["alpha page one", "beta page two", "gamma page three"])
    text = extract_page_range(pdf, 1, 3)
    assert "alpha" in text
    assert "beta" in text
    assert "gamma" in text


def test_extract_page_range_invalid_start(make_pdf: Callable[[list[str]], Path]) -> None:
    pdf = make_pdf(["a", "b"])
    with pytest.raises(PdfError):
        extract_page_range(pdf, 0, 1)


def test_extract_page_range_end_before_start(make_pdf: Callable[[list[str]], Path]) -> None:
    pdf = make_pdf(["a", "b"])
    with pytest.raises(PdfError):
        extract_page_range(pdf, 2, 1)


def test_extract_page_range_end_beyond_doc(make_pdf: Callable[[list[str]], Path]) -> None:
    pdf = make_pdf(["a", "b"])
    with pytest.raises(PdfError):
        extract_page_range(pdf, 1, 5)


def test_get_page_count(make_pdf: Callable[[list[str]], Path]) -> None:
    pdf = make_pdf(["a", "b", "c", "d"])
    assert get_page_count(pdf) == 4
