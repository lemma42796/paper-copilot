from __future__ import annotations

from pathlib import Path

import pytest

from paper_copilot.cli.commands.doctor import _collect_sessions
from paper_copilot.session.store import SessionStore


@pytest.fixture
def isolated_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PAPER_COPILOT_HOME", str(tmp_path))
    return tmp_path


def test_collect_sessions_marks_legacy_session(isolated_root: Path) -> None:
    # session.jsonl with only header + final_output (no llm_call) — the
    # 2026-04-24 batch shape that prompted this fix.
    store = SessionStore.create("legacy0000aa", model="qwen3.6-flash", agent="MainAgent")
    store.append_final_output({"ok": True})

    aggs = _collect_sessions(n=10)

    assert len(aggs) == 1
    s = aggs[0]
    assert s.paper_id == "legacy0000aa"
    assert s.has_telemetry is False
    assert s.n_calls == 0
    assert s.input_tokens == 0
    assert s.cost_cny == 0.0
    assert s.latency_ms_total == 0


def test_collect_sessions_marks_modern_session(isolated_root: Path) -> None:
    store = SessionStore.create("modern0000bb", model="qwen3.6-flash", agent="MainAgent")
    store.append_llm_call(
        agent="SkimAgent",
        model="qwen3.6-flash",
        usage={
            "input_tokens": 1000,
            "output_tokens": 200,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 500,
        },
        latency_ms=1234,
        stop_reason="end_turn",
    )

    aggs = _collect_sessions(n=10)

    assert len(aggs) == 1
    s = aggs[0]
    assert s.paper_id == "modern0000bb"
    assert s.has_telemetry is True
    assert s.n_calls == 1
    assert s.input_tokens == 1000
    assert s.output_tokens == 200
    assert s.cache_read_tokens == 500
    assert s.latency_ms_total == 1234
    assert s.cost_cny > 0
