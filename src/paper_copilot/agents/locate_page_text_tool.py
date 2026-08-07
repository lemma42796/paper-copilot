from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf
from pydantic import BaseModel, ConfigDict, Field

from paper_copilot.agents.inspect_page_tool import (
    _resolve_library_root,
    _resolve_paper_path,
    _sha256_file,
)
from paper_copilot.shared.errors import KnowledgeError

__all__ = [
    "LocatePageTextInput",
    "LocatePageTextRun",
    "locate_page_text_tool_description",
    "run_locate_page_text",
]

_SCHEMA_VERSION = 1
_SEARCH_MAX_MATCHES = 20


class LocatePageTextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str = Field(
        min_length=12,
        max_length=64,
        pattern=r"^(?:[0-9a-f]{12}|[0-9a-f]{64})$",
        description=(
            "Full PDF SHA-256 from the Runtime-prepared research manifest. "
            "Legacy 12-character Paper Copilot IDs remain accepted for historical "
            "sessions."
        ),
    )
    page: int = Field(
        ge=1,
        description="One-based PDF page number to search.",
    )
    query: str = Field(
        min_length=1,
        max_length=300,
        description=(
            "Exact phrase quoted from layout.txt, for example a prose line that "
            "directly precedes or follows a formula. Quote a short distinctive "
            "fragment; a phrase broken by a line break will not match."
        ),
    )
    purpose: str = Field(
        min_length=1,
        max_length=500,
        description="Why this text needs to be located on the page.",
    )


@dataclass(frozen=True, slots=True)
class LocatePageTextRun:
    output: dict[str, Any]
    trace_attributes: dict[str, Any]


def locate_page_text_tool_description() -> str:
    return (
        "Locate a quoted phrase in the text layer of one page of an authorized "
        "local PDF and return normalized rectangles for every match: the phrase "
        "itself and the full text line containing it. Use this to turn text you "
        "can already read in layout.txt (for example the prose line above or "
        "below a formula) into page coordinates, then derive a crop region for "
        "recognize_formula or inspect_page from those rectangles. This tool "
        "renders nothing and performs no OCR."
    )


async def run_locate_page_text(
    args: LocatePageTextInput,
    library_root: Path | None,
) -> LocatePageTextRun:
    root = _resolve_library_root(library_root)
    pdf_path = await asyncio.to_thread(_resolve_paper_path, args.paper_id, root)
    pdf_sha256 = await asyncio.to_thread(_sha256_file, pdf_path)
    started = time.monotonic()
    matches = await asyncio.to_thread(
        _search_page_text, pdf_path, args.page, args.query
    )
    current_pdf_sha256 = await asyncio.to_thread(_sha256_file, pdf_path)
    if current_pdf_sha256 != pdf_sha256:
        raise KnowledgeError("PDF changed while locate_page_text was searching it")
    evidence = {
        "schema_version": _SCHEMA_VERSION,
        "source_kind": "pdf_page_text_search",
        "pdf_sha256": pdf_sha256,
        "page": args.page,
        "region": None,
        "artifact_sha256": None,
        "extractor_fingerprint": None,
        "cache_revision_id": None,
        "query": args.query,
    }
    output = {
        "status": "ok",
        "paper_id": args.paper_id,
        "page": args.page,
        "purpose": args.purpose,
        "query": args.query,
        "match_count": len(matches),
        "matches": matches,
        "evidence": [evidence],
        "unresolved": [],
    }
    if not matches:
        output["note"] = (
            "no text-layer match for this quote; copy a shorter distinctive "
            "fragment from layout.txt, avoiding words split across line breaks"
        )
    return LocatePageTextRun(
        output=output,
        trace_attributes={
            "locate_page_text_schema_version": _SCHEMA_VERSION,
            "paper_id": args.paper_id,
            "pdf_sha256": pdf_sha256,
            "page": args.page,
            "query": args.query,
            "match_count": len(matches),
            "wall_time_seconds": round(time.monotonic() - started, 3),
            "page_evidence": evidence,
        },
    )


def _search_page_text(
    pdf_path: Path, page_number: int, query: str
) -> list[dict[str, Any]]:
    """Return normalized phrase and containing-line rectangles for each match.

    The line box spans every text-layer word whose vertical center falls inside
    the phrase rect, so it approximates the full column-width row. That row box
    lets callers derive formula crop bands between two prose anchors without
    knowing column geometry.
    """
    document = pymupdf.open(pdf_path)
    try:
        if page_number > document.page_count:
            raise KnowledgeError(
                f"page {page_number} is outside the PDF page range "
                f"1-{document.page_count}"
            )
        page = document.load_page(page_number - 1)
        width = page.rect.width
        height = page.rect.height
        if width <= 0.0 or height <= 0.0:
            raise KnowledgeError("PDF page has a degenerate size")
        words = page.get_text("words")
        results: list[dict[str, Any]] = []
        for rect in page.search_for(query)[:_SEARCH_MAX_MATCHES]:
            line = _line_box(words, rect)
            results.append(
                {
                    "phrase": _normalized_rect(rect, width, height),
                    "line": _normalized_rect(line, width, height),
                }
            )
        return results
    finally:
        document.close()


def _line_box(words: list[Any], rect: pymupdf.Rect) -> pymupdf.Rect:
    union = pymupdf.Rect(rect)
    for word in words:
        vertical_center = (word[1] + word[3]) / 2.0
        if rect.y0 <= vertical_center <= rect.y1:
            union |= pymupdf.Rect(word[0], word[1], word[2], word[3])
    return union


def _normalized_rect(
    rect: pymupdf.Rect,
    width: float,
    height: float,
) -> dict[str, float]:
    def clamp(value: float) -> float:
        return max(0.0, min(1.0, round(value, 4)))

    return {
        "x1": clamp(rect.x0 / width),
        "y1": clamp(rect.y0 / height),
        "x2": clamp(rect.x1 / width),
        "y2": clamp(rect.y1 / height),
    }
