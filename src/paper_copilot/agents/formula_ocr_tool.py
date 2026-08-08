from __future__ import annotations

import atexit
import asyncio
import hashlib
import json
import os
import select
import subprocess
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
    _png_dimensions,
    _render_page,
    _resolve_paper_path,
    _resolve_poppler_executable,
    _sha256_file,
)
from paper_copilot.shared.errors import KnowledgeError, PdfCacheError
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
_HELPER_IDLE_TIMEOUT_SECONDS = 60.0 * 60.0
_HELPER_TERMINATION_GRACE_SECONDS = 2.0
_MAX_HELPER_OUTPUT_BYTES = 64_000
_MAX_HELPER_DIAGNOSTIC_BYTES = 4_000
_HELPER_READ_CHUNK_BYTES = 8_192
# Slot crops are rendered large enough for the recognizer to keep limits and
# scripts; the cap bounds the intermediate full-page render.
_FORMULA_BASE_RENDER_DIMENSION = 1_800
_FORMULA_MAX_RENDER_DIMENSION = 3_600
_FORMULA_MIN_CROP_WIDTH = 700
_FORMULA_MIN_CROP_HEIGHT = 180
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
            "Use this for numbered display equations that have no cache slot "
            "and no known region."
        ),
    )
    region: InspectPageRegion | None = Field(
        default=None,
        description=(
            "Optional normalized formula crop. Only needed to override a stored "
            "slot crop or for formulas without a cache slot."
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
            "Recognize with only the slot when possible: the Runtime crops the "
            "stored formula coordinates automatically. Provide it during "
            "recognize so a later accept can replace that exact location."
        ),
    )
    candidate_id: str | None = Field(
        default=None,
        pattern=r"^formula-candidate-[0-9a-f]{32}$",
        description=(
            "Candidate ID returned by recognize and required by accept. "
            "Accept uses only this ID; any locator fields repeated alongside "
            "it are ignored."
        ),
    )
    refined_latex: str | None = Field(
        default=None,
        max_length=6000,
        description=(
            "Accept only. Optional cleaned copy of the candidate LaTeX: fix "
            "OCR artifacts such as stray prose from an overwide crop or broken "
            "spacing, without changing the mathematics. Omit it to publish the "
            "OCR output unchanged."
        ),
    )

    @model_validator(mode="after")
    def _operation_arguments_match(self) -> FormulaOCRInput:
        if self.operation == "recognize":
            if self.equation_label is not None and self.region is not None:
                raise ValueError(
                    "recognize accepts at most one of equation_label or region"
                )
            if (
                self.equation_label is None
                and self.region is None
                and self.cache_slot is None
            ):
                raise ValueError(
                    "recognize requires equation_label, region, or cache_slot"
                )
            if self.purpose is None:
                raise ValueError("recognize requires purpose")
            if self.candidate_id is not None:
                raise ValueError("recognize does not accept candidate_id")
            if self.refined_latex is not None:
                raise ValueError("recognize does not accept refined_latex")
            return self
        if self.candidate_id is None:
            raise ValueError("accept requires candidate_id")
        if self.refined_latex is not None:
            _validate_refined_latex(self.refined_latex)
        # Accept silently ignores repeated locator fields: models commonly echo
        # cache_slot/purpose/region back, and the frozen candidate remains the
        # only trust anchor for what gets published.
        return self


@dataclass(frozen=True, slots=True)
class FormulaOCRRun:
    output: dict[str, Any]
    trace_attributes: dict[str, Any]


def _validate_refined_latex(value: str) -> None:
    """Reject refined LaTeX that could corrupt the text cache.

    The published text is spliced into layout.txt, so marker-like sequences
    and control characters are forbidden regardless of prompt wording.
    """
    if not value.strip():
        raise ValueError("refined_latex must not be empty")
    if "[[" in value:
        raise ValueError("refined_latex must not contain marker sequences")
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ValueError("refined_latex must not contain control characters")


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


class _FormulaOCRHelperFailure(Exception):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        discard_process: bool,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.discard_process = discard_process


class _FormulaOCRRequestCancelled(Exception):
    pass


class _FormulaOCRHelperProcess:
    def __init__(self, helper_path: Path) -> None:
        self.helper_path = helper_path
        try:
            self.process = subprocess.Popen(
                [
                    str(helper_path),
                    "--serve",
                    "--idle-timeout-seconds",
                    str(_HELPER_IDLE_TIMEOUT_SECONDS),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={
                    **os.environ,
                    "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
                },
                start_new_session=True,
            )
        except OSError as error:
            raise _FormulaOCRHelperFailure(
                "could not start the Formula OCR helper",
                retryable=False,
                discard_process=True,
            ) from error
        if (
            self.process.stdin is None
            or self.process.stdout is None
            or self.process.stderr is None
        ):
            self.terminate()
            raise _FormulaOCRHelperFailure(
                "Formula OCR helper did not expose its protocol streams",
                retryable=False,
                discard_process=True,
            )
        self._stderr_lock = threading.Lock()
        self._stderr_tail = bytearray()
        self._stderr_reader = threading.Thread(
            target=self._drain_stderr,
            name="paper-copilot-formula-ocr-stderr",
            daemon=True,
        )
        self._stderr_reader.start()

    def request(self, image_path: Path) -> dict[str, Any]:
        if self.process.poll() is not None:
            raise _FormulaOCRHelperFailure(
                "Formula OCR helper exited before the request",
                retryable=True,
                discard_process=True,
            )
        request_id = uuid4().hex
        request = json.dumps(
            {
                "schema_version": 1,
                "request_id": request_id,
                "image": str(image_path),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        stdin = self.process.stdin
        assert stdin is not None
        try:
            stdin.write(request)
            stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise _FormulaOCRHelperFailure(
                "Formula OCR helper closed stdin",
                retryable=True,
                discard_process=True,
            ) from error
        response_bytes = self._read_response()
        try:
            response = json.loads(response_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise _FormulaOCRHelperFailure(
                "Formula OCR helper returned invalid JSON",
                retryable=True,
                discard_process=True,
            ) from error
        if not isinstance(response, dict) or response.get("schema_version") != 1:
            raise _FormulaOCRHelperFailure(
                "Formula OCR helper returned an unsupported schema",
                retryable=True,
                discard_process=True,
            )
        if response.get("request_id") != request_id:
            raise _FormulaOCRHelperFailure(
                "Formula OCR helper response did not match its request",
                retryable=True,
                discard_process=True,
            )
        error_message = response.get("error")
        if error_message is not None:
            diagnostic = (
                error_message
                if isinstance(error_message, str) and error_message
                else "no diagnostic output"
            )
            raise _FormulaOCRHelperFailure(
                "Formula OCR helper failed: " + diagnostic[:500],
                retryable=False,
                discard_process=False,
            )
        return response

    def diagnostic(self) -> str:
        with self._stderr_lock:
            return self._stderr_tail.decode("utf-8", errors="replace").strip()

    def terminate(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=_HELPER_TERMINATION_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None and not stream.closed:
                stream.close()

    def _read_response(self) -> bytes:
        stdout = self.process.stdout
        assert stdout is not None
        deadline = time.monotonic() + _HELPER_TIMEOUT_SECONDS
        response = bytearray()
        while True:
            newline_at = response.find(b"\n")
            if newline_at >= 0:
                if response[newline_at + 1 :]:
                    raise _FormulaOCRHelperFailure(
                        "Formula OCR helper returned multiple protocol records",
                        retryable=True,
                        discard_process=True,
                    )
                return bytes(response[:newline_at])
            if len(response) > _MAX_HELPER_OUTPUT_BYTES:
                raise _FormulaOCRHelperFailure(
                    "Formula OCR helper returned oversized output",
                    retryable=False,
                    discard_process=True,
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _FormulaOCRHelperFailure(
                    "Formula OCR helper exceeded its deadline",
                    retryable=False,
                    discard_process=True,
                )
            readable, _, _ = select.select([stdout.fileno()], [], [], remaining)
            if not readable:
                raise _FormulaOCRHelperFailure(
                    "Formula OCR helper exceeded its deadline",
                    retryable=False,
                    discard_process=True,
                )
            chunk = os.read(stdout.fileno(), _HELPER_READ_CHUNK_BYTES)
            if not chunk:
                self._stderr_reader.join(timeout=0.2)
                raise _FormulaOCRHelperFailure(
                    "Formula OCR helper closed stdout",
                    retryable=True,
                    discard_process=True,
                )
            response.extend(chunk)

    def _drain_stderr(self) -> None:
        stderr = self.process.stderr
        assert stderr is not None
        while chunk := stderr.read(_HELPER_READ_CHUNK_BYTES):
            with self._stderr_lock:
                self._stderr_tail.extend(chunk)
                excess = len(self._stderr_tail) - _MAX_HELPER_DIAGNOSTIC_BYTES
                if excess > 0:
                    del self._stderr_tail[:excess]


class _FormulaOCRHelperPool:
    def __init__(self) -> None:
        self._request_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._process: _FormulaOCRHelperProcess | None = None
        self._active_cancellation: threading.Event | None = None

    def request(
        self,
        helper_path: Path,
        image_path: Path,
        cancellation: threading.Event,
    ) -> dict[str, Any]:
        with self._request_lock:
            if cancellation.is_set():
                raise _FormulaOCRRequestCancelled
            for attempt in range(2):
                try:
                    process = self._get_or_start(helper_path)
                except _FormulaOCRHelperFailure as error:
                    raise KnowledgeError(str(error)) from error
                with self._state_lock:
                    if cancellation.is_set():
                        raise _FormulaOCRRequestCancelled
                    self._active_cancellation = cancellation
                try:
                    return process.request(image_path)
                except _FormulaOCRHelperFailure as error:
                    if cancellation.is_set():
                        raise _FormulaOCRRequestCancelled from error
                    diagnostic = process.diagnostic()
                    if error.discard_process:
                        self._discard(process)
                    if error.retryable and attempt == 0:
                        continue
                    message = str(error)
                    if diagnostic and "failed:" not in message:
                        message += ": " + diagnostic[-500:]
                    raise KnowledgeError(message) from error
                finally:
                    with self._state_lock:
                        if self._active_cancellation is cancellation:
                            self._active_cancellation = None
        raise AssertionError("formula OCR helper retry loop did not return")

    def cancel(self, cancellation: threading.Event) -> None:
        cancellation.set()
        with self._state_lock:
            if self._active_cancellation is not cancellation:
                return
            process = self._process
            self._process = None
        if process is not None:
            process.terminate()

    def terminate(self) -> None:
        with self._state_lock:
            process = self._process
            self._process = None
        if process is not None:
            process.terminate()

    def _get_or_start(self, helper_path: Path) -> _FormulaOCRHelperProcess:
        with self._state_lock:
            process = self._process
            if (
                process is not None
                and process.helper_path == helper_path
                and process.process.poll() is None
            ):
                return process
            if process is not None:
                self._process = None
                process.terminate()
            process = _FormulaOCRHelperProcess(helper_path)
            self._process = process
            return process

    def _discard(self, process: _FormulaOCRHelperProcess) -> None:
        with self._state_lock:
            if self._process is process:
                self._process = None
        process.terminate()


_FORMULA_OCR_HELPERS = _FormulaOCRHelperPool()
atexit.register(_FORMULA_OCR_HELPERS.terminate)
_LEGACY_HELPER_SIGNATURES: set[tuple[Path, int, int, int]] = set()
_LEGACY_HELPER_SIGNATURES_LOCK = threading.Lock()


def formula_ocr_tool_description() -> str:
    return (
        "Recognize and optionally accept one formula from an authorized local PDF. "
        "Use this only when the current task requires understanding or citing a "
        "specific formula, that formula is corrupted or flattened in extracted PDF "
        "text, and the configured language model cannot inspect images. Do not call "
        "this tool merely because unrelated garbled text or formula slots exist. Identify "
        "the exact physical page first, then provide the cache_slot shown beside "
        "the garbled formula (preferred; the crop is automatic), or a printed "
        "equation label, or a normalized formula region. recognize returns a candidate without "
        "changing the cache. Inspect its LaTeX; only when it is acceptable call this "
        "tool again with operation=accept and candidate_id, optionally passing a "
        "cleaned copy of the LaTeX as refined_latex when OCR artifacts pollute it. "
        "If layout.txt showed a "
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
    region: InspectPageRegion | None = args.region
    region_source = "provided"
    if region is None and args.cache_slot is not None:
        slot_bbox = await _lookup_slot_bbox(
            pdf_sha256,
            page=args.page,
            cache_slot=args.cache_slot,
            cache_root=cache_root,
        )
        if slot_bbox is not None:
            region = InspectPageRegion(**slot_bbox)
            region_source = "cache_slot_bbox"
    if region is None:
        if args.equation_label is None:
            raise KnowledgeError(
                f"cache slot {args.cache_slot} has no stored crop coordinates in "
                "the text cache; pass region or equation_label instead"
            )
        region = await asyncio.to_thread(
            _locate_numbered_formula,
            pdf_path,
            args.page,
            args.equation_label,
        )
        region_source = "equation_label"
    started = time.monotonic()
    pdftoppm_path = _resolve_poppler_executable("pdftoppm")
    with tempfile.TemporaryDirectory(prefix="paper-copilot-formula-ocr-") as raw_dir:
        render_path = await _render_formula_crop(
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
        "region_source": region_source,
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
            "region_source": region_source,
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
    published_latex = (
        args.refined_latex.strip() if args.refined_latex else candidate.latex
    )
    refined = published_latex != candidate.latex
    if candidate.cache_slot is not None:
        if cache_root is None:
            raise KnowledgeError("formula OCR acceptance requires a configured cache root")
        cache = PdfTextCache(cache_root.expanduser().resolve())
        lookup = await cache.record_formula_ocr(
            candidate.pdf_sha256,
            page=candidate.page,
            cache_slot=candidate.cache_slot,
            latex=published_latex,
            ocr_latex=candidate.latex,
            region=candidate.region,
            model=candidate.model,
            render_sha256=candidate.render_sha256,
            equation_label=candidate.equation_label,
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
        "latex": published_latex,
        "ocr_latex": candidate.latex,
        "refined": refined,
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
            "refined": refined,
            "published_latex_sha256": hashlib.sha256(
                published_latex.encode("utf-8")
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


async def _lookup_slot_bbox(
    pdf_sha256: str,
    *,
    page: int,
    cache_slot: str,
    cache_root: Path | None,
) -> dict[str, float] | None:
    """Return the stored slot crop, or None when unavailable.

    A missing cache or unreadable revision degrades to the explicit-locator
    path instead of failing recognition outright.
    """
    if cache_root is None:
        return None
    cache = PdfTextCache(cache_root.expanduser().resolve())
    try:
        return await cache.slot_bbox(pdf_sha256, page=page, cache_slot=cache_slot)
    except PdfCacheError:
        return None


async def _render_formula_crop(
    pdftoppm_path: Path,
    pdf_path: Path,
    *,
    page: int,
    region: InspectPageRegion,
    render_dir: Path,
) -> Path:
    """Render the region, upscaling the page until the crop is OCR-friendly.

    Display formulas occupy a thin band of a full-page render; at the base
    scale their scripts and operator limits blur below the recognizer's
    threshold, so the page is re-rendered larger when the crop is too small.
    """
    full_path = await _render_page(
        pdftoppm_path,
        pdf_path,
        page=page,
        region=None,
        render_dir=render_dir,
        scale_to=_FORMULA_BASE_RENDER_DIMENSION,
    )
    full_bytes = await asyncio.to_thread(full_path.read_bytes)
    width, height = _png_dimensions(
        full_bytes,
        max_dimension=_FORMULA_BASE_RENDER_DIMENSION,
    )
    crop_width = (region.x2 - region.x1) * width
    crop_height = (region.y2 - region.y1) * height
    factor = max(
        1.0,
        _FORMULA_MIN_CROP_WIDTH / max(crop_width, 1.0),
        _FORMULA_MIN_CROP_HEIGHT / max(crop_height, 1.0),
    )
    scale = min(
        int(_FORMULA_BASE_RENDER_DIMENSION * factor + 0.5),
        _FORMULA_MAX_RENDER_DIMENSION,
    )
    return await _render_page(
        pdftoppm_path,
        pdf_path,
        page=page,
        region=region,
        render_dir=render_dir,
        scale_to=scale,
    )


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
        content_bbox = _formula_content_bbox(page, label)
        if content_bbox is not None:
            width = page_rect.width
            height = page_rect.height
            padding = 3.0
            x1 = max(0.0, (content_bbox[0] - padding) / width)
            y1 = max(0.0, (content_bbox[1] - padding) / height)
            x2 = min(1.0, (content_bbox[2] + padding) / width)
            y2 = min(1.0, (content_bbox[3] + padding) / height)
            if x2 > x1 and y2 > y1:
                return InspectPageRegion(x1=x1, y1=y1, x2=x2, y2=y2)
        # Fall back to the label-anchored column heuristic when the PDF has no
        # usable text-layer geometry beside the label (for example vector-only
        # equations). Geometry-based crops cover centered single-column
        # equations that the legacy column assumption would truncate.
        return _legacy_label_region(label, page_rect)
    finally:
        document.close()


_WORD_TUPLE = tuple[float, float, float, float, str, int, int, int]


def _formula_content_bbox(
    page: pymupdf.Page,
    label: pymupdf.Rect,
) -> tuple[float, float, float, float] | None:
    """Return the union box of text-layer words belonging to the labelled formula.

    The label rect anchors the equation line; words whose vertical center lies
    within one label height of it are clustered from the label leftwards. The
    box then expands to nearby visual text rows only when the whole row stays
    horizontally inside the equation box. This works for single-column centered
    equations, two-column layouts, and sub/superscript or fraction rows without
    assuming a page-half column boundary.
    """
    words = page.get_text("words")
    vertical_tolerance = max(label.height * 0.6, 5.0)
    gap_tolerance = max(label.height * 1.0, 14.0)
    center = (label.y0 + label.y1) / 2.0
    candidates = [
        word
        for word in words
        if abs((word[1] + word[3]) / 2 - center) <= label.height
        and word[2] <= label.x0 - 2.0
    ]
    if not candidates:
        return None
    ordered = sorted(candidates, key=lambda word: word[0])
    clusters: list[list[_WORD_TUPLE]] = []
    for word in ordered:
        if clusters and word[0] - clusters[-1][-1][2] <= gap_tolerance:
            clusters[-1].append(word)
        else:
            clusters.append([word])
    cluster = max(clusters, key=lambda candidate: max(word[2] for word in candidate))
    bbox = [
        min(word[0] for word in cluster),
        min(word[1] for word in cluster),
        max(word[2] for word in cluster),
        max(word[3] for word in cluster),
    ]
    included = {id(word) for word in cluster}
    rows = _formula_visual_rows(page, words, label.x0)
    changed = True
    while changed:
        changed = False
        for row_box, row_words in rows:
            if all(id(word) in included for word in row_words):
                continue
            if (
                row_box[1] > bbox[3] + vertical_tolerance
                or row_box[3] < bbox[1] - vertical_tolerance
            ):
                continue
            if (
                row_box[0] < bbox[0] - gap_tolerance
                or row_box[2] > bbox[2] + gap_tolerance
            ):
                continue
            for word in row_words:
                included.add(id(word))
            bbox[0] = min(bbox[0], row_box[0])
            bbox[1] = min(bbox[1], row_box[1])
            bbox[2] = max(bbox[2], row_box[2])
            bbox[3] = max(bbox[3], row_box[3])
            changed = True
    return (bbox[0], bbox[1], bbox[2], bbox[3])


def _formula_visual_rows(
    page: pymupdf.Page,
    words: list[_WORD_TUPLE],
    label_x0: float,
) -> list[tuple[list[float], list[_WORD_TUPLE]]]:
    """Merge dict lines into visual rows for equation-content containment.

    Dict lines are the extractor's own text-line fragments. Adjacent fragments
    that overlap vertically by more than two points belong to the same visual
    row; a full-width paragraph row therefore fails horizontal containment even
    when one of its inline-math fragments fits inside the equation box.
    """
    rows: list[tuple[list[float], list[_WORD_TUPLE]]] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            line_box = line["bbox"]
            line_words = [
                word
                for word in words
                if word[2] <= label_x0 - 2.0
                and line_box[0] - 0.5 <= word[0]
                and word[2] <= line_box[2] + 0.5
                and line_box[1] - 0.5 <= word[1]
                and word[3] <= line_box[3] + 0.5
            ]
            if not line_words:
                continue
            merged = False
            for row_box, row_words in rows:
                if (
                    line_box[1] <= row_box[3] - 2.0
                    and line_box[3] >= row_box[1] + 2.0
                ):
                    row_box[0] = min(row_box[0], line_box[0])
                    row_box[1] = min(row_box[1], line_box[1])
                    row_box[2] = max(row_box[2], line_box[2])
                    row_box[3] = max(row_box[3], line_box[3])
                    row_words.extend(line_words)
                    merged = True
                    break
            if not merged:
                rows.append(
                    (
                        [line_box[0], line_box[1], line_box[2], line_box[3]],
                        line_words,
                    )
                )
    return rows


def _legacy_label_region(
    label: pymupdf.Rect,
    page_rect: pymupdf.Rect,
) -> InspectPageRegion:
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
        helper_signature = _helper_binary_signature(helper_path)
    except OSError as error:
        raise KnowledgeError("could not inspect the Formula OCR helper") from error
    with _LEGACY_HELPER_SIGNATURES_LOCK:
        use_one_shot = helper_signature in _LEGACY_HELPER_SIGNATURES
    if use_one_shot:
        return await _run_helper_once(helper_path, image_path)
    cancellation = threading.Event()
    try:
        try:
            result = await asyncio.to_thread(
                _FORMULA_OCR_HELPERS.request,
                helper_path,
                image_path,
                cancellation,
            )
        except KnowledgeError as error:
            if not _helper_server_is_unsupported(str(error)):
                raise
            with _LEGACY_HELPER_SIGNATURES_LOCK:
                _LEGACY_HELPER_SIGNATURES.add(helper_signature)
            result = await _run_helper_once(helper_path, image_path)
    except asyncio.CancelledError:
        _FORMULA_OCR_HELPERS.cancel(cancellation)
        raise
    if not isinstance(result, dict) or result.get("schema_version") != 1:
        raise KnowledgeError("Formula OCR helper returned an unsupported schema")
    return result


def _helper_binary_signature(helper_path: Path) -> tuple[Path, int, int, int]:
    stat = helper_path.stat()
    return (helper_path, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def _helper_server_is_unsupported(diagnostic: str) -> bool:
    return "--serve" in diagnostic and (
        "unrecognized arguments" in diagnostic
        or "the following arguments are required" in diagnostic
    )


async def _run_helper_once(helper_path: Path, image_path: Path) -> dict[str, Any]:
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
