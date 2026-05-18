from __future__ import annotations

import asyncio
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from paper_copilot.chat.history import ChatReportItem, list_chat_reports
from paper_copilot.chat.runtime import ChatRunResult, handle_chat_request
from paper_copilot.shared.errors import PaperCopilotError


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


class ChatHttpResponse(BaseModel):
    request: str
    route: dict[str, str]
    report_markdown: str
    session_path: str
    report_path: str
    quality_run_path: str | None
    eval_report_path: str | None
    termination_reason: str
    cost_cny: float
    events_count: int
    paper_budget: dict[str, object]

    @classmethod
    def from_result(cls, result: ChatRunResult) -> ChatHttpResponse:
        return cls(
            request=result.request,
            route=result.route.to_payload(),
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
        )


class ChatReportHttpItem(BaseModel):
    id: str
    request: str
    route: dict[str, str]
    report_markdown: str
    session_path: str
    report_path: str
    updated_at: str
    termination_reason: str
    cost_cny: float | None
    events_count: int | None
    paper_budget: dict[str, object]

    @classmethod
    def from_item(cls, item: ChatReportItem) -> ChatReportHttpItem:
        return cls(
            id=item.id,
            request=item.request,
            route=item.route,
            report_markdown=item.report_markdown,
            session_path=str(item.session_path),
            report_path=str(item.report_path),
            updated_at=item.updated_at,
            termination_reason=item.termination_reason,
            cost_cny=item.cost_cny,
            events_count=item.events_count,
            paper_budget=item.paper_budget,
        )


class ChatReportsHttpResponse(BaseModel):
    reports: list[ChatReportHttpItem]

    @classmethod
    def from_items(cls, items: list[ChatReportItem]) -> ChatReportsHttpResponse:
        return cls(reports=[ChatReportHttpItem.from_item(item) for item in items])


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
        self._write_error(HTTPStatus.NOT_FOUND, "not_found", f"unknown path: {parsed.path}")

    def do_POST(self) -> None:
        if self.path != "/chat":
            self._write_error(HTTPStatus.NOT_FOUND, "not_found", f"unknown path: {self.path}")
            return

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
