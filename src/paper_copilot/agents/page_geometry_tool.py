from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pymupdf
from pydantic import BaseModel, ConfigDict, Field, model_validator

from paper_copilot.agents.inspect_page_tool import (
    InspectPageRegion,
    _resolve_paper_path,
    _sha256_file,
)
from paper_copilot.shared.errors import KnowledgeError

__all__ = [
    "PageGeometryInput",
    "PageGeometryRun",
    "page_geometry_tool_description",
    "run_page_geometry",
]

_SCHEMA_VERSION = 1
_MAX_SEARCH_MATCHES = 20
_DEFAULT_MAX_CHARACTERS = 240
_MAX_CHARACTERS = 600
_ENGLISH_WORD_PATTERN = re.compile(r"[A-Za-z]{2,}")


class PageGeometryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["search_text", "inspect_region"] = Field(
        description=(
            "Use search_text for a known equation label, prose fragment, or visible "
            "formula text. Use inspect_region to enumerate bounded lines and character "
            "coordinates while refining a formula crop."
        )
    )
    paper_id: str = Field(
        min_length=12,
        max_length=64,
        pattern=r"^(?:[0-9a-f]{12}|[0-9a-f]{64})$",
        description="Authorized PDF SHA-256 or legacy 12-character paper ID.",
    )
    page: int = Field(ge=1, description="One-based physical PDF page number.")
    query: str | None = Field(
        default=None,
        min_length=1,
        max_length=300,
        description="Exact text to locate during search_text.",
    )
    region: InspectPageRegion | None = Field(
        default=None,
        description="Normalized bounded page region to enumerate during inspect_region.",
    )
    purpose: str = Field(
        min_length=1,
        max_length=500,
        description="Specific formula boundary or anchor being explored.",
    )
    max_characters: int = Field(
        default=_DEFAULT_MAX_CHARACTERS,
        ge=1,
        le=_MAX_CHARACTERS,
        description="Maximum character boxes returned by inspect_region.",
    )

    @model_validator(mode="after")
    def _operation_arguments_match(self) -> PageGeometryInput:
        if self.operation == "search_text":
            if self.query is None:
                raise ValueError("search_text requires query")
            if self.region is not None:
                raise ValueError("search_text does not accept region")
            return self
        if self.region is None:
            raise ValueError("inspect_region requires region")
        if self.query is not None:
            raise ValueError("inspect_region does not accept query")
        return self


@dataclass(frozen=True, slots=True)
class PageGeometryRun:
    output: dict[str, Any]
    trace_attributes: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _GeometryLine:
    line_id: str
    text: str
    bbox: pymupdf.Rect
    characters: tuple[tuple[str, pymupdf.Rect], ...]


def page_geometry_tool_description() -> str:
    return (
        "Explore text-layer coordinates on one authorized PDF page while locating a "
        "formula. This tool never chooses an OCR crop. search_text returns exact text "
        "matches and their containing lines; inspect_region returns bounded lines and "
        "per-character rectangles, including damaged characters when the PDF text layer "
        "exposes them. Use semantic context or a printed equation label to choose the "
        "page, then refine coordinates before passing an explicit region to "
        "recognize_formula. Results are geometry hints and may be incomplete when the PDF "
        "text layer omits glyphs."
    )


async def run_page_geometry(
    args: PageGeometryInput,
    library_root: Path | None,
) -> PageGeometryRun:
    root = _resolve_library_root(library_root)
    pdf_path = await asyncio.to_thread(_resolve_paper_path, args.paper_id, root)
    pdf_sha256 = await asyncio.to_thread(_sha256_file, pdf_path)
    payload = await asyncio.to_thread(_query_geometry, pdf_path, args)
    current_pdf_sha256 = await asyncio.to_thread(_sha256_file, pdf_path)
    if current_pdf_sha256 != pdf_sha256:
        raise KnowledgeError("PDF changed while page geometry was being queried")
    output = {
        "status": "ok",
        "schema_version": _SCHEMA_VERSION,
        "paper_id": args.paper_id,
        "page": args.page,
        "operation": args.operation,
        "purpose": args.purpose,
        "geometry_source": "pymupdf_rawdict",
        **payload,
    }
    return PageGeometryRun(
        output=output,
        trace_attributes={
            "page_geometry_schema_version": _SCHEMA_VERSION,
            "paper_id": args.paper_id,
            "pdf_sha256": pdf_sha256,
            "page": args.page,
            "operation": args.operation,
            "result_count": payload["result_count"],
            "truncated": payload["truncated"],
        },
    )


def _resolve_library_root(library_root: Path | None) -> Path:
    if library_root is None:
        raise KnowledgeError("page geometry requires a configured PDF library")
    root = library_root.expanduser().resolve()
    if not root.is_dir():
        raise KnowledgeError("configured PDF library is not available")
    return root


def _query_geometry(pdf_path: Path, args: PageGeometryInput) -> dict[str, Any]:
    document = pymupdf.open(pdf_path)
    try:
        if args.page > document.page_count:
            raise KnowledgeError(
                f"page {args.page} is outside the PDF page range 1-{document.page_count}"
            )
        page = document.load_page(args.page - 1)
        lines = _page_lines(page)
        if args.operation == "search_text":
            assert args.query is not None
            return _search_text(page, lines, args.query)
        assert args.region is not None
        return _inspect_region(page, lines, args.region, args.max_characters)
    finally:
        document.close()


def _page_lines(page: pymupdf.Page) -> tuple[_GeometryLine, ...]:
    raw = page.get_text("rawdict")
    lines: list[_GeometryLine] = []
    for block_index, block in enumerate(raw.get("blocks", [])):
        if not isinstance(block, dict):
            continue
        for line_index, line in enumerate(block.get("lines", [])):
            if not isinstance(line, dict):
                continue
            characters: list[tuple[str, pymupdf.Rect]] = []
            for span in line.get("spans", []):
                if not isinstance(span, dict):
                    continue
                for character in span.get("chars", []):
                    if not isinstance(character, dict):
                        continue
                    text = character.get("c")
                    bbox = character.get("bbox")
                    if not isinstance(text, str) or not text or not _valid_bbox(bbox):
                        continue
                    characters.append(
                        (_sanitize_extracted_text(text), pymupdf.Rect(bbox))
                    )
            if not characters:
                continue
            line_bbox = pymupdf.Rect(characters[0][1])
            for _text, character_bbox in characters[1:]:
                line_bbox |= character_bbox
            lines.append(
                _GeometryLine(
                    line_id=f"block-{block_index + 1:03d}-line-{line_index + 1:03d}",
                    text="".join(text for text, _bbox in characters),
                    bbox=line_bbox,
                    characters=tuple(characters),
                )
            )
    return tuple(lines)


def _search_text(
    page: pymupdf.Page,
    lines: tuple[_GeometryLine, ...],
    query: str,
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    found = page.search_for(query)
    for rect in found[:_MAX_SEARCH_MATCHES]:
        line = _best_line(lines, rect)
        match: dict[str, Any] = {
            "phrase": _normalized_rect(rect, page.rect),
        }
        if line is not None:
            match.update(
                {
                    "line_id": line.line_id,
                    "line": _normalized_rect(line.bbox, page.rect),
                    "line_text": line.text[:500],
                    "line_has_prose": _has_prose(line.text),
                }
            )
        matches.append(match)
    return {
        "query": query,
        "matches": matches,
        "result_count": len(matches),
        "truncated": len(found) > _MAX_SEARCH_MATCHES,
        **(
            {
                "note": (
                    "No exact text-layer match was found. Inspect a bounded region near "
                    "the semantic context instead of treating this as proof the text is absent."
                )
            }
            if not matches
            else {}
        ),
    }


def _inspect_region(
    page: pymupdf.Page,
    lines: tuple[_GeometryLine, ...],
    region: InspectPageRegion,
    max_characters: int,
) -> dict[str, Any]:
    clip = pymupdf.Rect(
        page.rect.x0 + region.x1 * page.rect.width,
        page.rect.y0 + region.y1 * page.rect.height,
        page.rect.x0 + region.x2 * page.rect.width,
        page.rect.y0 + region.y2 * page.rect.height,
    )
    payload_lines: list[dict[str, Any]] = []
    returned_characters = 0
    truncated = False
    for line in lines:
        if returned_characters >= max_characters:
            truncated = True
            break
        selected = [
            (text, bbox)
            for text, bbox in line.characters
            if bbox.intersects(clip)
        ]
        if not selected:
            continue
        character_payload: list[dict[str, Any]] = []
        for text, bbox in selected:
            if returned_characters >= max_characters:
                truncated = True
                break
            character_payload.append(
                {
                    "text": text,
                    "bbox": _normalized_rect(bbox, page.rect),
                    "garbled": _is_garbled_text(text),
                }
            )
            returned_characters += 1
        payload_lines.append(
            {
                "line_id": line.line_id,
                "text": line.text[:500],
                "bbox": _normalized_rect(line.bbox, page.rect),
                "has_prose": _has_prose(line.text),
                "characters": character_payload,
            }
        )
        if truncated:
            break
    return {
        "region": region.model_dump(mode="json"),
        "lines": payload_lines,
        "character_count": returned_characters,
        "result_count": len(payload_lines),
        "truncated": truncated,
    }


def _best_line(
    lines: tuple[_GeometryLine, ...],
    rect: pymupdf.Rect,
) -> _GeometryLine | None:
    intersecting = [line for line in lines if line.bbox.intersects(rect)]
    if not intersecting:
        return None
    return max(
        intersecting,
        key=lambda line: (line.bbox & rect).get_area(),
    )


def _valid_bbox(value: object) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 4
        and all(isinstance(item, (int, float)) for item in value)
        and float(value[2]) > float(value[0])
        and float(value[3]) > float(value[1])
    )


def _normalized_rect(rect: pymupdf.Rect, page_rect: pymupdf.Rect) -> dict[str, float]:
    def clamp(value: float) -> float:
        return max(0.0, min(1.0, round(value, 4)))

    return {
        "x1": clamp((rect.x0 - page_rect.x0) / page_rect.width),
        "y1": clamp((rect.y0 - page_rect.y0) / page_rect.height),
        "x2": clamp((rect.x1 - page_rect.x0) / page_rect.width),
        "y2": clamp((rect.y1 - page_rect.y0) / page_rect.height),
    }


def _has_prose(text: str) -> bool:
    return any("\u3400" <= character <= "\u9fff" for character in text) or bool(
        _ENGLISH_WORD_PATTERN.search(text)
    )


def _sanitize_extracted_text(text: str) -> str:
    # PDF text is untrusted and PyMuPDF can expose isolated UTF-16 surrogates.
    # Replace them at the extraction boundary so every tool result is valid UTF-8.
    return "".join(
        "\ufffd" if "\ud800" <= character <= "\udfff" else character
        for character in text
    )


def _is_garbled_text(text: str) -> bool:
    return any(
        character == "\ufffd"
        or "\ue000" <= character <= "\uf8ff"
        or (
            ("\x00" <= character <= "\x1f" and character not in "\t\n\r")
            or character == "\x7f"
        )
        for character in text
    )
