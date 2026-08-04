from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import pymupdf
from pydantic import BaseModel, ConfigDict, Field, model_validator

from paper_copilot.agents.inspect_page_tool import (
    InspectPageRegion,
    _page_count,
    _render_page,
    _resolve_paper_path,
    _resolve_poppler_executable,
    _sha256_file,
)
from paper_copilot.shared.errors import KnowledgeError
from paper_copilot.shared.pdf_cache import PdfTextCache

__all__ = [
    "FormulaOCRInput",
    "FormulaOCRRun",
    "formula_ocr_available",
    "formula_ocr_tool_description",
    "run_formula_ocr",
]

_COMPONENT_SCHEMA_VERSION = 2
_TOOL_SCHEMA_VERSION = 1
_HELPER_TIMEOUT_SECONDS = 120.0
_MAX_HELPER_OUTPUT_BYTES = 64_000
_DEFAULT_COMPONENT_ROOT = (
    Path.home()
    / "Library"
    / "Application Support"
    / "Paper Copilot"
    / "optional-components"
    / "formula-ocr"
)


class FormulaOCRInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["recognize", "accept"] = Field(
        default="recognize",
        description=(
            "Use recognize to obtain a candidate LaTeX result without changing the "
            "cache. After inspecting that result, use accept with its candidate_id "
            "to publish it into the text cache."
        ),
    )
    paper_id: str = Field(
        min_length=12,
        max_length=64,
        pattern=r"^(?:[0-9a-f]{12}|[0-9a-f]{64})$",
        description=(
            "Full PDF SHA-256 from the Runtime-prepared research manifest. "
            "Legacy 12-character Paper Copilot IDs remain accepted."
        ),
    )
    page: int = Field(ge=1, description="One-based physical PDF page number.")
    equation_label: str | None = Field(
        default=None,
        min_length=1,
        max_length=32,
        description=(
            "Printed equation label without parentheses, for example '3'. "
            "Use this for numbered display equations when no region is known."
        ),
    )
    region: InspectPageRegion | None = Field(
        default=None,
        description=(
            "Optional normalized formula crop. Use this when exact page coordinates "
            "are already known."
        ),
    )
    purpose: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        description="Specific formula that needs local OCR verification.",
    )
    cache_slot: str | None = Field(
        default=None,
        pattern=r"^page-[0-9]{4}-formula-[0-9]{4}$",
        description=(
            "Stable cache_slot shown beside a garbled formula in layout.txt. "
            "Provide it during recognize so a later accept can replace that exact "
            "location."
        ),
    )
    candidate_id: str | None = Field(
        default=None,
        pattern=r"^formula-candidate-[0-9a-f]{32}$",
        description="Candidate ID returned by recognize and required by accept.",
    )

    @model_validator(mode="after")
    def _operation_arguments_match(self) -> FormulaOCRInput:
        if self.operation == "recognize":
            if (self.equation_label is None) == (self.region is None):
                raise ValueError("recognize requires exactly one of equation_label or region")
            if self.purpose is None:
                raise ValueError("recognize requires purpose")
            if self.candidate_id is not None:
                raise ValueError("recognize does not accept candidate_id")
            return self
        if self.candidate_id is None:
            raise ValueError("accept requires candidate_id")
        if self.equation_label is not None or self.region is not None:
            raise ValueError("accept does not accept equation_label or region")
        if self.cache_slot is not None or self.purpose is not None:
            raise ValueError("accept uses the cache_slot and purpose frozen in the candidate")
        return self


@dataclass(frozen=True, slots=True)
class FormulaOCRRun:
    output: dict[str, Any]
    trace_attributes: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _FormulaOCRCandidate:
    candidate_id: str
    requested_paper_id: str
    pdf_sha256: str
    page: int
    purpose: str
    equation_label: str | None
    region: dict[str, float]
    latex: str
    model: str
    render_sha256: str
    cache_slot: str | None


_CANDIDATES: dict[str, _FormulaOCRCandidate] = {}
_CANDIDATES_LOCK = threading.Lock()


def formula_ocr_tool_description() -> str:
    return (
        "Recognize and optionally accept one formula from an authorized local PDF. "
        "Use this only when the current task requires understanding or citing a "
        "specific formula, that formula is corrupted or flattened in extracted PDF "
        "text, and the configured language model cannot inspect images. Do not call "
        "this tool merely because unrelated garbled text or formula slots exist. Identify "
        "the exact physical page first, then provide either a printed equation label "
        "or a normalized formula region. recognize returns a candidate without "
        "changing the cache. Inspect its LaTeX; only when it is acceptable call this "
        "tool again with operation=accept and candidate_id. If layout.txt showed a "
        "cache_slot, accept atomically publishes the TXT cache with the LaTeX replacing "
        "that garbled slot, then automatically deletes superseded TXT revisions. The "
        "optional local Formula OCR component "
        "must already be installed. Results are OCR output, not verified mathematical "
        "ground truth; preserve the returned page, region, hashes, and warnings."
    )


def formula_ocr_available() -> bool:
    return _formula_ocr_helper_path() is not None


async def run_formula_ocr(
    args: FormulaOCRInput,
    library_root: Path | None,
    *,
    cache_root: Path | None = None,
) -> FormulaOCRRun:
    if args.operation == "accept":
        return await _accept_formula_candidate(args, library_root, cache_root)
    helper_path = _formula_ocr_helper_path()
    if helper_path is None:
        raise KnowledgeError(
            "the optional Formula OCR component is not installed; download it "
            "from Paper Copilot settings"
        )
    root = _resolve_library_root(library_root)
    pdf_path = await asyncio.to_thread(_resolve_paper_path, args.paper_id, root)
    pdfinfo_path = _resolve_poppler_executable("pdfinfo")
    page_count = await _page_count(pdfinfo_path, pdf_path)
    if args.page > page_count:
        raise KnowledgeError(
            f"page {args.page} is outside the PDF page range 1-{page_count}"
        )
    pdf_sha256 = await asyncio.to_thread(_sha256_file, pdf_path)
    region = args.region or await asyncio.to_thread(
        _locate_numbered_formula,
        pdf_path,
        args.page,
        args.equation_label,
    )
    started = time.monotonic()
    pdftoppm_path = _resolve_poppler_executable("pdftoppm")
    with tempfile.TemporaryDirectory(prefix="paper-copilot-formula-ocr-") as raw_dir:
        render_path = await _render_page(
            pdftoppm_path,
            pdf_path,
            page=args.page,
            region=region,
            render_dir=Path(raw_dir),
        )
        render_sha256 = await asyncio.to_thread(_sha256_file, render_path)
        helper_result = await _run_helper(helper_path, render_path)
    current_pdf_sha256 = await asyncio.to_thread(_sha256_file, pdf_path)
    if current_pdf_sha256 != pdf_sha256:
        raise KnowledgeError("PDF changed while formula OCR was running")
    latex = helper_result.get("latex")
    model_name = helper_result.get("model")
    if not isinstance(latex, str) or not latex.strip():
        raise KnowledgeError("Formula OCR helper returned empty LaTeX")
    if not isinstance(model_name, str) or not model_name:
        raise KnowledgeError("Formula OCR helper omitted its model identity")
    region_payload = region.model_dump(mode="json")
    candidate_id = f"formula-candidate-{uuid4().hex}"
    candidate = _FormulaOCRCandidate(
        candidate_id=candidate_id,
        requested_paper_id=args.paper_id,
        pdf_sha256=pdf_sha256,
        page=args.page,
        purpose=args.purpose or "",
        equation_label=args.equation_label,
        region=region_payload,
        latex=latex.strip(),
        model=model_name,
        render_sha256=render_sha256,
        cache_slot=args.cache_slot,
    )
    with _CANDIDATES_LOCK:
        _CANDIDATES[candidate_id] = candidate
    evidence = {
        "schema_version": _TOOL_SCHEMA_VERSION,
        "source_kind": "pdf_formula_ocr",
        "pdf_sha256": pdf_sha256,
        "page": args.page,
        "region": region_payload,
        "artifact_sha256": render_sha256,
        "extractor_fingerprint": hashlib.sha256(
            model_name.encode("utf-8")
        ).hexdigest(),
        "cache_revision_id": None,
        "render_sha256": render_sha256,
    }
    output = {
        "status": "recognized_pending_acceptance",
        "candidate_id": candidate_id,
        "paper_id": args.paper_id,
        "page": args.page,
        "purpose": args.purpose,
        "equation_label": args.equation_label,
        "region": region_payload,
        "latex": latex,
        "model": model_name,
        "cache_slot": args.cache_slot,
        "cache_revision_id": None,
        "cache_artifact_sha256": None,
        "cache_write_pending": args.cache_slot is not None,
        "verified": False,
        "warnings": [
            "formula OCR may contain symbol, subscript, superscript, or layout errors",
            "compare material formulas with the original PDF before quoting exactly",
        ],
        "evidence": [evidence],
    }
    return FormulaOCRRun(
        output=output,
        trace_attributes={
            "formula_ocr_schema_version": _TOOL_SCHEMA_VERSION,
            "paper_id": args.paper_id,
            "pdf_sha256": pdf_sha256,
            "page": args.page,
            "region": region_payload,
            "equation_label": args.equation_label,
            "render_sha256": render_sha256,
            "formula_ocr_model": model_name,
            "formula_ocr_output_sha256": hashlib.sha256(
                latex.encode("utf-8")
            ).hexdigest(),
            "cache_slot": args.cache_slot,
            "candidate_id": candidate_id,
            "cache_revision_id": None,
            "cache_artifact_sha256": None,
            "wall_time_seconds": round(time.monotonic() - started, 3),
            "page_evidence": evidence,
        },
    )


async def _accept_formula_candidate(
    args: FormulaOCRInput,
    library_root: Path | None,
    cache_root: Path | None,
) -> FormulaOCRRun:
    assert args.candidate_id is not None
    with _CANDIDATES_LOCK:
        candidate = _CANDIDATES.get(args.candidate_id)
    if candidate is None:
        raise KnowledgeError(
            "formula OCR candidate is unavailable; run recognize again in this "
            "Runtime process"
        )
    if args.paper_id != candidate.requested_paper_id or args.page != candidate.page:
        raise KnowledgeError("accept does not match the recognized paper and page")
    root = _resolve_library_root(library_root)
    pdf_path = await asyncio.to_thread(
        _resolve_paper_path,
        candidate.requested_paper_id,
        root,
    )
    current_pdf_sha256 = await asyncio.to_thread(_sha256_file, pdf_path)
    if current_pdf_sha256 != candidate.pdf_sha256:
        raise KnowledgeError("PDF changed after formula OCR recognition")
    cache_revision_id: str | None = None
    cache_artifact_sha256: str | None = None
    cache_path: str | None = None
    if candidate.cache_slot is not None:
        if cache_root is None:
            raise KnowledgeError("formula OCR acceptance requires a configured cache root")
        cache = PdfTextCache(cache_root.expanduser().resolve())
        lookup = await cache.record_formula_ocr(
            candidate.pdf_sha256,
            page=candidate.page,
            cache_slot=candidate.cache_slot,
            latex=candidate.latex,
            region=candidate.region,
            model=candidate.model,
            render_sha256=candidate.render_sha256,
        )
        if lookup.cache_ref is None or lookup.manifest is None:
            raise KnowledgeError("formula OCR acceptance produced no text cache revision")
        cache_revision_id = lookup.cache_ref.revision_id
        cache_artifact_sha256 = lookup.manifest.artifact.sha256
        cache_path = (
            "cache/"
            f"{lookup.cache_ref.pdf_sha256}/"
            f"{lookup.cache_ref.extractor_fingerprint}/revisions/"
            f"{lookup.cache_ref.revision_id}/{lookup.manifest.artifact.filename}"
        )
    with _CANDIDATES_LOCK:
        _CANDIDATES.pop(candidate.candidate_id, None)
    output = {
        "status": "accepted",
        "candidate_id": candidate.candidate_id,
        "paper_id": candidate.requested_paper_id,
        "page": candidate.page,
        "purpose": candidate.purpose,
        "equation_label": candidate.equation_label,
        "region": candidate.region,
        "latex": candidate.latex,
        "model": candidate.model,
        "cache_slot": candidate.cache_slot,
        "cache_revision_id": cache_revision_id,
        "cache_artifact_sha256": cache_artifact_sha256,
        "cache_path": cache_path,
        "verified": False,
        "warnings": [
            "accepted means the model approved this OCR candidate for caching; it "
            "does not make the LaTeX mathematical ground truth"
        ],
    }
    return FormulaOCRRun(
        output=output,
        trace_attributes={
            "formula_ocr_schema_version": _TOOL_SCHEMA_VERSION,
            "operation": "accept",
            "candidate_id": candidate.candidate_id,
            "paper_id": candidate.requested_paper_id,
            "pdf_sha256": candidate.pdf_sha256,
            "page": candidate.page,
            "region": candidate.region,
            "equation_label": candidate.equation_label,
            "render_sha256": candidate.render_sha256,
            "formula_ocr_model": candidate.model,
            "formula_ocr_output_sha256": hashlib.sha256(
                candidate.latex.encode("utf-8")
            ).hexdigest(),
            "cache_slot": candidate.cache_slot,
            "cache_revision_id": cache_revision_id,
            "cache_artifact_sha256": cache_artifact_sha256,
        },
    )


def _resolve_library_root(library_root: Path | None) -> Path:
    if library_root is None:
        raise KnowledgeError("formula OCR requires a configured PDF library")
    root = library_root.expanduser().resolve()
    if not root.is_dir():
        raise KnowledgeError("configured PDF library is not available")
    return root


def _component_root() -> Path:
    configured = os.environ.get("PAPER_COPILOT_FORMULA_OCR_COMPONENT_ROOT")
    return (
        Path(configured).expanduser().resolve()
        if configured
        else _DEFAULT_COMPONENT_ROOT
    )


def _formula_ocr_helper_path() -> Path | None:
    configured = os.environ.get("PAPER_COPILOT_FORMULA_OCR_HELPER")
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
        return None
    root = _component_root()
    active_path = root / "active.json"
    try:
        raw = json.loads(active_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if raw.get("schema_version") != _COMPONENT_SCHEMA_VERSION:
        return None
    relative_raw = raw.get("helper_relative_path")
    if not isinstance(relative_raw, str) or not relative_raw:
        return None
    relative = Path(relative_raw)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() and os.access(candidate, os.X_OK) else None


def _locate_numbered_formula(
    pdf_path: Path,
    page_number: int,
    equation_label: str | None,
) -> InspectPageRegion:
    if equation_label is None:
        raise KnowledgeError("equation_label is required when region is absent")
    document = pymupdf.open(pdf_path)
    try:
        page = document.load_page(page_number - 1)
        candidates = page.search_for(f"({equation_label})")
        if not candidates:
            raise KnowledgeError(
                f"could not locate equation label ({equation_label}) on page {page_number}"
            )
        label = max(candidates, key=lambda rect: rect.x0)
        page_rect = page.rect
    finally:
        document.close()
    width = page_rect.width
    height = page_rect.height
    column_left = page_rect.x0 if label.x0 < width / 2 else width / 2
    vertical_padding = max(label.height * 2.2, 18.0)
    x1 = max(0.0, (column_left + 8.0) / width)
    x2 = min(1.0, (label.x0 - 5.0) / width)
    y1 = max(0.0, (label.y0 - vertical_padding) / height)
    y2 = min(1.0, (label.y1 + vertical_padding) / height)
    if x2 <= x1 or y2 <= y1:
        raise KnowledgeError("equation label produced an invalid formula crop")
    return InspectPageRegion(x1=x1, y1=y1, x2=x2, y2=y2)


async def _run_helper(helper_path: Path, image_path: Path) -> dict[str, Any]:
    try:
        process = await asyncio.create_subprocess_exec(
            str(helper_path),
            "--image",
            str(image_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={
                **os.environ,
                "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
            },
        )
    except OSError as error:
        raise KnowledgeError("could not start the Formula OCR helper") from error
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=_HELPER_TIMEOUT_SECONDS,
        )
    except TimeoutError as error:
        process.kill()
        await process.wait()
        raise KnowledgeError("Formula OCR helper exceeded its deadline") from error
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise
    if len(stdout) > _MAX_HELPER_OUTPUT_BYTES:
        raise KnowledgeError("Formula OCR helper returned oversized output")
    if process.returncode != 0:
        diagnostic = stderr.decode("utf-8", errors="replace").strip()
        raise KnowledgeError(
            "Formula OCR helper failed: " + (diagnostic[:500] or "no diagnostic output")
        )
    try:
        result = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise KnowledgeError("Formula OCR helper returned invalid JSON") from error
    if not isinstance(result, dict) or result.get("schema_version") != 1:
        raise KnowledgeError("Formula OCR helper returned an unsupported schema")
    return result
