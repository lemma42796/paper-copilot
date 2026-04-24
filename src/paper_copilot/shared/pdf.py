"""PDF reading utilities used by SkimAgent (front matter) and, later,
DeepAgent chunking.

This module sits below the LLM boundary: PyMuPDF exceptions (encrypted
PDFs, corrupt files, missing path) propagate unchanged. Callers translate
them at the entry point.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from paper_copilot.shared.errors import PdfError

__all__ = [
    "OutlineEntry",
    "PdfFrontMatter",
    "extract_page_range",
    "get_page_count",
    "load_front_matter",
]


@dataclass(frozen=True, slots=True)
class OutlineEntry:
    title: str
    page: int
    depth: int


@dataclass(frozen=True, slots=True)
class PdfFrontMatter:
    text: str
    page_count: int
    pages_loaded: int
    outline: list[OutlineEntry] | None


def load_front_matter(
    pdf_path: Path,
    pages_with_outline: int = 3,
    pages_without_outline: int = 8,
) -> PdfFrontMatter:
    # When the PDF has no bookmarks, Skim must infer the outline from in-text
    # headings; feeding only 3 pages drops the outline's tail and cascades into
    # Deep missing the back half of the paper (see docs/issues.md, Zhou06).
    with pymupdf.open(pdf_path) as doc:  # type: ignore[no-untyped-call]
        page_count: int = doc.page_count
        raw_toc = doc.get_toc()
        outline: list[OutlineEntry] | None = (
            [
                OutlineEntry(title=str(title).strip(), page=int(page), depth=int(level))
                for level, title, page in raw_toc
            ]
            if raw_toc
            else None
        )
        n_pages = pages_with_outline if outline is not None else pages_without_outline
        limit = min(n_pages, page_count)

        chunks: list[str] = []
        for i in range(limit):
            chunks.append(f"--- page {i + 1} ---")
            chunks.append(doc.load_page(i).get_text())
        text = "\n\n".join(chunks)

    return PdfFrontMatter(
        text=text, page_count=page_count, pages_loaded=limit, outline=outline
    )


def get_page_count(pdf_path: Path) -> int:
    with pymupdf.open(pdf_path) as doc:  # type: ignore[no-untyped-call]
        count: int = doc.page_count
    return count


def extract_page_range(pdf_path: Path, start_page: int, end_page: int) -> str:
    """Extract text from pages [start_page, end_page] inclusive, 1-based."""
    if start_page < 1:
        raise PdfError(f"start_page must be >= 1, got {start_page}")
    if end_page < start_page:
        raise PdfError(f"end_page ({end_page}) must be >= start_page ({start_page})")
    with pymupdf.open(pdf_path) as doc:  # type: ignore[no-untyped-call]
        page_count: int = doc.page_count
        if end_page > page_count:
            raise PdfError(f"end_page ({end_page}) exceeds document page_count ({page_count})")
        chunks: list[str] = [
            doc.load_page(i - 1).get_text() for i in range(start_page, end_page + 1)
        ]
    return "\n\n".join(chunks)
