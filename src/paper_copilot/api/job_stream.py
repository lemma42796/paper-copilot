from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import Server, ServerConnection, serve

from paper_copilot.chat.jobs import (
    ChatJobEvent,
    ChatJobRecord,
    ChatJobRegistry,
    job_registry,
)
from paper_copilot.shared.errors import PaperCopilotError

_LOCAL_ORIGIN_RE = re.compile(r"https?://(?:localhost|127\.0\.0\.1)(?::[0-9]+)?$")


def create_job_websocket_server(host: str, port: int) -> Server:
    return serve(
        _handle_job_websocket,
        host,
        port,
        origins=[None, _LOCAL_ORIGIN_RE],
        ping_interval=20,
        ping_timeout=20,
    )


def job_stream_payload(
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


def _handle_job_websocket(connection: ServerConnection) -> None:
    try:
        job_id, root, after = _stream_request(connection.request.path)
        registry = job_registry(root)
        record = registry.get(job_id)
        events = registry.events(job_id, after=after)
        _send_job_events(connection, record, events, after=after)
        if events:
            after = events[-1].seq

        while record.status not in {"completed", "interrupted", "failed"}:
            try:
                message = connection.recv(timeout=0.25)
            except TimeoutError:
                message = None
            if message is not None:
                _handle_control_message(connection, registry, job_id, message)
            record = registry.get(job_id)
            events = registry.events(job_id, after=after)
            if events:
                _send_job_events(connection, record, events, after=after)
                after = events[-1].seq
            elif record.status in {"completed", "interrupted", "failed"}:
                _send_job_events(connection, record, [], after=after)
                return
    except ConnectionClosed:
        return
    except (PaperCopilotError, ValueError):
        connection.close(code=1008, reason="invalid job stream request")


def _send_job_events(
    connection: ServerConnection,
    record: ChatJobRecord,
    events: list[ChatJobEvent],
    *,
    after: int,
) -> None:
    connection.send(
        json.dumps(
            {
                "method": "job/events",
                "params": job_stream_payload(record, events, after=after),
            },
            ensure_ascii=False,
        )
    )


def _handle_control_message(
    connection: ServerConnection,
    registry: ChatJobRegistry,
    job_id: str,
    message: str | bytes,
) -> None:
    request_id: str | int | None = None
    try:
        if not isinstance(message, str):
            raise ValueError("WebSocket control messages must be text")
        request = json.loads(message)
        if not isinstance(request, dict):
            raise ValueError("WebSocket control message must be an object")
        request_id = request.get("id")
        if not isinstance(request_id, str | int):
            raise ValueError("WebSocket control message requires a string or integer id")
        method = request.get("method")
        params = request.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("WebSocket control params must be an object")
        match method:
            case "job/interrupt":
                record = registry.interrupt(job_id)
            case "job/resume":
                record = registry.resume(job_id)
            case "job/approve" | "job/deny":
                approval_id = params.get("approval_id")
                if not isinstance(approval_id, str):
                    raise ValueError("approval control requires approval_id")
                record = registry.resolve_approval(
                    job_id,
                    approval_id,
                    approved=method == "job/approve",
                )
            case _:
                raise ValueError(f"unknown WebSocket method: {method}")
        response = {
            "id": request_id,
            "result": {"record": record.model_dump(mode="json")},
        }
    except (json.JSONDecodeError, PaperCopilotError, ValueError) as exc:
        response = {
            "id": request_id,
            "error": {
                "code": exc.__class__.__name__,
                "message": str(exc),
            },
        }
    connection.send(json.dumps(response, ensure_ascii=False))


def _stream_request(path: str) -> tuple[str, Path | None, int]:
    parsed = urlparse(path)
    parts = parsed.path.strip("/").split("/")
    if len(parts) != 3 or parts[0] != "jobs" or parts[2] != "stream":
        raise ValueError(f"unknown WebSocket path: {parsed.path}")
    query = parse_qs(parsed.query)
    after = int(query.get("after", ["0"])[-1])
    if after < 0:
        raise ValueError("after must be non-negative")
    root_raw = query.get("root", [None])[-1]
    root = Path(root_raw) if root_raw is not None else None
    return parts[1], root, after
