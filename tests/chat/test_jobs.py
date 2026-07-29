from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from paper_copilot.agents.loop import (
    LLMResponse,
    TextBlock,
)
from paper_copilot.api import http
from paper_copilot.chat import runtime
from paper_copilot.chat.jobs import (
    ChatJobAttempt,
    ChatJobEvent,
    ChatJobRecord,
    ChatJobRegistry,
    ChatJobSpec,
)
from paper_copilot.session import SessionStore
from paper_copilot.shared.errors import AgentError


class _DirectAnswerLLM:
    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
        system: str | list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        return LLMResponse(
            content=[TextBlock(text="恢复验收完成")],
            stop_reason="end_turn",
            usage={"input_tokens": 10, "output_tokens": 5},
        )


class _DisconnectedLLM:
    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
        system: str | list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        raise AgentError("simulated network outage")


class _BlockingLLM:
    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
        system: str | list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        await asyncio.Event().wait()
        raise AssertionError("rollout deadline must cancel the LLM call")


class _ConversationLLM:
    calls: ClassVar[list[list[dict[str, Any]]]] = []

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
        system: str | list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.calls.append(deepcopy(messages))
        return LLMResponse(
            content=[TextBlock(text=f"第 {len(self.calls)} 轮回答")],
            stop_reason="end_turn",
            usage={"input_tokens": 10 * len(self.calls), "output_tokens": 5},
        )


def test_http_job_completes_after_request_client_disconnects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_llm(monkeypatch, _DirectAnswerLLM)

    with _api_server() as api_url:
        created = _request_json(
            "POST",
            f"{api_url}/jobs",
            {
                "message": "客户端关闭后继续执行",
                "root": str(tmp_path),
                "record_quality": False,
                "update_report": False,
            },
        )
        job_id = str(created["id"])

        completed = _wait_for_http_status(
            api_url,
            job_id,
            tmp_path,
            expected="completed",
        )
        events = _request_json(
            "GET",
            _job_url(api_url, job_id, tmp_path, action="events"),
        )

    assert completed["result"]["report_markdown"] == "恢复验收完成"
    assert completed["attempts"][0]["status"] == "completed"
    assert [event["type"] for event in events["events"]] == [
        "created",
        "started",
        "progress",
        "progress",
        "completed",
    ]


def test_http_job_diagnostics_reduces_completed_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_llm(monkeypatch, _DirectAnswerLLM)

    with _api_server() as api_url:
        created = _request_json(
            "POST",
            f"{api_url}/jobs",
            {
                "message": "检查本地 trace 诊断",
                "root": str(tmp_path),
                "record_quality": False,
                "update_report": False,
            },
        )
        job_id = str(created["id"])
        _wait_for_http_status(api_url, job_id, tmp_path, expected="completed")
        diagnostics = _request_json(
            "GET",
            _job_url(api_url, job_id, tmp_path, action="diagnostics"),
        )

    attempt_dir = tmp_path / "jobs" / job_id / "attempts" / "1"
    assert diagnostics["job_id"] == job_id
    assert diagnostics["attempt"] == 1
    assert diagnostics["status"] == "completed"
    assert diagnostics["total_duration_ms"] is not None
    assert diagnostics["phase_duration_ms"]["rollout"] >= 0
    assert diagnostics["phase_duration_ms"]["turn"] >= 0
    assert diagnostics["unfinished_operations"] == []
    assert (attempt_dir / "state.json").is_file()


def test_failed_job_waits_for_explicit_resume_and_creates_new_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_llm(monkeypatch, _DisconnectedLLM)

    with _api_server() as api_url:
        created = _request_json(
            "POST",
            f"{api_url}/jobs",
            {
                "message": "断网后恢复",
                "root": str(tmp_path),
                "record_quality": False,
                "update_report": False,
            },
        )
        job_id = str(created["id"])
        failed = _wait_for_http_status(
            api_url,
            job_id,
            tmp_path,
            expected="failed",
        )
        failed_diagnostics = _request_json(
            "GET",
            _job_url(api_url, job_id, tmp_path, action="diagnostics"),
        )

        time.sleep(0.05)
        unchanged = _request_json("GET", _job_url(api_url, job_id, tmp_path))
        assert unchanged["status"] == "failed"
        assert len(unchanged["attempts"]) == 1

        _use_llm(monkeypatch, _DirectAnswerLLM)
        resumed = _request_json(
            "POST",
            _job_url(api_url, job_id, tmp_path, action="resume"),
            {"root": str(tmp_path)},
        )
        completed = _wait_for_http_status(
            api_url,
            job_id,
            tmp_path,
            expected="completed",
        )

    assert failed["attempts"][0]["status"] == "failed"
    assert failed_diagnostics["status"] == "failed"
    assert failed_diagnostics["first_error"]["error_type"] == "AgentError"
    assert failed_diagnostics["unfinished_operations"] == []
    assert resumed["status"] == "queued"
    assert [attempt["status"] for attempt in completed["attempts"]] == [
        "failed",
        "completed",
    ]
    assert completed["attempts"][0]["session_id"] != completed["attempts"][1][
        "session_id"
    ]


def test_rollout_deadline_fails_attempt_without_marking_user_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_llm(monkeypatch, _BlockingLLM)
    registry = ChatJobRegistry(tmp_path)
    created = registry.create(
        ChatJobSpec(
            request="verify rollout deadline",
            record_quality=False,
            update_report=False,
            rollout_timeout_seconds=0.02,
        )
    )

    failed = _wait_for_registry_status(registry, created.id, expected="failed")
    diagnostics = registry.diagnostics(created.id)

    assert failed.attempts[0].status == "failed"
    assert failed.error == "rollout attempt timed out after 0.02 seconds"
    assert registry.events(created.id)[-1].type == "failed"
    assert diagnostics.status == "failed"
    assert diagnostics.first_error is not None
    assert diagnostics.first_error.entity_type == "rollout"
    assert diagnostics.first_error.error_type == "RolloutTimeoutError"
    assert diagnostics.unfinished_operations == []


def test_registry_restart_marks_running_job_interrupted_until_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = "job-20260722T120000-1234567890"
    _write_running_job(tmp_path, job_id)

    registry = ChatJobRegistry(tmp_path)
    interrupted = registry.get(job_id)

    assert interrupted.status == "interrupted"
    assert [attempt.status for attempt in interrupted.attempts] == ["interrupted"]
    assert registry.events(job_id)[-1].type == "interrupted"

    time.sleep(0.05)
    unchanged = registry.get(job_id)
    assert unchanged.status == "interrupted"
    assert len(unchanged.attempts) == 1

    _use_llm(monkeypatch, _DirectAnswerLLM)
    resumed = registry.resume(job_id)
    completed = _wait_for_registry_status(registry, job_id, expected="completed")

    assert resumed.status == "queued"
    assert [attempt.status for attempt in completed.attempts] == [
        "interrupted",
        "completed",
    ]
    assert [event.type for event in registry.events(job_id)][-3:] == [
        "progress",
        "progress",
        "completed",
    ]


def test_follow_up_job_appends_completed_rollout_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ConversationLLM.calls = []
    monkeypatch.setattr(runtime, "LLMClient", _ConversationLLM)
    monkeypatch.setattr(runtime, "default_pdf_dir", lambda: None)
    registry = ChatJobRegistry(tmp_path)

    first = registry.create(
        ChatJobSpec(
            request="第一轮: 比较方法 A 和 B",
            record_quality=False,
            update_report=False,
        )
    )
    first_completed = _wait_for_registry_status(
        registry,
        first.id,
        expected="completed",
    )
    conversation_id = first_completed.spec.conversation_id
    assert conversation_id is not None

    second = registry.create(
        ChatJobSpec(
            request="第二轮: 为什么推荐 A?",
            conversation_id=conversation_id,
            record_quality=False,
            update_report=False,
        )
    )
    second_completed = _wait_for_registry_status(
        registry,
        second.id,
        expected="completed",
    )

    assert second_completed.spec.conversation_id == conversation_id
    second_messages = _ConversationLLM.calls[1]
    assert second_messages[0] == {
        "role": "user",
        "content": "第一轮: 比较方法 A 和 B",
    }
    assert second_messages[1]["role"] == "assistant"
    assert second_messages[1]["content"] == [
        {"type": "text", "text": "第 1 轮回答"}
    ]
    second_content = second_messages[-1]["content"]
    assert isinstance(second_content, list)
    assert second_content[0]["text"].startswith("<runtime_context>\n")
    assert not any(
        block["text"].startswith("<conversation_context>\n")
        for block in second_content
    )
    assert second_content[-1] == {
        "type": "text",
        "text": "第二轮: 为什么推荐 A?",
    }
    assert first_completed.context_usage is not None
    assert second_completed.context_usage is not None
    assert (
        second_completed.context_usage.context_tokens
        > first_completed.context_usage.context_tokens
    )


def test_conversation_context_carries_persistent_research_exclusions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ConversationLLM.calls = []
    monkeypatch.setattr(runtime, "LLMClient", _ConversationLLM)
    monkeypatch.setattr(runtime, "default_pdf_dir", lambda: None)
    registry = ChatJobRegistry(tmp_path)
    first = registry.create(
        ChatJobSpec(
            request="后续排除主要无监督论文",
            record_quality=False,
            update_report=False,
        )
    )
    first_completed = _wait_for_registry_status(
        registry,
        first.id,
        expected="completed",
    )
    assert first_completed.result is not None
    first_store = SessionStore(
        Path(first_completed.result.session_path),
        last_id="",
    )
    excluded_pdf_sha256 = "a" * 64
    first_store.append_application_event(
        namespace="research_scope",
        name="exclusions_updated",
        payload={
            "schema_version": 1,
            "exclusions": [
                {
                    "pdf_sha256": excluded_pdf_sha256,
                    "reason": "主要设定为无监督学习",
                    "evidence_refs": [
                        f"[{excluded_pdf_sha256}:page[4]]"
                    ],
                }
            ],
        },
    )
    conversation_id = first_completed.spec.conversation_id
    assert conversation_id is not None
    pending = ChatJobRecord(
        id="job-follow-up-scope",
        status="queued",
        created_at="9999-01-01T00:00:00+00:00",
        updated_at="9999-01-01T00:00:00+00:00",
        spec=ChatJobSpec(
            request="继续复核",
            conversation_id=conversation_id,
            record_quality=False,
            update_report=False,
        ),
    )

    _context, _summary, exclusions, previous_record = (
        registry._build_conversation_context(pending)
    )

    assert [exclusion.pdf_sha256 for exclusion in exclusions] == [
        excluded_pdf_sha256
    ]
    assert previous_record is not None
    assert previous_record.id == first_completed.id


def _use_llm(
    monkeypatch: pytest.MonkeyPatch,
    llm_type: type[object],
) -> None:
    monkeypatch.setattr(runtime, "LLMClient", llm_type)
    monkeypatch.setattr(runtime, "default_pdf_dir", lambda: None)


@contextmanager
def _api_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), http._ChatHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request_json(
    method: str,
    url: str,
    payload: dict[str, object] | None = None,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urlopen(request, timeout=3) as response:
        decoded = json.loads(response.read().decode("utf-8"))
    assert isinstance(decoded, dict)
    return decoded


def _job_url(
    api_url: str,
    job_id: str,
    root: Path,
    *,
    action: str | None = None,
) -> str:
    suffix = f"/{action}" if action is not None else ""
    query = urlencode({"root": str(root)})
    return f"{api_url}/jobs/{job_id}{suffix}?{query}"


def _wait_for_http_status(
    api_url: str,
    job_id: str,
    root: Path,
    *,
    expected: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        record = _request_json("GET", _job_url(api_url, job_id, root))
        if record["status"] == expected:
            return record
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {expected}")


def _wait_for_registry_status(
    registry: ChatJobRegistry,
    job_id: str,
    *,
    expected: str,
) -> ChatJobRecord:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        record = registry.get(job_id)
        if record.status == expected:
            return record
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {expected}")


def _write_running_job(root: Path, job_id: str) -> None:
    created_at = "2026-07-22T12:00:00+00:00"
    session_id = f"paper-copilot-{job_id}-attempt-1"
    job_dir = root / "jobs" / job_id
    job_dir.mkdir(parents=True)
    record = ChatJobRecord(
        id=job_id,
        status="running",
        created_at=created_at,
        updated_at=created_at,
        spec=ChatJobSpec(
            request="服务重启后恢复",
            record_quality=False,
            update_report=False,
        ),
        attempts=[
            ChatJobAttempt(
                number=1,
                status="running",
                session_id=session_id,
                session_path=str(root / "papers" / session_id / "session.jsonl"),
                started_at=created_at,
            )
        ],
    )
    events = [
        ChatJobEvent(
            seq=1,
            ts=created_at,
            type="created",
            status="queued",
            attempt=0,
            message="任务已创建。",
        ),
        ChatJobEvent(
            seq=2,
            ts=created_at,
            type="started",
            status="running",
            attempt=1,
            message="任务已开始。",
        ),
    ]
    (job_dir / "job.json").write_text(record.model_dump_json(indent=2), encoding="utf-8")
    (job_dir / "events.jsonl").write_text(
        "".join(event.model_dump_json() + "\n" for event in events),
        encoding="utf-8",
    )
