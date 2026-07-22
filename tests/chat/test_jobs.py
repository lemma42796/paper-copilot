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

from paper_copilot.agents import paper_copilot as paper_copilot_module
from paper_copilot.agents.loop import (
    LLMResponse,
    TextBlock,
    ToolResultData,
    ToolUseBlock,
    ToolUseRequest,
)
from paper_copilot.agents.paper_copilot import PaperCopilotContext
from paper_copilot.api import http
from paper_copilot.chat import runtime
from paper_copilot.chat.jobs import (
    ChatJobAttempt,
    ChatJobEvent,
    ChatJobRecord,
    ChatJobRegistry,
    ChatJobSpec,
)
from paper_copilot.session import SessionStore, TurnAborted
from paper_copilot.session import ToolResult as SessionToolResult
from paper_copilot.session import ToolUse as SessionToolUse
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
            usage={"input_tokens": 10, "output_tokens": 5},
        )


class _ToolThenDisconnectLLM:
    calls: ClassVar[int] = 0

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
        system: str | list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        type(self).calls += 1
        if type(self).calls == 1:
            return LLMResponse(
                content=[
                    ToolUseBlock(
                        id="call-persisted",
                        name="search_papers",
                        input={"query": "recovery"},
                    )
                ],
                stop_reason="tool_use",
                usage={"input_tokens": 10, "output_tokens": 5},
            )
        raise AgentError("simulated outage after completed tool")


class _ToolBeforeDispatchFailureLLM:
    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
        system: str | list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        return LLMResponse(
            content=[
                ToolUseBlock(
                    id="call-aborted",
                    name="search_papers",
                    input={"query": "interrupted"},
                )
            ],
            stop_reason="tool_use",
            usage={"input_tokens": 10, "output_tokens": 5},
        )


class _ToolThenBlockedDispatchLLM:
    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
        system: str | list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        return LLMResponse(
            content=[
                ToolUseBlock(
                    id="call-user-interrupted",
                    name="search_papers",
                    input={"query": "long running"},
                )
            ],
            stop_reason="tool_use",
            usage={"input_tokens": 10, "output_tokens": 5},
        )


class _RepeatedToolLoopLLM:
    calls: ClassVar[int] = 0

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
        system: str | list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        type(self).calls += 1
        return LLMResponse(
            content=[
                ToolUseBlock(
                    id=f"call-loop-{type(self).calls}",
                    name="search_papers",
                    input={"query": "same forever"},
                )
            ],
            stop_reason="tool_use",
            usage={"input_tokens": 10, "output_tokens": 5},
        )


class _ResumeInspectLLM:
    calls: ClassVar[list[list[dict[str, Any]]]] = []

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
        system: str | list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        type(self).calls.append(deepcopy(messages))
        return LLMResponse(
            content=[TextBlock(text="rollout 恢复完成")],
            stop_reason="end_turn",
            usage={"input_tokens": 10, "output_tokens": 5},
        )


class _ResumeInspectThenDisconnectLLM:
    calls: ClassVar[list[list[dict[str, Any]]]] = []

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
        system: str | list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        type(self).calls.append(deepcopy(messages))
        raise AgentError("simulated second interruption")


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


def test_resume_reuses_completed_tool_result_without_dispatching_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ToolThenDisconnectLLM.calls = 0
    _ResumeInspectLLM.calls = []
    dispatch_count = 0

    def fake_dispatch(
        _req: ToolUseRequest,
        _context: PaperCopilotContext,
    ) -> ToolResultData:
        nonlocal dispatch_count
        dispatch_count += 1
        return ToolResultData(output="persisted tool result")

    _use_llm(monkeypatch, _ToolThenDisconnectLLM)
    monkeypatch.setattr(
        paper_copilot_module,
        "dispatch_paper_copilot_tool",
        fake_dispatch,
    )
    registry = ChatJobRegistry(tmp_path)
    created = registry.create(
        ChatJobSpec(
            request="verify completed tool recovery",
            record_quality=False,
            update_report=False,
        )
    )
    failed = _wait_for_registry_status(registry, created.id, expected="failed")

    assert dispatch_count == 1
    _use_llm(monkeypatch, _ResumeInspectLLM)
    registry.resume(created.id)
    completed = _wait_for_registry_status(registry, created.id, expected="completed")

    assert dispatch_count == 1
    assert [attempt.status for attempt in completed.attempts] == [
        "failed",
        "completed",
    ]
    assert completed.attempts[1].resumed_from_attempt == 1
    assert failed.attempts[0].session_id != completed.attempts[1].session_id
    result = _tool_result(_ResumeInspectLLM.calls[0], "call-persisted")
    assert result == {
        "type": "tool_result",
        "tool_use_id": "call-persisted",
        "content": "persisted tool result",
        "is_error": False,
    }


def test_resume_marks_missing_result_aborted_across_multiple_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ResumeInspectThenDisconnectLLM.calls = []
    _ResumeInspectLLM.calls = []
    dispatch_count = 0

    def failing_dispatch(
        _req: ToolUseRequest,
        _context: PaperCopilotContext,
    ) -> ToolResultData:
        nonlocal dispatch_count
        dispatch_count += 1
        raise AgentError("simulated crash before tool result persistence")

    _use_llm(monkeypatch, _ToolBeforeDispatchFailureLLM)
    monkeypatch.setattr(
        paper_copilot_module,
        "dispatch_paper_copilot_tool",
        failing_dispatch,
    )
    registry = ChatJobRegistry(tmp_path)
    created = registry.create(
        ChatJobSpec(
            request="verify aborted tool recovery",
            record_quality=False,
            update_report=False,
        )
    )
    _wait_for_registry_status(registry, created.id, expected="failed")

    assert dispatch_count == 1
    _use_llm(monkeypatch, _ResumeInspectThenDisconnectLLM)
    registry.resume(created.id)
    _wait_for_registry_status(registry, created.id, expected="failed")
    first_recovery_result = _tool_result(
        _ResumeInspectThenDisconnectLLM.calls[0],
        "call-aborted",
    )

    assert first_recovery_result["content"] == "aborted"
    assert first_recovery_result["is_error"] is True
    assert dispatch_count == 1

    _use_llm(monkeypatch, _ResumeInspectLLM)
    registry.resume(created.id)
    completed = _wait_for_registry_status(registry, created.id, expected="completed")

    assert dispatch_count == 1
    assert [attempt.status for attempt in completed.attempts] == [
        "failed",
        "failed",
        "completed",
    ]
    assert [attempt.resumed_from_attempt for attempt in completed.attempts] == [
        None,
        1,
        2,
    ]
    assert len(_tool_results(_ResumeInspectLLM.calls[0], "call-aborted")) == 1
    assert _tool_result(_ResumeInspectLLM.calls[0], "call-aborted")["content"] == (
        "aborted"
    )


def test_repeated_tool_loop_fails_job_and_resume_sees_aborted_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _RepeatedToolLoopLLM.calls = 0
    _ResumeInspectLLM.calls = []
    dispatch_count = 0

    def fake_dispatch(
        _req: ToolUseRequest,
        _context: PaperCopilotContext,
    ) -> ToolResultData:
        nonlocal dispatch_count
        dispatch_count += 1
        return ToolResultData(output="same result")

    _use_llm(monkeypatch, _RepeatedToolLoopLLM)
    monkeypatch.setattr(
        paper_copilot_module,
        "dispatch_paper_copilot_tool",
        fake_dispatch,
    )
    registry = ChatJobRegistry(tmp_path)
    created = registry.create(
        ChatJobSpec(
            request="verify repeated tool loop guard",
            record_quality=False,
            update_report=False,
        )
    )
    failed = _wait_for_registry_status(registry, created.id, expected="failed")
    diagnostics = registry.diagnostics(created.id)

    assert dispatch_count == 2
    assert "tool loop blocked before dispatch" in (failed.error or "")
    assert diagnostics.first_error is not None
    assert diagnostics.first_error.entity_id == "call-loop-3"
    assert diagnostics.first_error.error_type == "ToolLoopError"
    assert diagnostics.repeated_tool_calls[0].count == 3

    _use_llm(monkeypatch, _ResumeInspectLLM)
    registry.resume(created.id)
    completed = _wait_for_registry_status(registry, created.id, expected="completed")

    assert dispatch_count == 2
    assert [attempt.status for attempt in completed.attempts] == ["failed", "completed"]
    recovered = _tool_result(_ResumeInspectLLM.calls[0], "call-loop-3")
    assert recovered["content"] == "aborted"
    assert recovered["is_error"] is True


def test_http_interrupt_cancels_tool_and_resume_sees_aborted_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatch_started = threading.Event()
    dispatch_count = 0
    _ResumeInspectLLM.calls = []

    async def blocking_dispatch(
        _req: ToolUseRequest,
        _context: PaperCopilotContext,
        *,
        read_llm: Any,
        cost: Any,
        max_budget_cny: float,
    ) -> ToolResultData:
        nonlocal dispatch_count
        dispatch_count += 1
        dispatch_started.set()
        await asyncio.Event().wait()
        raise AssertionError("blocked dispatch should be cancelled")

    _use_llm(monkeypatch, _ToolThenBlockedDispatchLLM)
    monkeypatch.setattr(
        paper_copilot_module,
        "dispatch_paper_copilot_tool_async",
        blocking_dispatch,
    )

    with _api_server() as api_url:
        created = _request_json(
            "POST",
            f"{api_url}/jobs",
            {
                "message": "interrupt this tool",
                "root": str(tmp_path),
                "record_quality": False,
                "update_report": False,
            },
        )
        job_id = str(created["id"])
        assert dispatch_started.wait(timeout=2)

        accepted = _request_json(
            "POST",
            _job_url(api_url, job_id, tmp_path, action="interrupt"),
            {"root": str(tmp_path)},
        )
        interrupted = _wait_for_http_status(
            api_url,
            job_id,
            tmp_path,
            expected="interrupted",
        )
        interrupted_diagnostics = _request_json(
            "GET",
            _job_url(api_url, job_id, tmp_path, action="diagnostics"),
        )

        assert accepted["status"] == "running"
        assert dispatch_count == 1
        first_attempt = interrupted["attempts"][0]
        entries = SessionStore.load(
            str(first_attempt["session_id"]),
            root=tmp_path,
        ).read_all()
        assert any(isinstance(entry, SessionToolUse) for entry in entries)
        assert not any(isinstance(entry, SessionToolResult) for entry in entries)
        assert any(isinstance(entry, TurnAborted) for entry in entries)

        _use_llm(monkeypatch, _ResumeInspectLLM)
        _request_json(
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

    assert dispatch_count == 1
    assert interrupted_diagnostics["status"] == "cancelled"
    assert interrupted_diagnostics["unfinished_operations"] == []
    assert [attempt["status"] for attempt in completed["attempts"]] == [
        "interrupted",
        "completed",
    ]
    recovered_result = _tool_result(
        _ResumeInspectLLM.calls[0],
        "call-user-interrupted",
    )
    assert recovered_result["content"] == "aborted"
    assert recovered_result["is_error"] is True


def test_follow_up_job_receives_completed_turns_from_same_conversation(
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
    second_content = _ConversationLLM.calls[1][0]["content"]
    assert isinstance(second_content, list)
    assert second_content[0]["text"].startswith("<runtime_context>\n")
    assert second_content[1]["text"].startswith("<conversation_context>\n")
    assert '"compaction_summary":null' in second_content[1]["text"]
    assert "第一轮: 比较方法 A 和 B" in second_content[1]["text"]
    assert "第 1 轮回答" in second_content[1]["text"]
    assert second_content[2] == {"type": "text", "text": "第二轮: 为什么推荐 A?"}


def _use_llm(
    monkeypatch: pytest.MonkeyPatch,
    llm_type: type[object],
) -> None:
    monkeypatch.setattr(runtime, "LLMClient", llm_type)
    monkeypatch.setattr(runtime, "default_pdf_dir", lambda: None)


def _tool_results(
    messages: list[dict[str, Any]],
    tool_use_id: str,
) -> list[dict[str, Any]]:
    return [
        block
        for message in messages
        for block in _content_blocks(message)
        if block.get("type") == "tool_result"
        and block.get("tool_use_id") == tool_use_id
    ]


def _tool_result(
    messages: list[dict[str, Any]],
    tool_use_id: str,
) -> dict[str, Any]:
    results = _tool_results(messages, tool_use_id)
    assert len(results) == 1
    return results[0]


def _content_blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


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
