from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from paper_copilot.agents.research_evidence import ActivePaperSnapshot
from paper_copilot.shared.errors import KnowledgeError
from paper_copilot.shared.pdf_cache import PdfCacheRef, PdfTextCache

__all__ = [
    "ReadPageInput",
    "ReadPageRun",
    "read_page_tool_description",
    "run_read_page",
]

_SCHEMA_VERSION = 1


class ReadPageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pdf_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description=(
            "Complete lowercase PDF SHA-256 from the trusted research_cache_index. "
            "Short hashes, filenames, and paths are not accepted."
        ),
    )
    page: int = Field(
        ge=1,
        description="One-based PDF page number to read.",
    )


@dataclass(frozen=True, slots=True)
class ReadPageRun:
    output: dict[str, Any]
    trace_attributes: dict[str, Any]


def read_page_tool_description() -> str:
    return (
        "Read one text page from the Runtime-prepared paper cache. Pass the complete "
        "lowercase PDF SHA-256 from research_cache_index and a one-based PDF page. "
        "The Runtime verifies the active cache revision and returns bounded page text "
        "with citation-grade evidence metadata. This tool does not search, extract, "
        "render images, or accept paths."
    )


async def run_read_page(
    args: ReadPageInput,
    *,
    cache_root: Path,
    active_papers: dict[str, ActivePaperSnapshot],
) -> ReadPageRun:
    active_paper = active_papers.get(args.pdf_sha256)
    if active_paper is None:
        raise KnowledgeError(
            "read_page pdf_sha256 is not in the current Runtime research cache index"
        )
    if args.page > active_paper.page_count:
        raise KnowledgeError(
            f"page {args.page} is outside the cached PDF page range "
            f"1-{active_paper.page_count}"
        )
    cache_ref = PdfCacheRef(
        pdf_sha256=active_paper.pdf_sha256,
        extractor_fingerprint=active_paper.extractor_fingerprint,
        revision_id=active_paper.cache_revision_id,
    )
    cache_page = await PdfTextCache(cache_root).page(cache_ref, page=args.page)
    if cache_page.artifact_sha256 != active_paper.artifact_sha256:
        raise KnowledgeError("read_page cache artifact changed after Runtime preflight")
    page_artifact_sha256 = hashlib.sha256(cache_page.text.encode("utf-8")).hexdigest()
    page_evidence = {
        "schema_version": _SCHEMA_VERSION,
        "source_kind": "cached_text_page",
        "pdf_sha256": cache_page.paper_id,
        "page": cache_page.page,
        "artifact_sha256": page_artifact_sha256,
        "extractor_fingerprint": cache_ref.extractor_fingerprint,
        "cache_revision_id": cache_ref.revision_id,
        "region": None,
        "render_sha256": None,
    }
    return ReadPageRun(
        output={
            "status": "ok",
            "pdf_sha256": cache_page.paper_id,
            "page": cache_page.page,
            "text": cache_page.text,
            "evidence": page_evidence,
        },
        trace_attributes={
            "read_page_schema_version": _SCHEMA_VERSION,
            "pdf_sha256": cache_page.paper_id,
            "page": cache_page.page,
            "artifact_sha256": page_artifact_sha256,
            "cache_artifact_sha256": cache_page.artifact_sha256,
            "extractor_fingerprint": cache_ref.extractor_fingerprint,
            "cache_revision_id": cache_ref.revision_id,
            "page_evidence": page_evidence,
        },
    )
