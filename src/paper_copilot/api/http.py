from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from paper_copilot.agents.tool_security import ApprovalMode
from paper_copilot.chat.jobs import (
    ChatJobEvent,
    ChatJobRecord,
    ChatJobSpec,
    job_registry,
)
from paper_copilot.shared.errors import PaperCopilotError


class JobCreateHttpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    pdf_dir: Path | None = None
    max_turns: int = Field(default=16, ge=1)
    budget_cny: float = Field(default=2.0, gt=0)
    max_papers: int = Field(default=5, ge=1)
    root: Path | None = None
    record_quality: bool = True
    update_report: bool = True
    conversation_id: str | None = Field(
        default=None,
        pattern=r"^conversation-[0-9A-Za-z-]{8,80}$",
    )
    rollout_timeout_seconds: float | None = Field(default=3600.0, gt=0)
    approval_mode: ApprovalMode = "ask"


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


def serve_http_api(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    shutdown_event: threading.Event | None = None,
    ready_callback: Callable[[str, int], None] | None = None,
) -> None:
    http_server = ThreadingHTTPServer((host, port), _ChatHandler)
    try:
        http_address = http_server.server_address
        if ready_callback is not None:
            ready_callback(str(http_address[0]), int(http_address[1]))
        if shutdown_event is None:
            http_server.serve_forever()
        else:
            http_server.timeout = 0.25
            while not shutdown_event.is_set():
                http_server.handle_request()
    finally:
        http_server.server_close()


class _ChatHandler(BaseHTTPRequestHandler):
    server_version = "PaperCopilotHTTP/0.1"

    def do_OPTIONS(self) -> None:
        self._write_json(HTTPStatus.NO_CONTENT, None)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._write_json(HTTPStatus.OK, {"status": "ok"})
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
        self._write_error(HTTPStatus.NOT_FOUND, "not_found", f"unknown path: {parsed.path}")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
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

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        conversation_id = _conversation_route(parsed.path)
        if conversation_id is None:
            self._write_error(
                HTTPStatus.NOT_FOUND,
                "not_found",
                f"unknown path: {parsed.path}",
            )
            return
        try:
            request = JobActionHttpRequest.model_validate(self._read_json_body())
        except ValidationError as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, "bad_request", str(exc))
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, "invalid_json", str(exc))
            return

        try:
            deleted_jobs = job_registry(request.root).delete_conversation(
                conversation_id
            )
        except PaperCopilotError as exc:
            self._write_error(
                HTTPStatus.BAD_REQUEST,
                exc.__class__.__name__,
                str(exc),
            )
            return
        self._write_json(
            HTTPStatus.OK,
            {
                "conversation_id": conversation_id,
                "deleted_jobs": deleted_jobs,
            },
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
                    approval_mode=request.approval_mode,
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
            self._write_stream_event(_job_stream_payload(record, events, after=after))
            if events:
                after = events[-1].seq
            while record.status in {"queued", "running", "waiting_for_approval"}:
                record, events = registry.wait_for_events(
                    job_id,
                    after=after,
                    limit=request.limit,
                )
                if events or record.status not in {
                    "queued",
                    "running",
                    "waiting_for_approval",
                }:
                    self._write_stream_event(
                        _job_stream_payload(record, events, after=after)
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
        self.send_header(
            "Access-Control-Allow-Methods",
            "DELETE, GET, POST, OPTIONS",
        )
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


def _conversation_route(path: str) -> str | None:
    parts = path.strip("/").split("/")
    if len(parts) == 2 and parts[0] == "conversations":
        return parts[1]
    return None


def _job_stream_payload(
    record: ChatJobRecord,
    events: list[ChatJobEvent],
    *,
    after: int,
) -> dict[str, Any]:
    next_after = events[-1].seq if events else after
    return {
        "record": record.model_dump(mode="json"),
        "events": [event.model_dump(mode="json") for event in events],
        "next_after": next_after,
    }
