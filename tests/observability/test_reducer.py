from __future__ import annotations

import json
from pathlib import Path

import pytest

from paper_copilot.observability import (
    RolloutRecorder,
    diagnose_rollout,
    reduce_trace_bundle,
)
from paper_copilot.shared.errors import TraceIntegrityError


def test_diagnostics_identifies_first_error_slow_calls_and_repeated_tools(
    tmp_path: Path,
) -> None:
    recorder = _recorder(tmp_path)
    _start_rollout(recorder)
    with (
        recorder.activate(),
        recorder.operation(
            "turn",
            recorder.turn_id,
            parent_entity_id=recorder.rollout_entity_id,
        ),
    ):
        for index in range(3):
            with recorder.operation(
                "tool_call",
                f"tool-{index}",
                attributes={"tool_name": "search_papers"},
                input_payload={"query": "same query"},
            ) as operation:
                is_error = index == 0
                operation.set_result(
                    status="failed" if is_error else "completed",
                    output_payload={
                        "output": "simulated tool failure" if is_error else "ok",
                        "is_error": is_error,
                    },
                )
    _complete_rollout(recorder, duration_ms=2500)

    state = reduce_trace_bundle(recorder.bundle_dir)
    diagnostics = diagnose_rollout(
        recorder.bundle_dir,
        state,
        slow_ms=0,
        repeat_threshold=3,
    )

    assert state.status == "completed"
    assert (recorder.bundle_dir / "state.json").is_file()
    assert diagnostics.total_duration_ms == 2500
    assert diagnostics.first_error is not None
    assert diagnostics.first_error.entity_id == "tool-0"
    assert diagnostics.first_error.error_message == "simulated tool failure"
    assert {operation.entity_id for operation in diagnostics.slow_operations} == {
        "turn-1",
        "tool-0",
        "tool-1",
        "tool-2",
    }
    assert len(diagnostics.repeated_tool_calls) == 1
    assert diagnostics.repeated_tool_calls[0].tool_name == "search_papers"
    assert diagnostics.repeated_tool_calls[0].count == 3


def test_diagnostics_lists_unfinished_operations_for_live_trace(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path)
    _start_rollout(recorder)
    recorder.record(
        entity_type="llm_call",
        entity_id="llm-live",
        parent_entity_id=recorder.rollout_entity_id,
        event_type="llm_call.started",
        status="running",
        attributes={"model": "test-model"},
    )

    state = reduce_trace_bundle(recorder.bundle_dir)
    diagnostics = diagnose_rollout(recorder.bundle_dir, state)

    assert state.status == "running"
    assert diagnostics.total_duration_ms is None
    assert [operation.entity_id for operation in diagnostics.unfinished_operations] == [
        recorder.rollout_entity_id,
        "llm-live",
    ]


def test_reducer_ignores_torn_trace_tail(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path)
    _start_rollout(recorder)
    trace_path = recorder.bundle_dir / "trace.jsonl"
    with trace_path.open("a", encoding="utf-8") as stream:
        stream.write('{"schema_version":1,"seq":2')

    state = reduce_trace_bundle(recorder.bundle_dir)

    assert state.event_count == 1
    assert state.status == "running"


def test_reducer_rejects_sequence_gap(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path)
    _start_rollout(recorder)
    trace_path = recorder.bundle_dir / "trace.jsonl"
    event = json.loads(trace_path.read_text(encoding="utf-8"))
    event["seq"] = 2
    trace_path.write_text(json.dumps(event) + "\n", encoding="utf-8")

    with pytest.raises(TraceIntegrityError, match="sequence expected 1, found 2"):
        reduce_trace_bundle(recorder.bundle_dir)


def test_reducer_rejects_missing_payload(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path)
    recorder.record(
        entity_type="rollout",
        entity_id=recorder.rollout_entity_id,
        event_type="rollout.started",
        status="running",
        payloads={"request": {"text": "sensitive request"}},
    )
    next((recorder.bundle_dir / "payloads").glob("*.json")).unlink()

    with pytest.raises(TraceIntegrityError, match="payload file not found"):
        reduce_trace_bundle(recorder.bundle_dir)


def test_reducer_rejects_duplicate_terminal_event(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path)
    _start_rollout(recorder)
    _complete_rollout(recorder, duration_ms=10)
    _complete_rollout(recorder, duration_ms=11)

    with pytest.raises(TraceIntegrityError, match="more than one terminal event"):
        reduce_trace_bundle(recorder.bundle_dir)


def test_payload_redacts_secrets_and_truncates_long_strings(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path)
    recorder.record(
        entity_type="rollout",
        entity_id=recorder.rollout_entity_id,
        event_type="rollout.started",
        status="running",
        payloads={
            "request": {
                "headers": {
                    "Authorization": "Bearer top-secret-token",
                    "x-api-key": "sk-super-secret-key",
                },
                "prompt": "api_key=inline-secret " + ("x" * 2_100),
                "nested": {"password": "do-not-write"},
            }
        },
    )
    payload_path = next((recorder.bundle_dir / "payloads").glob("*.json"))
    raw_text = payload_path.read_text(encoding="utf-8")
    raw = json.loads(raw_text)

    assert "top-secret-token" not in raw_text
    assert "sk-super-secret-key" not in raw_text
    assert "inline-secret" not in raw_text
    assert "do-not-write" not in raw_text
    assert raw["value"]["headers"]["Authorization"] == "[REDACTED]"
    assert raw["value"]["headers"]["x-api-key"] == "[REDACTED]"
    assert raw["value"]["prompt"]["_trace_value"] == "truncated_string"
    assert raw["value"]["prompt"]["length"] > 2_000


def test_payload_file_size_is_bounded_and_policy_is_in_manifest(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path)
    recorder.record(
        entity_type="rollout",
        entity_id=recorder.rollout_entity_id,
        event_type="rollout.started",
        status="running",
        payloads={
            "request": {
                "rows": [
                    {f"field-{field}": "x" * 2_500 for field in range(5)}
                    for _ in range(50)
                ]
            }
        },
    )
    payload_path = next((recorder.bundle_dir / "payloads").glob("*.json"))
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    manifest = json.loads(
        (recorder.bundle_dir / "manifest.json").read_text(encoding="utf-8")
    )

    assert payload_path.stat().st_size < 32_000
    assert payload["value"]["_trace_value"] == "truncated_payload"
    assert payload["value"]["sanitized_bytes"] > 262_144
    assert manifest["payload_policy"] == "local_safe_v1"
    assert manifest["payload_max_bytes"] == 262_144
    assert manifest["payload_max_string_chars"] == 2_000


def test_legacy_manifest_without_payload_policy_remains_reducible(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path)
    _start_rollout(recorder)
    manifest_path = recorder.bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("payload_policy")
    manifest.pop("payload_max_bytes")
    manifest.pop("payload_max_string_chars")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    state = reduce_trace_bundle(recorder.bundle_dir)

    assert state.status == "running"


def _recorder(tmp_path: Path) -> RolloutRecorder:
    return RolloutRecorder.create(
        tmp_path / "attempt",
        job_id="job-12345678",
        attempt=1,
        session_id="session-1",
        turn_id="turn-1",
    )


def _start_rollout(recorder: RolloutRecorder) -> None:
    recorder.record(
        entity_type="rollout",
        entity_id=recorder.rollout_entity_id,
        event_type="rollout.started",
        status="running",
    )


def _complete_rollout(recorder: RolloutRecorder, *, duration_ms: int) -> None:
    recorder.record(
        entity_type="rollout",
        entity_id=recorder.rollout_entity_id,
        event_type="rollout.completed",
        status="completed",
        duration_ms=duration_ms,
    )
