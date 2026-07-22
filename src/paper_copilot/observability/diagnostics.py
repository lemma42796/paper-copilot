from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from paper_copilot.observability.reducer import load_payload
from paper_copilot.observability.retention import tombstone_value_sha256
from paper_copilot.observability.types import (
    ReducedOperation,
    RolloutState,
    TraceEntityType,
    TraceStatus,
)


class OperationDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str
    entity_type: TraceEntityType
    label: str
    status: TraceStatus
    duration_ms: int | None
    error_type: str | None = None
    error_message: str | None = None


class RepeatedToolCallDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    input_sha256: str
    count: int = Field(ge=2)
    entity_ids: list[str]


class RolloutDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    attempt: int
    trace_id: str
    status: TraceStatus
    event_count: int
    total_duration_ms: int | None
    phase_duration_ms: dict[str, int]
    first_error: OperationDiagnostic | None
    slow_operations: list[OperationDiagnostic]
    unfinished_operations: list[OperationDiagnostic]
    repeated_tool_calls: list[RepeatedToolCallDiagnostic]


def diagnose_rollout(
    bundle_dir: Path,
    state: RolloutState,
    *,
    slow_ms: int = 1000,
    repeat_threshold: int = 3,
) -> RolloutDiagnostics:
    operations = state.operations
    rollout = next(item for item in operations if item.entity_type == "rollout")
    phase_duration_ms: dict[str, int] = defaultdict(int)
    for operation in operations:
        if operation.duration_ms is not None:
            phase_duration_ms[operation.entity_type] += operation.duration_ms

    failed = [item for item in operations if item.status in {"failed", "aborted"}]
    failed.sort(key=lambda item: item.terminal_seq or item.started_seq)
    slow = [
        item
        for item in operations
        if item.entity_type != "rollout"
        and item.duration_ms is not None
        and item.duration_ms >= slow_ms
    ]
    slow.sort(key=lambda item: item.duration_ms or 0, reverse=True)
    unfinished = [item for item in operations if item.status == "running"]

    return RolloutDiagnostics(
        job_id=state.job_id,
        attempt=state.attempt,
        trace_id=state.trace_id,
        status=state.status,
        event_count=state.event_count,
        total_duration_ms=rollout.duration_ms,
        phase_duration_ms=dict(sorted(phase_duration_ms.items())),
        first_error=(
            _operation_diagnostic(failed[0], bundle_dir=bundle_dir) if failed else None
        ),
        slow_operations=[_operation_diagnostic(item) for item in slow],
        unfinished_operations=[_operation_diagnostic(item) for item in unfinished],
        repeated_tool_calls=_repeated_tool_calls(
            bundle_dir,
            operations,
            repeat_threshold=repeat_threshold,
        ),
    )


def _operation_diagnostic(
    operation: ReducedOperation,
    *,
    bundle_dir: Path | None = None,
) -> OperationDiagnostic:
    label = str(
        operation.attributes.get("tool_name")
        or operation.attributes.get("model")
        or operation.entity_type
    )
    error_message = operation.error_message
    if error_message is None and bundle_dir is not None:
        payload_id = operation.payload_refs.get(f"{operation.status}.output")
        if payload_id is not None:
            payload = load_payload(bundle_dir, payload_id)
            if isinstance(payload, dict) and payload.get("is_error") is True:
                error_message = _payload_text(payload.get("output", ""))
    return OperationDiagnostic(
        entity_id=operation.entity_id,
        entity_type=operation.entity_type,
        label=label,
        status=operation.status,
        duration_ms=operation.duration_ms,
        error_type=operation.error_type,
        error_message=error_message,
    )


def _repeated_tool_calls(
    bundle_dir: Path,
    operations: list[ReducedOperation],
    *,
    repeat_threshold: int,
) -> list[RepeatedToolCallDiagnostic]:
    signatures: Counter[tuple[str, str]] = Counter()
    entity_ids: dict[tuple[str, str], list[str]] = defaultdict(list)
    for operation in operations:
        if operation.entity_type != "tool_call":
            continue
        payload_id = operation.payload_refs.get("started.input")
        if payload_id is None:
            continue
        tool_name = str(operation.attributes.get("tool_name", "unknown"))
        payload = load_payload(bundle_dir, payload_id)
        retained_sha256 = tombstone_value_sha256(payload)
        if retained_sha256 is None:
            canonical = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            retained_sha256 = hashlib.sha256(canonical).hexdigest()
        signature = (tool_name, retained_sha256)
        signatures[signature] += 1
        entity_ids[signature].append(operation.entity_id)

    repeated = [
        RepeatedToolCallDiagnostic(
            tool_name=signature[0],
            input_sha256=signature[1],
            count=count,
            entity_ids=entity_ids[signature],
        )
        for signature, count in signatures.items()
        if count >= repeat_threshold
    ]
    repeated.sort(key=lambda item: (-item.count, item.tool_name, item.input_sha256))
    return repeated


def _payload_text(value: object) -> str:
    if isinstance(value, dict) and value.get("_trace_value") == "truncated_string":
        return f"{value.get('preview', '')}…"
    return str(value)
