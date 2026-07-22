from pathlib import Path
from typing import Any

from paper_copilot.session import SessionStore, reconstruct_rollout


def test_reconstruct_rollout_reuses_completed_tool_result(tmp_path: Path) -> None:
    store = _store(tmp_path, "completed-tool")
    _append_llm_call(store, stop_reason="tool_use")
    store.append_tool_use("call-1", "search_papers", {"query": "attention"})
    store.append_tool_result("call-1", '{"papers":["p1"]}', is_error=False)

    recovered = reconstruct_rollout(
        store.read_all(),
        fallback_history=[{"role": "user", "content": "find papers"}],
    )

    assert recovered.history == [
        {"role": "user", "content": "find papers"},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "call-1",
                    "name": "search_papers",
                    "input": {"query": "attention"},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call-1",
                    "content": '{"papers":["p1"]}',
                    "is_error": False,
                }
            ],
        },
    ]


def test_reconstruct_rollout_marks_missing_tool_result_aborted(tmp_path: Path) -> None:
    store = _store(tmp_path, "aborted-tool")
    _append_llm_call(store, stop_reason="tool_use")
    store.append_tool_use("call-2", "search_papers", {"query": "transformer"})

    recovered = reconstruct_rollout(
        store.read_all(),
        fallback_history=[{"role": "user", "content": "find papers"}],
    )

    assert recovered.history[-1] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "call-2",
                "content": "aborted",
                "is_error": True,
            }
        ],
    }


def test_reconstruct_rollout_starts_from_latest_compaction(tmp_path: Path) -> None:
    store = _store(tmp_path, "compacted")
    _append_llm_call(store, stop_reason="end_turn")
    store.append_message("assistant", "obsolete response")
    replacement = [
        {
            "role": "user",
            "content": [{"type": "text", "text": "compacted context"}],
        }
    ]
    summary = {"summary_version": 1, "task": "compare papers"}
    store.append_compaction(
        summary_version=1,
        source_message_count=4,
        retained_message_count=1,
        trigger_estimated_input_tokens=200_000,
        estimated_before_tokens=200_000,
        estimated_after_tokens=20_000,
        estimated_retained_recent_tokens=5_000,
        summary_output_tokens=300,
        model="test-model",
        summary=summary,
        replacement_history=replacement,
    )
    store.append_runtime_state({"main_cost": {"input_tokens": 20}})
    _append_llm_call(store, stop_reason="end_turn")
    store.append_message("assistant", "current response")
    store.append_runtime_state({"main_cost": {"input_tokens": 30}})

    recovered = reconstruct_rollout(
        store.read_all(),
        fallback_history=[{"role": "user", "content": "obsolete request"}],
    )

    assert recovered.history == [
        *replacement,
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "current response"}],
        },
    ]
    assert recovered.runtime_state == {"main_cost": {"input_tokens": 30}}
    assert recovered.compaction_summary == summary


def test_reconstruct_rollout_uses_latest_recovery_base(tmp_path: Path) -> None:
    store = _store(tmp_path, "recovered-twice")
    store.append_recovery_base(
        source_session_path="attempt-1/session.jsonl",
        history=[{"role": "user", "content": "attempt one"}],
        runtime_state={"attempt": 1},
        compaction_summary={"summary_version": 1},
    )
    store.append_message("assistant", "obsolete resumed output")
    latest_history: list[dict[str, Any]] = [
        {"role": "user", "content": "attempt two"}
    ]
    store.append_recovery_base(
        source_session_path="attempt-2/session.jsonl",
        history=latest_history,
        runtime_state={"attempt": 2},
        compaction_summary={"summary_version": 2},
    )
    store.append_tool_use("call-3", "search_papers", {})

    recovered = reconstruct_rollout(
        store.read_all(),
        fallback_history=[{"role": "user", "content": "original"}],
    )

    assert recovered.history[:1] == latest_history
    assert "obsolete resumed output" not in str(recovered.history)
    assert recovered.history[-1]["content"][0]["content"] == "aborted"
    assert recovered.runtime_state == {"attempt": 2}
    assert recovered.compaction_summary == {"summary_version": 2}


def _store(tmp_path: Path, session_id: str) -> SessionStore:
    return SessionStore.create(
        session_id,
        model="test-model",
        agent="paper_copilot",
        root=tmp_path,
    )


def _append_llm_call(store: SessionStore, *, stop_reason: str) -> None:
    store.append_llm_call(
        agent="paper_copilot",
        model="test-model",
        usage={"input_tokens": 10, "output_tokens": 5},
        latency_ms=1,
        stop_reason=stop_reason,
    )
