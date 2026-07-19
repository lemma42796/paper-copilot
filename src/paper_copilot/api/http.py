from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from paper_copilot.agents.composer_library import load_composer_library
from paper_copilot.chat.evidence import EvidenceChunk, EvidenceField, lookup_evidence_ref
from paper_copilot.chat.history import ChatReportItem, list_chat_reports
from paper_copilot.chat.runtime import ChatRunResult, handle_chat_request
from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.session.paths import default_root
from paper_copilot.shared.errors import ApiError, PaperCopilotError


class ChatHttpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    pdf_dir: Path | None = None
    max_turns: int = Field(default=16, ge=1)
    budget_cny: float = Field(default=2.0, gt=0)
    max_papers: int = Field(default=5, ge=1)
    root: Path | None = None
    record_quality: bool = True
    update_report: bool = True


class ReportsHttpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: Path | None = None
    limit: int = Field(default=20, ge=1, le=100)


class EvidenceHttpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str = Field(min_length=1)
    root: Path | None = None


class ComposerLibraryHttpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pdf_dir: Path
    root: Path | None = None
    limit: int = Field(default=20, ge=1, le=200)


class ChatHttpResponse(BaseModel):
    request: str
    report_markdown: str
    session_path: str
    report_path: str
    quality_run_path: str | None
    eval_report_path: str | None
    termination_reason: str
    cost_cny: float
    events_count: int
    paper_budget: dict[str, object]
    composer_plan: dict[str, Any] | None
    proposal_check: dict[str, Any] | None

    @classmethod
    def from_result(cls, result: ChatRunResult) -> ChatHttpResponse:
        return cls(
            request=result.request,
            report_markdown=result.report_markdown,
            session_path=str(result.session_path),
            report_path=str(result.report_path),
            quality_run_path=(
                str(result.quality_run_path) if result.quality_run_path is not None else None
            ),
            eval_report_path=(
                str(result.eval_report_path) if result.eval_report_path is not None else None
            ),
            termination_reason=result.termination_reason,
            cost_cny=result.cost_cny,
            events_count=result.events_count,
            paper_budget=result.paper_budget,
            composer_plan=result.composer_plan,
            proposal_check=result.proposal_check,
        )


class ChatReportHttpItem(BaseModel):
    id: str
    request: str
    report_markdown: str
    session_path: str
    report_path: str
    updated_at: str
    termination_reason: str
    cost_cny: float | None
    events_count: int | None
    paper_budget: dict[str, object]
    composer_plan: dict[str, Any] | None
    proposal_check: dict[str, Any] | None

    @classmethod
    def from_item(cls, item: ChatReportItem) -> ChatReportHttpItem:
        return cls(
            id=item.id,
            request=item.request,
            report_markdown=item.report_markdown,
            session_path=str(item.session_path),
            report_path=str(item.report_path),
            updated_at=item.updated_at,
            termination_reason=item.termination_reason,
            cost_cny=item.cost_cny,
            events_count=item.events_count,
            paper_budget=item.paper_budget,
            composer_plan=item.composer_plan,
            proposal_check=item.proposal_check,
        )


class ChatReportsHttpResponse(BaseModel):
    reports: list[ChatReportHttpItem]

    @classmethod
    def from_items(cls, items: list[ChatReportItem]) -> ChatReportsHttpResponse:
        return cls(reports=[ChatReportHttpItem.from_item(item) for item in items])


class DirectorySelectionHttpResponse(BaseModel):
    path: str | None


class EvidenceHttpResponse(BaseModel):
    kind: str
    citation_ref: str
    paper_id: str
    title: str
    year: int | None
    chunk_id: int | None
    section: str | None
    page_start: int | None
    page_end: int | None
    field: str | None
    text: str

    @classmethod
    def from_chunk(cls, chunk: EvidenceChunk) -> EvidenceHttpResponse:
        return cls(
            kind="chunk",
            citation_ref=chunk.citation_ref,
            paper_id=chunk.paper_id,
            title=chunk.title,
            year=chunk.year,
            chunk_id=chunk.chunk_id,
            section=chunk.section,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            field=None,
            text=chunk.text,
        )

    @classmethod
    def from_field(cls, field: EvidenceField) -> EvidenceHttpResponse:
        return cls(
            kind="field",
            citation_ref=field.citation_ref,
            paper_id=field.paper_id,
            title=field.title,
            year=field.year,
            chunk_id=None,
            section=None,
            page_start=None,
            page_end=None,
            field=field.field,
            text=field.text,
        )

    @classmethod
    def from_evidence(
        cls, evidence: EvidenceChunk | EvidenceField
    ) -> EvidenceHttpResponse:
        if isinstance(evidence, EvidenceChunk):
            return cls.from_chunk(evidence)
        return cls.from_field(evidence)


def serve_http_api(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), _ChatHandler)
    server.serve_forever()


class _ChatHandler(BaseHTTPRequestHandler):
    server_version = "PaperCopilotHTTP/0.1"

    def do_OPTIONS(self) -> None:
        self._write_json(HTTPStatus.NO_CONTENT, None)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._write_json(HTTPStatus.OK, {"status": "ok"})
            return
        if parsed.path == "/reports":
            try:
                request = ReportsHttpRequest.model_validate(_single_query_values(parsed.query))
                response = ChatReportsHttpResponse.from_items(
                    list_chat_reports(root=request.root, limit=request.limit)
                )
            except ValidationError as exc:
                self._write_error(HTTPStatus.BAD_REQUEST, "bad_request", str(exc))
                return
            self._write_json(HTTPStatus.OK, response.model_dump(mode="json"))
            return
        if parsed.path == "/evidence":
            try:
                request = EvidenceHttpRequest.model_validate(_single_query_values(parsed.query))
                evidence = lookup_evidence_ref(request.ref, root=request.root)
                response = EvidenceHttpResponse.from_evidence(evidence)
            except ValidationError as exc:
                self._write_error(HTTPStatus.BAD_REQUEST, "bad_request", str(exc))
                return
            except PaperCopilotError as exc:
                self._write_error(HTTPStatus.BAD_REQUEST, exc.__class__.__name__, str(exc))
                return
            self._write_json(HTTPStatus.OK, response.model_dump(mode="json"))
            return
        if parsed.path == "/composer/library":
            try:
                request = ComposerLibraryHttpRequest.model_validate(
                    _single_query_values(parsed.query)
                )
                response = _composer_library_payload(request)
            except ValidationError as exc:
                self._write_error(HTTPStatus.BAD_REQUEST, "bad_request", str(exc))
                return
            except PaperCopilotError as exc:
                self._write_error(HTTPStatus.BAD_REQUEST, exc.__class__.__name__, str(exc))
                return
            self._write_json(HTTPStatus.OK, response)
            return
        self._write_error(HTTPStatus.NOT_FOUND, "not_found", f"unknown path: {parsed.path}")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/library/select-directory":
            self._handle_select_directory()
            return
        if parsed.path == "/chat":
            self._handle_chat()
            return

        self._write_error(HTTPStatus.NOT_FOUND, "not_found", f"unknown path: {parsed.path}")

    def _handle_chat(self) -> None:
        try:
            request = ChatHttpRequest.model_validate(self._read_json_body())
        except ValidationError as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, "bad_request", str(exc))
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, "invalid_json", str(exc))
            return

        try:
            result = asyncio.run(
                handle_chat_request(
                    request.message,
                    pdf_dir=request.pdf_dir,
                    max_turns=request.max_turns,
                    budget_cny=request.budget_cny,
                    max_papers=request.max_papers,
                    root=request.root,
                    record_quality=request.record_quality,
                    update_report=request.update_report,
                )
            )
        except PaperCopilotError as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, exc.__class__.__name__, str(exc))
            return

        self._write_json(
            HTTPStatus.OK,
            ChatHttpResponse.from_result(result).model_dump(mode="json"),
        )

    def _handle_select_directory(self) -> None:
        try:
            path = _select_directory()
        except ApiError as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, exc.__class__.__name__, str(exc))
            return

        response = DirectorySelectionHttpResponse(
            path=str(path) if path is not None else None
        )
        self._write_json(HTTPStatus.OK, response.model_dump(mode="json"))

    def _read_json_body(self) -> dict[str, Any]:
        length_raw = self.headers.get("Content-Length", "0")
        length = int(length_raw)
        body = self.rfile.read(length).decode("utf-8")
        raw = json.loads(body or "{}")
        if not isinstance(raw, dict):
            raise json.JSONDecodeError("request body must be a JSON object", body, 0)
        return raw

    def _write_error(self, status: HTTPStatus, code: str, message: str) -> None:
        self._write_json(status, {"error": {"code": code, "message": message}})

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any] | None) -> None:
        body = (
            b""
            if payload is None
            else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )
        self.send_response(status.value)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        if payload is not None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def _single_query_values(query: str) -> dict[str, str]:
    return {key: values[-1] for key, values in parse_qs(query).items() if values}


def _composer_library_payload(request: ComposerLibraryHttpRequest) -> dict[str, Any]:
    pdf_dir = request.pdf_dir.expanduser().resolve()
    if not pdf_dir.is_dir():
        raise ApiError(f"pdf_dir does not exist: {pdf_dir}")
    root = request.root if request.root is not None else default_root()
    fields_db = root.expanduser() / "fields.db"
    with FieldsStore.open(fields_db) as fields_store:
        library = load_composer_library(pdf_dir, fields_store)
        return library.to_payload(limit=request.limit)


def _select_directory() -> Path | None:
    if sys.platform == "darwin":
        return _select_directory_macos()
    return _select_directory_tk()


def _select_directory_macos() -> Path | None:
    script = 'POSIX path of (choose folder with prompt "选择本地论文文件夹")'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError as exc:
        raise ApiError(f"macOS directory selector is unavailable: {exc}") from exc

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "User canceled" in stderr or "用户已取消" in stderr:
            return None
        raise ApiError(stderr or "failed to open directory selector")

    selected = result.stdout.strip()
    return Path(selected) if selected else None


def _select_directory_tk() -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise ApiError("directory selector is unavailable on this platform") from exc

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise ApiError("directory selector cannot open without a desktop session") from exc
    root.withdraw()
    try:
        selected = filedialog.askdirectory(
            mustexist=True,
            title="选择本地论文文件夹",
        )
    finally:
        root.destroy()

    return Path(selected) if selected else None
