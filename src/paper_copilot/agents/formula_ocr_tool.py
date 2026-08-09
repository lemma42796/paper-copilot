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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

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
from paper_copilot.shared.errors import KnowledgeError
from paper_copilot.shared.pdf_cache import FormulaTargetSnapshot, PdfTextCache

__all__ = [
    "FormulaOCRInput",
    "FormulaOCRRun",
    "formula_ocr_available",
    "formula_ocr_tool_description",
    "run_formula_ocr",
]

_COMPONENT_SCHEMA_VERSION = 2
_TOOL_SCHEMA_VERSION = 2
_HELPER_TIMEOUT_SECONDS = 120.0
_HELPER_IDLE_TIMEOUT_SECONDS = 60.0 * 60.0
_HELPER_TERMINATION_GRACE_SECONDS = 2.0
_MAX_HELPER_OUTPUT_BYTES = 64_000
_MAX_HELPER_DIAGNOSTIC_BYTES = 4_000
_HELPER_READ_CHUNK_BYTES = 8_192
# Formula crops are rendered large enough for the recognizer to keep limits
# and scripts; the cap bounds the intermediate full-page render.
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
    formula_ref: str | None = Field(
        default=None,
        min_length=1,
        max_length=300,
        description=(
            "Stable identity for the same physical formula, such as 'equation (3.5)' "
            "or a distinctive nearby prose fragment. Reuse it unchanged for every "
            "crop refinement so the Runtime can enforce the attempt limit."
        ),
    )
    region: InspectPageRegion | None = Field(
        default=None,
        description=(
            "Explicit normalized formula crop selected after coordinate exploration. "
            "Cached hints and printed labels never become automatic crops."
        ),
    )
    purpose: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        description="Specific formula that needs local OCR verification.",
    )
    repair_span_id: str | None = Field(
        default=None,
        pattern=r"^page-[0-9]{4}-repair-[0-9]{4}$",
        description=(
            "Stable replacement span shown beside damaged formula text. This grants "
            "permission to replace that cache span after acceptance but does not "
            "supply OCR coordinates."
        ),
    )
    replacement_text: str | None = Field(
        default=None,
        min_length=1,
        max_length=6000,
        description=(
            "Exact whole formula currently present on the cached page. Use for a "
            "readable formula suspected of silently missing symbols; acceptance "
            "replaces it only if this frozen text still matches uniquely."
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
            "spacing, without changing the mathematics. Provide the formula body "
            "without outer $$ or \\[...\\] delimiters. Omit it to publish the OCR "
            "output unchanged when it is already a valid body."
        ),
    )

    @model_validator(mode="after")
    def _operation_arguments_match(self) -> FormulaOCRInput:
        if self.operation == "recognize":
            if self.region is None:
                raise ValueError("recognize requires an explicit region")
            if self.formula_ref is None:
                raise ValueError("recognize requires formula_ref")
            if self.purpose is None:
                raise ValueError("recognize requires purpose")
            if self.repair_span_id is not None and self.replacement_text is not None:
                raise ValueError(
                    "recognize accepts at most one of repair_span_id or replacement_text"
                )
            if self.replacement_text is not None:
                _validate_replacement_text(self.replacement_text)
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
        # repair_span_id/purpose/region back, and the frozen candidate remains the
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
    stripped = value.strip()
    if (
        stripped.startswith("$$")
        or stripped.endswith("$$")
        or stripped.startswith(r"\[")
        or stripped.endswith(r"\]")
    ):
        raise ValueError("refined_latex must not include outer display delimiters")
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ValueError("refined_latex must not contain control characters")


def _validate_replacement_text(value: str) -> None:
    if not value.strip():
        raise ValueError("replacement_text must not be empty")
    if "[[" in value or "\f" in value:
        raise ValueError("replacement_text must not contain cache markers")


@dataclass(frozen=True, slots=True)
class _FormulaOCRCandidate:
    candidate_id: str
    requested_paper_id: str
    pdf_sha256: str
    page: int
    purpose: str
    formula_ref: str
    region: dict[str, float]
    latex: str
    model: str
    render_sha256: str
    repair_span_id: str | None
    replacement_text: str | None
    target_snapshot: FormulaTargetSnapshot | None


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
        "Use it only when the user asks to explain or verify a specific formula, or "
        "when the current task materially requires exact formula structure that cached "
        "text cannot establish. Never call it merely because unrelated damage exists. "
        "recognize requires a model-selected explicit region and a stable formula_ref; "
        "printed labels and cached hints do not choose a crop. The Runtime permits at "
        "most three recognize attempts for the same formula in one task. Inspect each "
        "candidate and adjust the crop only when useful. accept publishes cleaned display "
        "LaTeX through a frozen repair_span_id or exact whole-formula replacement_text. "
        "Results remain unverified OCR evidence."
    )


def formula_ocr_available() -> bool:
    return _formula_ocr_helper_path() is not None


async def run_formula_ocr(
    args: FormulaOCRInput,
    library_root: Path | None,
    *,
    cache_root: Path | None = None,
    on_recognize_attempt: Callable[[], None] | None = None,
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
    assert args.region is not None
    assert args.formula_ref is not None
    region = args.region
    target_snapshot: FormulaTargetSnapshot | None = None
    if args.repair_span_id is not None or args.replacement_text is not None:
        if cache_root is None:
            raise KnowledgeError("formula targeting requires a configured cache root")
        cache = PdfTextCache(cache_root.expanduser().resolve())
        target_snapshot = await cache.snapshot_formula_target(
            pdf_sha256,
            page=args.page,
            repair_span_id=args.repair_span_id,
            replacement_text=args.replacement_text,
        )
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
        if on_recognize_attempt is not None:
            on_recognize_attempt()
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
    latex_body = latex.strip()
    region_payload = region.model_dump(mode="json")
    candidate_id = f"formula-candidate-{uuid4().hex}"
    candidate = _FormulaOCRCandidate(
        candidate_id=candidate_id,
        requested_paper_id=args.paper_id,
        pdf_sha256=pdf_sha256,
        page=args.page,
        purpose=args.purpose or "",
        formula_ref=args.formula_ref,
        region=region_payload,
        latex=latex_body,
        model=model_name,
        render_sha256=render_sha256,
        repair_span_id=args.repair_span_id,
        replacement_text=args.replacement_text,
        target_snapshot=target_snapshot,
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
        "cache_revision_id": (
            target_snapshot.cache_revision_id
            if target_snapshot is not None
            else None
        ),
        "render_sha256": render_sha256,
    }
    output = {
        "status": "recognized_pending_acceptance",
        "candidate_id": candidate_id,
        "paper_id": args.paper_id,
        "page": args.page,
        "region_source": "model_selected",
        "purpose": args.purpose,
        "formula_ref": args.formula_ref,
        "region": region_payload,
        "latex": latex_body,
        "model": model_name,
        "repair_span_id": args.repair_span_id,
        "target_kind": (
            target_snapshot.target_kind if target_snapshot is not None else None
        ),
        "target_sha256": (
            target_snapshot.target_sha256 if target_snapshot is not None else None
        ),
        "cache_revision_id": (
            target_snapshot.cache_revision_id
            if target_snapshot is not None
            else None
        ),
        "cache_artifact_sha256": (
            target_snapshot.cache_artifact_sha256
            if target_snapshot is not None
            else None
        ),
        "cache_write_pending": target_snapshot is not None,
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
            "region_source": "model_selected",
            "formula_ref_sha256": hashlib.sha256(
                args.formula_ref.encode("utf-8")
            ).hexdigest(),
            "render_sha256": render_sha256,
            "formula_ocr_model": model_name,
            "formula_ocr_output_sha256": hashlib.sha256(
                latex_body.encode("utf-8")
            ).hexdigest(),
            "repair_span_id": args.repair_span_id,
            "target_kind": (
                target_snapshot.target_kind if target_snapshot is not None else None
            ),
            "target_sha256": (
                target_snapshot.target_sha256 if target_snapshot is not None else None
            ),
            "candidate_id": candidate_id,
            "cache_revision_id": (
                target_snapshot.cache_revision_id
                if target_snapshot is not None
                else None
            ),
            "cache_artifact_sha256": (
                target_snapshot.cache_artifact_sha256
                if target_snapshot is not None
                else None
            ),
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
    _validate_refined_latex(published_latex)
    refined = published_latex != candidate.latex
    if candidate.target_snapshot is None:
        raise KnowledgeError(
            "this candidate has no frozen cache target; use its LaTeX as evidence "
            "without accepting it"
        )
    if cache_root is None:
        raise KnowledgeError("formula OCR acceptance requires a configured cache root")
    cache = PdfTextCache(cache_root.expanduser().resolve())
    lookup = await cache.record_formula_latex(
        candidate.pdf_sha256,
        page=candidate.page,
        repair_span_id=candidate.repair_span_id,
        replacement_text=candidate.replacement_text,
        expected_target_sha256=candidate.target_snapshot.target_sha256,
        latex=published_latex,
        ocr_latex=candidate.latex,
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
        "formula_ref": candidate.formula_ref,
        "region": candidate.region,
        "latex": published_latex,
        "ocr_latex": candidate.latex,
        "refined": refined,
        "model": candidate.model,
        "repair_span_id": candidate.repair_span_id,
        "target_kind": candidate.target_snapshot.target_kind,
        "target_sha256": candidate.target_snapshot.target_sha256,
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
            "formula_ref_sha256": hashlib.sha256(
                candidate.formula_ref.encode("utf-8")
            ).hexdigest(),
            "render_sha256": candidate.render_sha256,
            "formula_ocr_model": candidate.model,
            "formula_ocr_output_sha256": hashlib.sha256(
                candidate.latex.encode("utf-8")
            ).hexdigest(),
            "refined": refined,
            "published_latex_sha256": hashlib.sha256(
                published_latex.encode("utf-8")
            ).hexdigest(),
            "repair_span_id": candidate.repair_span_id,
            "target_kind": candidate.target_snapshot.target_kind,
            "target_sha256": candidate.target_snapshot.target_sha256,
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
