from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from paper_copilot.observability.types import (
    ReducedOperation,
    RolloutState,
    TraceEvent,
    TraceManifest,
)
from paper_copilot.shared.errors import TraceIntegrityError

_PAYLOAD_ID_RE = re.compile(r"^payload-[0-9a-f]{32}$")


def reduce_trace_bundle(bundle_dir: Path, *, write_state: bool = True) -> RolloutState:
    manifest = _read_manifest(bundle_dir)
    events = _read_events(bundle_dir / "trace.jsonl")
    operations: dict[str, ReducedOperation] = {}
    event_ids: set[str] = set()

    for expected_seq, event in enumerate(events, start=1):
        _validate_event_identity(event, manifest, expected_seq)
        if event.event_id in event_ids:
            raise TraceIntegrityError(f"duplicate event id {event.event_id}")
        event_ids.add(event.event_id)
        phase = event.event_type.rsplit(".", maxsplit=1)[1]
        expected_entity_type = event.event_type.split(".", maxsplit=1)[0]
        if expected_entity_type != event.entity_type:
            raise TraceIntegrityError(
                f"event {event.seq} type {event.event_type} does not match "
                f"entity type {event.entity_type}"
            )
        _validate_payload_refs(bundle_dir, event)

        if phase == "started":
            if event.entity_id in operations:
                raise TraceIntegrityError(
                    f"entity {event.entity_id} has more than one started event"
                )
            if event.status != "running" or event.duration_ms is not None:
                raise TraceIntegrityError(
                    f"started event {event.seq} must be running without duration"
                )
            if (
                event.parent_entity_id is not None
                and event.parent_entity_id not in operations
            ):
                raise TraceIntegrityError(
                    f"entity {event.entity_id} references unknown parent "
                    f"{event.parent_entity_id}"
                )
            operations[event.entity_id] = ReducedOperation(
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                parent_entity_id=event.parent_entity_id,
                started_seq=event.seq,
                started_at=event.ts,
                status="running",
                attributes=event.attributes,
                payload_refs={
                    f"started.{name}": payload_id
                    for name, payload_id in event.payload_refs.items()
                },
            )
            continue

        operation = operations.get(event.entity_id)
        if operation is None:
            raise TraceIntegrityError(
                f"terminal event {event.seq} has no started event for {event.entity_id}"
            )
        if operation.terminal_seq is not None:
            raise TraceIntegrityError(
                f"entity {event.entity_id} has more than one terminal event"
            )
        if event.parent_entity_id != operation.parent_entity_id:
            raise TraceIntegrityError(
                f"entity {event.entity_id} changed parent between lifecycle events"
            )
        if event.entity_type != operation.entity_type:
            raise TraceIntegrityError(
                f"entity {event.entity_id} changed type between lifecycle events"
            )
        if event.status == "running" or event.status != phase:
            raise TraceIntegrityError(
                f"terminal event {event.seq} has inconsistent phase/status"
            )
        if event.duration_ms is None:
            raise TraceIntegrityError(
                f"terminal event {event.seq} is missing duration_ms"
            )
        operation.terminal_seq = event.seq
        operation.terminal_at = event.ts
        operation.status = event.status
        operation.duration_ms = event.duration_ms
        operation.error_type = event.error_type
        operation.error_message = event.error_message
        operation.attributes.update(event.attributes)
        operation.payload_refs.update(
            {
                f"{phase}.{name}": payload_id
                for name, payload_id in event.payload_refs.items()
            }
        )

    rollout_id = f"rollout:{manifest.job_id}:{manifest.attempt}"
    rollout = operations.get(rollout_id)
    if rollout is None or rollout.entity_type != "rollout":
        raise TraceIntegrityError(f"trace is missing rollout entity {rollout_id}")
    rollout_operations = [
        operation for operation in operations.values() if operation.entity_type == "rollout"
    ]
    if len(rollout_operations) != 1 or rollout.parent_entity_id is not None:
        raise TraceIntegrityError("trace must contain exactly one root rollout entity")
    state = RolloutState(
        trace_id=manifest.trace_id,
        job_id=manifest.job_id,
        attempt=manifest.attempt,
        session_id=manifest.session_id,
        turn_id=manifest.turn_id,
        status=rollout.status,
        event_count=len(events),
        operations=sorted(operations.values(), key=lambda item: item.started_seq),
    )
    if write_state:
        _write_state(bundle_dir / "state.json", state)
    return state


def load_payload(bundle_dir: Path, payload_id: str) -> Any:
    if _PAYLOAD_ID_RE.fullmatch(payload_id) is None:
        raise TraceIntegrityError(f"invalid payload reference {payload_id}")
    path = bundle_dir / "payloads" / f"{payload_id}.json"
    if not path.is_file():
        raise TraceIntegrityError(f"payload file not found for reference {payload_id}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("payload_id") != payload_id:
        raise TraceIntegrityError(f"payload file does not match reference {payload_id}")
    if "value" not in raw:
        raise TraceIntegrityError(f"payload {payload_id} is missing value")
    return raw["value"]


def _read_manifest(bundle_dir: Path) -> TraceManifest:
    path = bundle_dir / "manifest.json"
    if not path.is_file():
        raise TraceIntegrityError(f"trace manifest not found: {path}")
    return TraceManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _read_events(path: Path) -> list[TraceEvent]:
    if not path.is_file():
        raise TraceIntegrityError(f"trace file not found: {path}")
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines.pop()
    return [TraceEvent.model_validate_json(line) for line in lines if line.strip()]


def _validate_event_identity(
    event: TraceEvent,
    manifest: TraceManifest,
    expected_seq: int,
) -> None:
    if event.seq != expected_seq:
        raise TraceIntegrityError(
            f"trace sequence expected {expected_seq}, found {event.seq}"
        )
    expected = (
        manifest.job_id,
        manifest.attempt,
        manifest.session_id,
        manifest.turn_id,
    )
    actual = (event.job_id, event.attempt, event.session_id, event.turn_id)
    if actual != expected:
        raise TraceIntegrityError(f"event {event.seq} identity does not match manifest")


def _validate_payload_refs(bundle_dir: Path, event: TraceEvent) -> None:
    for payload_id in event.payload_refs.values():
        load_payload(bundle_dir, payload_id)


def _write_state(path: Path, state: RolloutState) -> None:
    temp_path = path.with_suffix(".json.tmp")
    with temp_path.open("w", encoding="utf-8") as stream:
        stream.write(state.model_dump_json(indent=2))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp_path, path)
