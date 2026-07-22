from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from pydantic import BaseModel

from paper_copilot.observability.context import (
    activate_recorder,
    current_entity_id,
    reset_current_entity,
    set_current_entity,
)
from paper_copilot.observability.types import (
    TraceEntityType,
    TraceEvent,
    TraceEventType,
    TraceManifest,
    TraceStatus,
)

_MAX_PAYLOAD_BYTES = 262_144
_MAX_PAYLOAD_PREVIEW_CHARS = 16_384
_MAX_STRING_CHARS = 2_000
_MAX_COLLECTION_ITEMS = 50
_MAX_MAPPING_ITEMS = 100
_MAX_DEPTH = 8
_INLINE_AUTH_RE = re.compile(
    r"\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+",
    re.IGNORECASE,
)
_INLINE_SECRET_RE = re.compile(
    r"\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|"
    r"authorization|cookie)(\s*[:=]\s*)([^\s,;]+)",
    re.IGNORECASE,
)
_SK_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")


class RolloutRecorder:
    def __init__(self, bundle_dir: Path, manifest: TraceManifest) -> None:
        self._bundle_dir = bundle_dir
        self._payload_dir = bundle_dir / "payloads"
        self._trace_path = bundle_dir / "trace.jsonl"
        self._manifest = manifest
        self._lock = threading.Lock()
        self._next_seq = 1

    @classmethod
    def create(
        cls,
        bundle_dir: Path,
        *,
        job_id: str,
        attempt: int,
        session_id: str,
        turn_id: str,
    ) -> RolloutRecorder:
        bundle_dir.mkdir(parents=True, exist_ok=False)
        payload_dir = bundle_dir / "payloads"
        payload_dir.mkdir()
        manifest = TraceManifest(
            trace_id=f"trace-{uuid4().hex}",
            job_id=job_id,
            attempt=attempt,
            session_id=session_id,
            turn_id=turn_id,
            started_at=_now_ts(),
        )
        _write_json_file(bundle_dir / "manifest.json", manifest.model_dump(mode="json"))
        return cls(bundle_dir, manifest)

    @property
    def rollout_entity_id(self) -> str:
        return f"rollout:{self._manifest.job_id}:{self._manifest.attempt}"

    @property
    def turn_id(self) -> str:
        return self._manifest.turn_id

    @property
    def bundle_dir(self) -> Path:
        return self._bundle_dir

    @contextmanager
    def activate(self) -> Iterator[None]:
        with activate_recorder(self):
            yield

    def new_entity_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid4().hex}"

    def operation(
        self,
        entity_type: TraceEntityType,
        entity_id: str,
        *,
        parent_entity_id: str | None = None,
        attributes: Mapping[str, Any] | None = None,
        input_payload: Any | None = None,
    ) -> TraceOperation:
        return TraceOperation(
            self,
            entity_type,
            entity_id,
            parent_entity_id=parent_entity_id,
            attributes=attributes,
            input_payload=input_payload,
        )

    def record(
        self,
        *,
        entity_type: TraceEntityType,
        entity_id: str,
        event_type: TraceEventType,
        status: TraceStatus,
        parent_entity_id: str | None = None,
        duration_ms: int | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        attributes: Mapping[str, Any] | None = None,
        payloads: Mapping[str, Any] | None = None,
    ) -> TraceEvent:
        with self._lock:
            payload_refs = {
                name: self._write_payload(name, payload)
                for name, payload in (payloads or {}).items()
            }
            event = TraceEvent(
                seq=self._next_seq,
                event_id=f"evt-{uuid4().hex}",
                ts=_now_ts(),
                job_id=self._manifest.job_id,
                attempt=self._manifest.attempt,
                session_id=self._manifest.session_id,
                turn_id=self._manifest.turn_id,
                entity_type=entity_type,
                entity_id=entity_id,
                parent_entity_id=parent_entity_id,
                event_type=event_type,
                status=status,
                duration_ms=duration_ms,
                error_type=error_type,
                error_message=error_message,
                attributes=dict(attributes or {}),
                payload_refs=payload_refs,
            )
            with self._trace_path.open("a", encoding="utf-8") as stream:
                stream.write(event.model_dump_json() + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._next_seq += 1
            return event

    def _write_payload(self, name: str, payload: Any) -> str:
        payload_id = f"payload-{uuid4().hex}"
        path = self._payload_dir / f"{payload_id}.json"
        sanitized = _bounded_trace_payload(payload)
        _write_json_file(
            path,
            {
                "payload_id": payload_id,
                "kind": name,
                "value": sanitized,
            },
        )
        return payload_id


class TraceOperation:
    def __init__(
        self,
        recorder: RolloutRecorder,
        entity_type: TraceEntityType,
        entity_id: str,
        *,
        parent_entity_id: str | None,
        attributes: Mapping[str, Any] | None,
        input_payload: Any | None,
    ) -> None:
        self._recorder = recorder
        self._entity_type = entity_type
        self._entity_id = entity_id
        self._parent_entity_id = parent_entity_id
        self._resolved_parent_entity_id: str | None = None
        self._attributes = dict(attributes or {})
        self._input_payload = input_payload
        self._output_payload: Any | None = None
        self._terminal_attributes: dict[str, Any] = {}
        self._terminal_status: Literal[
            "completed", "failed", "cancelled", "aborted"
        ] = "completed"
        self._started_at: float | None = None
        self._entity_token: Any = None
        self._error_type: str | None = None
        self._error_message: str | None = None

    def __enter__(self) -> TraceOperation:
        self._started_at = time.perf_counter()
        self._resolved_parent_entity_id = self._parent_entity_id or current_entity_id()
        self._recorder.record(
            entity_type=self._entity_type,
            entity_id=self._entity_id,
            parent_entity_id=self._resolved_parent_entity_id,
            event_type=_event_type(self._entity_type, "started"),
            status="running",
            attributes=self._attributes,
            payloads={"input": self._input_payload} if self._input_payload is not None else None,
        )
        self._entity_token = set_current_entity(self._entity_id)
        return self

    def set_result(
        self,
        *,
        status: Literal["completed", "failed", "cancelled", "aborted"] = "completed",
        output_payload: Any | None = None,
        attributes: Mapping[str, Any] | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if status == "aborted" and self._entity_type != "tool_call":
            raise ValueError("only tool_call operations can be aborted")
        self._terminal_status = status
        self._output_payload = output_payload
        self._terminal_attributes = dict(attributes or {})
        self._error_type = error_type
        self._error_message = error_message

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        _traceback: Any,
    ) -> Literal[False]:
        started_at = self._started_at if self._started_at is not None else time.perf_counter()
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        status = self._terminal_status
        error_type = self._error_type
        error_message = self._error_message
        if exc_type is not None:
            status = "cancelled" if issubclass(exc_type, asyncio.CancelledError) else "failed"
            error_type = exc_type.__name__
            error_message = str(exc)
        self._recorder.record(
            entity_type=self._entity_type,
            entity_id=self._entity_id,
            parent_entity_id=self._resolved_parent_entity_id,
            event_type=_event_type(self._entity_type, status),
            status=status,
            duration_ms=duration_ms,
            error_type=error_type,
            error_message=error_message,
            attributes={**self._attributes, **self._terminal_attributes},
            payloads={"output": self._output_payload} if self._output_payload is not None else None,
        )
        reset_current_entity(self._entity_token)
        return False


def _event_type(
    entity_type: TraceEntityType,
    phase: Literal["started", "completed", "failed", "cancelled", "aborted"],
) -> TraceEventType:
    return cast("TraceEventType", f"{entity_type}.{phase}")


def _write_json_file(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, default=_json_default)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"cannot serialize trace payload value of type {type(value).__name__}")


def _bounded_trace_payload(value: Any) -> Any:
    sanitized = _sanitize_trace_payload(value, depth=0)
    encoded = json.dumps(
        sanitized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    encoded_bytes = encoded.encode("utf-8")
    if len(encoded_bytes) <= _MAX_PAYLOAD_BYTES:
        return sanitized
    return {
        "_trace_value": "truncated_payload",
        "preview": encoded[:_MAX_PAYLOAD_PREVIEW_CHARS],
        "sanitized_bytes": len(encoded_bytes),
        "sha256": hashlib.sha256(encoded_bytes).hexdigest(),
    }


def _sanitize_trace_payload(
    value: Any,
    *,
    depth: int,
    key: str | None = None,
) -> Any:
    if key is not None and _is_sensitive_key(key):
        return "[REDACTED]"
    if depth >= _MAX_DEPTH:
        return {"_trace_value": "max_depth"}
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    elif is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    elif isinstance(value, Path):
        value = str(value)

    if isinstance(value, Mapping):
        items = list(value.items())
        sanitized = {
            str(item_key): _sanitize_trace_payload(
                item_value,
                depth=depth + 1,
                key=str(item_key),
            )
            for item_key, item_value in items[:_MAX_MAPPING_ITEMS]
        }
        if len(items) > _MAX_MAPPING_ITEMS:
            sanitized["_trace_omitted_keys"] = len(items) - _MAX_MAPPING_ITEMS
        return sanitized
    if isinstance(value, (list, tuple)):
        sanitized_items = [
            _sanitize_trace_payload(item, depth=depth + 1)
            for item in value[:_MAX_COLLECTION_ITEMS]
        ]
        if len(value) > _MAX_COLLECTION_ITEMS:
            sanitized_items.append(
                {
                    "_trace_value": "truncated_items",
                    "omitted": len(value) - _MAX_COLLECTION_ITEMS,
                }
            )
        return sanitized_items
    if isinstance(value, str):
        redacted = _redact_inline_secrets(value)
        if len(redacted) <= _MAX_STRING_CHARS:
            return redacted
        return {
            "_trace_value": "truncated_string",
            "preview": redacted[:_MAX_STRING_CHARS],
            "length": len(redacted),
            "sha256": hashlib.sha256(redacted.encode("utf-8")).hexdigest(),
        }
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _sanitize_trace_payload(_json_default(value), depth=depth + 1)


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    return (
        normalized
        in {
            "authorization",
            "cookie",
            "passwd",
            "password",
            "proxy_authorization",
            "secret",
            "set_cookie",
            "token",
        }
        or normalized.endswith("_api_key")
        or normalized.endswith("_password")
        or normalized.endswith("_secret")
        or normalized.endswith("_token")
    )


def _redact_inline_secrets(value: str) -> str:
    redacted = _INLINE_AUTH_RE.sub(lambda match: f"{match.group(0).split()[0]} [REDACTED]", value)
    redacted = _INLINE_SECRET_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        redacted,
    )
    return _SK_KEY_RE.sub("[REDACTED]", redacted)


def _now_ts() -> str:
    return datetime.now(UTC).isoformat()
