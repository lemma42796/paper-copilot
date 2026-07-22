from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from paper_copilot.agents.composer_library import load_composer_library
from paper_copilot.api.job_stream import (
    create_job_websocket_server,
    job_stream_payload,
)
from paper_copilot.chat.evidence import EvidenceChunk, EvidenceField, lookup_evidence_ref
from paper_copilot.chat.history import ChatReportItem, list_chat_reports
from paper_copilot.chat.jobs import ChatJobSpec, job_registry
from paper_copilot.chat.runtime import ChatRunResult, handle_chat_request
from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.session.paths import default_root
from paper_copilot.shared.errors import ApiError, PaperCopilotError
from paper_copilot.shared.logging import get_logger

_logger = get_logger(__name__)


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


class JobCreateHttpRequest(ChatHttpRequest):
    conversation_id: str | None = Field(
        default=None,
        pattern=r"^conversation-[0-9A-Za-z-]{8,80}$",
    )
    rollout_timeout_seconds: float | None = Field(default=3600.0, gt=0)


class ReportsHttpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: Path | None = None
    limit: int = Field(default=20, ge=1, le=100)


class JobsHttpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: Path | None = None
    limit: int = Field(default=50, ge=1, le=200)


class JobActionHttpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: Path | None = None


class JobApprovalHttpRequest(JobActionHttpRequest):
    approval_id: str = Field(min_length=1)
    approved: bool


class JobEventsHttpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: Path | None = None
    after: int = Field(default=0, ge=0)
    limit: int = Field(default=200, ge=1, le=1000)


class JobDiagnosticsHttpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: Path | None = None
    attempt: int | None = Field(default=None, ge=1)
    slow_ms: int = Field(default=1000, ge=0)
    repeat_threshold: int = Field(default=3, ge=2)


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


def serve_http_api(
    host: str = "127.0.0.1",
    port: int = 8765,
    websocket_port: int | None = None,
) -> None:
    resolved_websocket_port = port + 1 if websocket_port is None else websocket_port
    http_server = _PaperCopilotHTTPServer(
        (host, port),
        _ChatHandler,
        websocket_port=resolved_websocket_port,
    )
    try:
        websocket_server = create_job_websocket_server(host, resolved_websocket_port)
    except OSError as exc:
        websocket_server = None
        http_server.websocket_port = None
        _logger.warning(
            "websocket_server_unavailable",
            host=host,
            port=resolved_websocket_port,
            error=str(exc),
        )
    websocket_thread: threading.Thread | None = None
    if websocket_server is not None:
        websocket_thread = threading.Thread(
            target=websocket_server.serve_forever,
            name="paper-copilot-websocket",
            daemon=True,
        )
        websocket_thread.start()
    try:
        http_server.serve_forever()
    finally:
        if websocket_server is not None:
            websocket_server.shutdown()
        if websocket_thread is not None:
            websocket_thread.join()
        http_server.server_close()


class _PaperCopilotHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        *,
        websocket_port: int | None,
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.websocket_port = websocket_port


class _ChatHandler(BaseHTTPRequestHandler):
    server_version = "PaperCopilotHTTP/0.1"

    def do_OPTIONS(self) -> None:
        self._write_json(HTTPStatus.NO_CONTENT, None)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            payload = {"status": "ok"}
            websocket_url = self._websocket_url()
            if websocket_url is not None:
                payload["websocket_url"] = websocket_url
            self._write_json(HTTPStatus.OK, payload)
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
        if parsed.path == "/jobs":
            try:
                request = JobsHttpRequest.model_validate(_single_query_values(parsed.query))
                records = job_registry(request.root).list(limit=request.limit)
            except ValidationError as exc:
                self._write_error(HTTPStatus.BAD_REQUEST, "bad_request", str(exc))
                return
            except PaperCopilotError as exc:
                self._write_error(HTTPStatus.BAD_REQUEST, exc.__class__.__name__, str(exc))
                return
            self._write_json(
                HTTPStatus.OK,
                {"jobs": [record.model_dump(mode="json") for record in records]},
            )
            return
        job_route = _job_route(parsed.path)
        if job_route is not None and job_route[1] is None:
            job_id, _action = job_route
            try:
                request = JobActionHttpRequest.model_validate(
                    _single_query_values(parsed.query)
                )
                record = job_registry(request.root).get(job_id)
            except ValidationError as exc:
                self._write_error(HTTPStatus.BAD_REQUEST, "bad_request", str(exc))
                return
            except PaperCopilotError as exc:
                self._write_error(HTTPStatus.BAD_REQUEST, exc.__class__.__name__, str(exc))
                return
            self._write_json(HTTPStatus.OK, record.model_dump(mode="json"))
            return
        if job_route is not None and job_route[1] == "events":
            job_id, _action = job_route
            try:
                request = JobEventsHttpRequest.model_validate(
                    _single_query_values(parsed.query)
                )
                events = job_registry(request.root).events(
                    job_id,
                    after=request.after,
                    limit=request.limit,
                )
            except ValidationError as exc:
                self._write_error(HTTPStatus.BAD_REQUEST, "bad_request", str(exc))
                return
            except PaperCopilotError as exc:
                self._write_error(HTTPStatus.BAD_REQUEST, exc.__class__.__name__, str(exc))
                return
            self._write_json(
                HTTPStatus.OK,
                {
                    "events": [event.model_dump(mode="json") for event in events],
                    "next_after": events[-1].seq if events else request.after,
                },
            )
            return
        if job_route is not None and job_route[1] == "diagnostics":
            job_id, _action = job_route
            try:
                diagnostics_request = JobDiagnosticsHttpRequest.model_validate(
                    _single_query_values(parsed.query)
                )
                diagnostics = job_registry(diagnostics_request.root).diagnostics(
                    job_id,
                    attempt=diagnostics_request.attempt,
                    slow_ms=diagnostics_request.slow_ms,
                    repeat_threshold=diagnostics_request.repeat_threshold,
                )
            except (json.JSONDecodeError, ValidationError) as exc:
                self._write_error(HTTPStatus.BAD_REQUEST, "bad_request", str(exc))
                return
            except PaperCopilotError as exc:
                self._write_error(HTTPStatus.BAD_REQUEST, exc.__class__.__name__, str(exc))
                return
            self._write_json(
                HTTPStatus.OK,
                diagnostics.model_dump(mode="json"),
            )
            return
        if job_route is not None and job_route[1] == "stream":
            self._handle_job_event_stream(job_route[0], parsed.query)
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
        if parsed.path == "/jobs":
            self._handle_create_job()
            return
        job_route = _job_route(parsed.path)
        if job_route is not None and job_route[1] == "resume":
            self._handle_resume_job(job_route[0])
            return
        if job_route is not None and job_route[1] == "interrupt":
            self._handle_interrupt_job(job_route[0])
            return
        if job_route is not None and job_route[1] == "approval":
            self._handle_job_approval(job_route[0])
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

    def _handle_create_job(self) -> None:
        try:
            request = JobCreateHttpRequest.model_validate(self._read_json_body())
        except ValidationError as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, "bad_request", str(exc))
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, "invalid_json", str(exc))
            return

        try:
            record = job_registry(request.root).create(
                ChatJobSpec(
                    request=request.message,
                    conversation_id=request.conversation_id,
                    pdf_dir=str(request.pdf_dir) if request.pdf_dir is not None else None,
                    max_turns=request.max_turns,
                    budget_cny=request.budget_cny,
                    max_papers=request.max_papers,
                    record_quality=request.record_quality,
                    update_report=request.update_report,
                    rollout_timeout_seconds=request.rollout_timeout_seconds,
                )
            )
        except PaperCopilotError as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, exc.__class__.__name__, str(exc))
            return
        self._write_json(HTTPStatus.ACCEPTED, record.model_dump(mode="json"))

    def _handle_resume_job(self, job_id: str) -> None:
        try:
            request = JobActionHttpRequest.model_validate(self._read_json_body())
        except ValidationError as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, "bad_request", str(exc))
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, "invalid_json", str(exc))
            return

        try:
            record = job_registry(request.root).resume(job_id)
        except PaperCopilotError as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, exc.__class__.__name__, str(exc))
            return
        self._write_json(HTTPStatus.ACCEPTED, record.model_dump(mode="json"))

    def _handle_interrupt_job(self, job_id: str) -> None:
        try:
            request = JobActionHttpRequest.model_validate(self._read_json_body())
        except ValidationError as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, "bad_request", str(exc))
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, "invalid_json", str(exc))
            return

        try:
            record = job_registry(request.root).interrupt(job_id)
        except PaperCopilotError as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, exc.__class__.__name__, str(exc))
            return
        self._write_json(HTTPStatus.ACCEPTED, record.model_dump(mode="json"))

    def _handle_job_approval(self, job_id: str) -> None:
        try:
            request = JobApprovalHttpRequest.model_validate(self._read_json_body())
        except ValidationError as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, "bad_request", str(exc))
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, "invalid_json", str(exc))
            return

        try:
            record = job_registry(request.root).resolve_approval(
                job_id,
                request.approval_id,
                approved=request.approved,
            )
        except PaperCopilotError as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, exc.__class__.__name__, str(exc))
            return
        self._write_json(HTTPStatus.ACCEPTED, record.model_dump(mode="json"))

    def _handle_job_event_stream(self, job_id: str, query: str) -> None:
        query_values = _single_query_values(query)
        last_event_id = self.headers.get("Last-Event-ID")
        if last_event_id is not None:
            query_values["after"] = last_event_id
        try:
            request = JobEventsHttpRequest.model_validate(query_values)
            registry = job_registry(request.root)
            record = registry.get(job_id)
            events = registry.events(
                job_id,
                after=request.after,
                limit=request.limit,
            )
        except ValidationError as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, "bad_request", str(exc))
            return
        except PaperCopilotError as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, exc.__class__.__name__, str(exc))
            return

        self.send_response(HTTPStatus.OK.value)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        after = request.after
        try:
            self._write_stream_event(job_stream_payload(record, events, after=after))
            if events:
                after = events[-1].seq
            while record.status in {"queued", "running"}:
                record, events = registry.wait_for_events(
                    job_id,
                    after=after,
                    limit=request.limit,
                )
                if events or record.status not in {"queued", "running"}:
                    self._write_stream_event(
                        job_stream_payload(record, events, after=after)
                    )
                    if events:
                        after = events[-1].seq
                else:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
        except OSError:
            return

    def _write_stream_event(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False)
        message = f"id: {payload['next_after']}\ndata: {body}\n\n"
        self.wfile.write(message.encode("utf-8"))
        self.wfile.flush()

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

    def _websocket_url(self) -> str | None:
        server = cast(_PaperCopilotHTTPServer, self.server)
        if server.websocket_port is None:
            return None
        host_header = self.headers.get("Host", "127.0.0.1")
        hostname = urlparse(f"//{host_header}").hostname or "127.0.0.1"
        url_hostname = f"[{hostname}]" if ":" in hostname else hostname
        return f"ws://{url_hostname}:{server.websocket_port}"

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


def _job_route(path: str) -> tuple[str, str | None] | None:
    parts = path.strip("/").split("/")
    if len(parts) == 2 and parts[0] == "jobs":
        return parts[1], None
    if (
        len(parts) == 3
        and parts[0] == "jobs"
        and parts[2]
        in {"diagnostics", "events", "stream", "resume", "interrupt", "approval"}
    ):
        return parts[1], parts[2]
    return None


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
