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

__all__ = ["OutlineEntry", "PdfFrontMatter", "load_front_matter"]


@dataclass(frozen=True, slots=True)
class OutlineEntry:
    title: str
    page: int
    depth: int


@dataclass(frozen=True, slots=True)
class PdfFrontMatter:
    text: str
    page_count: int
    outline: list[OutlineEntry] | None


def load_front_matter(pdf_path: Path, n_pages: int = 3) -> PdfFrontMatter:
    with pymupdf.open(pdf_path) as doc:  # type: ignore[no-untyped-call]
        page_count: int = doc.page_count
        limit = min(n_pages, page_count)

        chunks: list[str] = []
        for i in range(limit):
            chunks.append(f"--- page {i + 1} ---")
            chunks.append(doc.load_page(i).get_text())
        text = "\n\n".join(chunks)

        raw_toc = doc.get_toc()
        outline: list[OutlineEntry] | None = (
            [
                OutlineEntry(title=str(title).strip(), page=int(page), depth=int(level))
                for level, title, page in raw_toc
            ]
            if raw_toc
            else None
        )

    return PdfFrontMatter(text=text, page_count=page_count, outline=outline)
