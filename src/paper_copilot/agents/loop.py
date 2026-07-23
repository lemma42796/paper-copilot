"""Agent loop: async generator driven by an injected LLM client.

See `run_agent_loop` for termination and cost semantics.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from paper_copilot.observability import current_llm_call_id, current_recorder
from paper_copilot.session import SessionStore
from paper_copilot.shared.cost import (
    CostSnapshot,
    CostTracker,
    UsageLike,
    read_usage_field,
)
from paper_copilot.shared.errors import AgentError, ToolLoopError, ToolTimeoutError
from paper_copilot.shared.logging import get_logger
from paper_copilot.shared.prompt_fingerprint import compute_prompt_sha256

__all__ = [
    "AssistantMessage",
    "ContentBlock",
    "Event",
    "LLMClientProtocol",
    "LLMResponse",
    "LLMStreamEvent",
    "LLMStreamEventCallback",
    "LoopConfig",
    "StopReason",
    "TerminateReason",
    "Terminated",
    "TextBlock",
    "ToolResult",
    "ToolResultData",
    "ToolUse",
    "ToolUseBlock",
    "ToolUseRequest",
    "emit_llm_stream_event",
    "llm_stream_events",
    "run_agent_loop",
]


# ---- LLM content blocks --------------------------------------------------


@dataclass(frozen=True, slots=True)
class TextBlock:
    text: str
    type: Literal["text"] = "text"


@dataclass(frozen=True, slots=True)
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]
    type: Literal["tool_use"] = "tool_use"


type ContentBlock = TextBlock | ToolUseBlock


# ---- LLM client surface --------------------------------------------------


type StopReason = Literal["end_turn", "tool_use"]


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: list[ContentBlock]
    stop_reason: StopReason
    usage: UsageLike | None = None
    latency_ms: int = 0
    reasoning_content: str = ""


@dataclass(frozen=True, slots=True)
class LLMStreamEvent:
    response_id: str
    type: Literal[
        "reasoning_started",
        "reasoning_delta",
        "reasoning_completed",
        "assistant_started",
        "assistant_delta",
        "assistant_completed",
    ]
    text: str = ""


type LLMStreamEventCallback = Callable[[LLMStreamEvent], None]


_LLM_STREAM_EVENT_CALLBACK: ContextVar[LLMStreamEventCallback | None] = ContextVar(
    "paper_copilot_llm_stream_event_callback",
    default=None,
)


@contextmanager
def llm_stream_events(
    callback: LLMStreamEventCallback | None,
) -> Iterator[None]:
    token = _LLM_STREAM_EVENT_CALLBACK.set(callback)
    try:
        yield
    finally:
        _LLM_STREAM_EVENT_CALLBACK.reset(token)


def emit_llm_stream_event(event: LLMStreamEvent) -> None:
    callback = _LLM_STREAM_EVENT_CALLBACK.get()
    if callback is not None:
        callback(event)


class LLMClientProtocol(Protocol):
    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
        system: str | list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse: ...


# ---- Tool dispatch surface -----------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolUseRequest:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResultData:
    output: str
    is_error: bool = False


# ---- Events --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssistantMessage:
    content: list[ContentBlock]
    type: Literal["assistant_message"] = "assistant_message"


@dataclass(frozen=True, slots=True)
class ToolUse:
    id: str
    name: str
    input: dict[str, Any]
    type: Literal["tool_use"] = "tool_use"


@dataclass(frozen=True, slots=True)
class ToolResult:
    id: str
    output: str
    is_error: bool
    type: Literal["tool_result"] = "tool_result"


type TerminateReason = Literal["end_turn", "max_turns", "max_budget", "cancelled"]


@dataclass(frozen=True, slots=True)
class Terminated:
    reason: TerminateReason
    cost: CostSnapshot | None
    type: Literal["terminated"] = "terminated"


type Event = AssistantMessage | ToolUse | ToolResult | Terminated


_log = get_logger(__name__)


# ---- Config --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LoopConfig:
    max_turns: int
    max_budget_cny: float
    max_tokens: int | None = None
    model_context_window_tokens: int | None = None
    working_context_limit_tokens: int | None = None
    auto_compact_trigger_tokens: int | None = None
    compacted_target_tokens: int | None = None
    emergency_compact_tokens: int | None = None
    max_consecutive_identical_tool_calls: int | None = 3
    tool_timeout_seconds: float | None = 600.0


# ---- Main loop -----------------------------------------------------------


async def run_agent_loop(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    config: LoopConfig,
    llm: LLMClientProtocol,
    dispatch_tool: Callable[[ToolUseRequest], Awaitable[ToolResultData]],
    cost: CostTracker | None = None,
    store: SessionStore | None = None,
    agent_name: str = "AgentLoop",
    model: str | None = None,
    system: str | list[dict[str, Any]] | None = None,
    build_runtime_context: Callable[[], str] | None = None,
    build_recovery_state: Callable[[], dict[str, Any]] | None = None,
    context_token_estimator: Callable[[list[dict[str, Any]]], int] | None = None,
    compact_history_callback: Callable[
        [list[dict[str, Any]], int],
        Awaitable[list[dict[str, Any]]],
    ]
    | None = None,
    stream_event_callback: LLMStreamEventCallback | None = None,
) -> AsyncIterator[Event]:
    """Drive an LLM with tools until it stops or a limit fires.

    Cancellation semantics: when the consumer calls `.athrow(CancelledError)`,
    the loop yields exactly one `Terminated(reason="cancelled")` event and
    returns normally. `CancelledError` is NOT re-raised. This keeps the
    event stream symmetric — every run ends with a single `Terminated`
    event regardless of outcome, so consumers have one place to finalize
    (session log, cost report) instead of splitting between an `async for`
    body and an outer `except`. Do not "fix" this by re-raising.

    Cost semantics: `cost=None` disables both budget checks and usage
    recording; `Terminated.cost` is then `None`. This lets tests and
    sketch scripts drive the loop without constructing a `CostTracker`.

    When `build_runtime_context` is provided, its latest snapshot is appended
    after the complete tool-result batch so the next model turn does not need
    to reconstruct mutable application constraints from earlier messages.
    """
    history: list[dict[str, Any]] = list(messages)
    turns = 0
    input_token_high_watermark = 0
    last_context_input_tokens: int | None = None
    last_request_history_tokens: int | None = None
    previous_tool_signature: str | None = None
    consecutive_identical_tool_calls = 0
    prompt_sha256 = compute_prompt_sha256(
        system=system,
        tools=tools,
        tool_choice=None,
    )
    try:
        while True:
            await asyncio.sleep(0)

            if turns >= config.max_turns:
                yield Terminated(reason="max_turns", cost=_cost_snapshot(cost))
                return
            if cost is not None and cost.total_cost_cny >= config.max_budget_cny:
                yield Terminated(reason="max_budget", cost=cost.snapshot())
                return

            estimated_next_input_tokens = _estimated_next_input_tokens(
                history,
                context_token_estimator=context_token_estimator,
                last_context_input_tokens=last_context_input_tokens,
                last_request_history_tokens=last_request_history_tokens,
            )
            if (
                compact_history_callback is not None
                and config.auto_compact_trigger_tokens is not None
                and estimated_next_input_tokens is not None
                and estimated_next_input_tokens >= config.auto_compact_trigger_tokens
            ):
                before_tokens = estimated_next_input_tokens
                history = await compact_history_callback(history, before_tokens)
                after_tokens = (
                    context_token_estimator(history)
                    if context_token_estimator is not None
                    else None
                )
                if (
                    after_tokens is not None
                    and config.compacted_target_tokens is not None
                    and after_tokens > config.compacted_target_tokens
                ):
                    raise AgentError(
                        "context compaction exceeded target: "
                        f"estimated {after_tokens} tokens > "
                        f"{config.compacted_target_tokens}"
                    )
                _log.info(
                    "agent.context_compacted",
                    agent=agent_name,
                    model=model,
                    before_tokens=before_tokens,
                    after_tokens=after_tokens,
                )
                last_context_input_tokens = None
                last_request_history_tokens = None
                if cost is not None and cost.total_cost_cny >= config.max_budget_cny:
                    yield Terminated(reason="max_budget", cost=cost.snapshot())
                    return
                estimated_next_input_tokens = after_tokens

            if (
                config.emergency_compact_tokens is not None
                and estimated_next_input_tokens is not None
                and estimated_next_input_tokens >= config.emergency_compact_tokens
            ):
                raise AgentError(
                    "context reached the emergency limit without a valid compaction: "
                    f"estimated {estimated_next_input_tokens} tokens >= "
                    f"{config.emergency_compact_tokens}"
                )

            last_request_history_tokens = (
                context_token_estimator(history)
                if context_token_estimator is not None
                else None
            )

            with llm_stream_events(stream_event_callback):
                response = await llm.generate(
                    history,
                    tools,
                    system=system,
                    max_tokens=config.max_tokens,
                )
            if response.usage is not None:
                context_input_tokens = _context_input_tokens(response.usage)
                last_context_input_tokens = context_input_tokens
                input_token_high_watermark = max(
                    input_token_high_watermark,
                    context_input_tokens,
                )
                _log.debug(
                    "agent.context_window",
                    agent=agent_name,
                    model=model,
                    turn=turns + 1,
                    context_input_tokens=context_input_tokens,
                    input_token_high_watermark=input_token_high_watermark,
                    model_context_window_tokens=config.model_context_window_tokens,
                    working_context_limit_tokens=config.working_context_limit_tokens,
                    auto_compact_trigger_tokens=config.auto_compact_trigger_tokens,
                    compact_would_trigger=(
                        config.auto_compact_trigger_tokens is not None
                        and context_input_tokens >= config.auto_compact_trigger_tokens
                    ),
                    compaction_enabled=compact_history_callback is not None,
                )
            if cost is not None and response.usage is not None:
                cost.record(response.usage)

            if store is not None:
                if model is not None:
                    usage: UsageLike = response.usage if response.usage is not None else {}
                    store.append_llm_call(
                        agent=agent_name,
                        model=model,
                        usage=usage,
                        latency_ms=response.latency_ms,
                        stop_reason=response.stop_reason,
                        prompt_sha256=prompt_sha256,
                    )
                if response.reasoning_content:
                    store.append_reasoning(response.reasoning_content)
                for block in response.content:
                    if isinstance(block, TextBlock):
                        store.append_message(role="assistant", text=block.text)
                    elif isinstance(block, ToolUseBlock):
                        store.append_tool_use(block.id, block.name, block.input)
                if build_recovery_state is not None:
                    store.append_runtime_state(build_recovery_state())
            yield AssistantMessage(content=response.content)
            assistant_history: dict[str, Any] = {
                "role": "assistant",
                "content": _content_blocks_to_wire(response.content),
            }
            if response.reasoning_content:
                assistant_history["reasoning_content"] = response.reasoning_content
            history.append(assistant_history)
            turns += 1

            if response.stop_reason == "end_turn":
                yield Terminated(reason="end_turn", cost=_cost_snapshot(cost))
                return

            tool_use_blocks = [b for b in response.content if isinstance(b, ToolUseBlock)]
            if not tool_use_blocks:
                raise AgentError("tool_use stop with no tool blocks")

            tool_results: list[dict[str, Any]] = []
            for block in tool_use_blocks:
                tool_signature = _tool_call_signature(block)
                if tool_signature == previous_tool_signature:
                    consecutive_identical_tool_calls += 1
                else:
                    previous_tool_signature = tool_signature
                    consecutive_identical_tool_calls = 1
                repeat_limit = config.max_consecutive_identical_tool_calls
                loop_error = (
                    ToolLoopError(
                        f"tool loop blocked before dispatch: {block.name} repeated "
                        f"with identical input {consecutive_identical_tool_calls} times"
                    )
                    if repeat_limit is not None
                    and consecutive_identical_tool_calls >= repeat_limit
                    else None
                )
                yield ToolUse(id=block.id, name=block.name, input=block.input)
                recorder = current_recorder()
                trace = (
                    recorder.operation(
                        "tool_call",
                        block.id,
                        parent_entity_id=current_llm_call_id(),
                        attributes={
                            "tool_name": block.name,
                            "turn": turns,
                            "timeout_seconds": config.tool_timeout_seconds,
                        },
                        input_payload=block.input,
                    )
                    if recorder is not None
                    else nullcontext()
                )
                result: ToolResultData | None = None
                with trace as operation:
                    if loop_error is not None:
                        if operation is not None:
                            operation.set_result(
                                status="aborted",
                                output_payload={
                                    "output": str(loop_error),
                                    "is_error": True,
                                },
                                attributes={
                                    "guard": "repeated_tool_call",
                                    "repeat_count": consecutive_identical_tool_calls,
                                    "repeat_limit": repeat_limit,
                                },
                                error_type=loop_error.__class__.__name__,
                                error_message=str(loop_error),
                            )
                    else:
                        request = ToolUseRequest(
                            id=block.id,
                            name=block.name,
                            input=block.input,
                        )
                        try:
                            if config.tool_timeout_seconds is None:
                                result = await dispatch_tool(request)
                            else:
                                async with asyncio.timeout(config.tool_timeout_seconds):
                                    result = await dispatch_tool(request)
                        except TimeoutError as exc:
                            timeout_error = ToolTimeoutError(
                                f"tool {block.name} timed out after "
                                f"{config.tool_timeout_seconds:g} seconds"
                            )
                            _log.error(
                                "agent.tool_timeout",
                                agent=agent_name,
                                tool_name=block.name,
                                timeout_seconds=config.tool_timeout_seconds,
                            )
                            raise timeout_error from exc
                    if operation is not None and result is not None:
                        operation.set_result(
                            status="failed" if result.is_error else "completed",
                            output_payload={
                                "output": result.output,
                                "is_error": result.is_error,
                            },
                            attributes={
                                "output_length": len(result.output),
                                "is_error": result.is_error,
                            },
                        )
                if loop_error is not None:
                    _log.error(
                        "agent.repeated_tool_call_blocked",
                        agent=agent_name,
                        tool_name=block.name,
                        repeat_count=consecutive_identical_tool_calls,
                        repeat_limit=repeat_limit,
                    )
                    raise loop_error
                assert result is not None
                if store is not None:
                    store.append_tool_result(block.id, result.output, result.is_error)
                    if build_recovery_state is not None:
                        store.append_runtime_state(build_recovery_state())
                yield ToolResult(id=block.id, output=result.output, is_error=result.is_error)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result.output,
                        "is_error": result.is_error,
                    }
                )
            if build_runtime_context is not None:
                runtime_context = build_runtime_context()
                tool_results.append({"type": "text", "text": runtime_context})
                if store is not None:
                    store.append_message(role="user", text=runtime_context)
            history.append({"role": "user", "content": tool_results})
    except asyncio.CancelledError:
        yield Terminated(reason="cancelled", cost=_cost_snapshot(cost))


def _cost_snapshot(cost: CostTracker | None) -> CostSnapshot | None:
    return cost.snapshot() if cost is not None else None


def _context_input_tokens(usage: UsageLike) -> int:
    return sum(
        read_usage_field(usage, field)
        for field in (
            "input_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        )
    )


def _estimated_next_input_tokens(
    history: list[dict[str, Any]],
    *,
    context_token_estimator: Callable[[list[dict[str, Any]]], int] | None,
    last_context_input_tokens: int | None,
    last_request_history_tokens: int | None,
) -> int | None:
    if context_token_estimator is None:
        return None
    current_history_tokens = context_token_estimator(history)
    if last_context_input_tokens is None or last_request_history_tokens is None:
        return current_history_tokens
    appended_tokens = max(current_history_tokens - last_request_history_tokens, 0)
    return last_context_input_tokens + appended_tokens


def _content_blocks_to_wire(blocks: list[ContentBlock]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for block in blocks:
        if isinstance(block, TextBlock):
            out.append({"type": "text", "text": block.text})
        elif isinstance(block, ToolUseBlock):
            out.append(
                {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }
            )
    return out


def _tool_call_signature(block: ToolUseBlock) -> str:
    return json.dumps(
        {"input": block.input, "name": block.name},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
