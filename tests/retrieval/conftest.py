from collections.abc import Callable
from pathlib import Path

import pymupdf
import pytest


@pytest.fixture
def make_pdf(tmp_path: Path) -> Callable[[list[str]], Path]:
    def _make(pages: list[str]) -> Path:
        doc = pymupdf.open()
        for content in pages:
            page = doc.new_page()
            page.insert_text((50, 72), content)
        pdf_path = tmp_path / "test.pdf"
        doc.save(pdf_path)
        doc.close()
        return pdf_path

    return _make
