"""Agent loop: async generator driven by an injected LLM client.

See `run_agent_loop` for termination and cost semantics.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from paper_copilot.session import SessionStore
from paper_copilot.shared.cost import CostSnapshot, CostTracker, UsageLike
from paper_copilot.shared.errors import AgentError

__all__ = [
    "AssistantMessage",
    "ContentBlock",
    "Event",
    "LLMClientProtocol",
    "LLMResponse",
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


class LLMClientProtocol(Protocol):
    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
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


# ---- Config --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LoopConfig:
    max_turns: int
    max_budget_cny: float


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
    """
    history: list[dict[str, Any]] = list(messages)
    turns = 0
    try:
        while True:
            await asyncio.sleep(0)

            if turns >= config.max_turns:
                yield Terminated(reason="max_turns", cost=_cost_snapshot(cost))
                return
            if cost is not None and cost.total_cost_cny >= config.max_budget_cny:
                yield Terminated(reason="max_budget", cost=cost.snapshot())
                return

            response = await llm.generate(history, tools)
            if cost is not None and response.usage is not None:
                cost.record(response.usage)

            if store is not None:
                for block in response.content:
                    if isinstance(block, TextBlock):
                        store.append_message(role="assistant", text=block.text)
                    elif isinstance(block, ToolUseBlock):
                        store.append_tool_use(block.id, block.name, block.input)
            yield AssistantMessage(content=response.content)
            history.append({"role": "assistant", "content": response.content})
            turns += 1

            if response.stop_reason == "end_turn":
                yield Terminated(reason="end_turn", cost=_cost_snapshot(cost))
                return

            tool_use_blocks = [b for b in response.content if isinstance(b, ToolUseBlock)]
            if not tool_use_blocks:
                raise AgentError("tool_use stop with no tool blocks")

            tool_results: list[dict[str, Any]] = []
            for block in tool_use_blocks:
                yield ToolUse(id=block.id, name=block.name, input=block.input)
                result = await dispatch_tool(
                    ToolUseRequest(id=block.id, name=block.name, input=block.input)
                )
                if store is not None:
                    store.append_tool_result(block.id, result.output, result.is_error)
                yield ToolResult(id=block.id, output=result.output, is_error=result.is_error)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result.output,
                        "is_error": result.is_error,
                    }
                )
            history.append({"role": "user", "content": tool_results})
    except asyncio.CancelledError:
        yield Terminated(reason="cancelled", cost=_cost_snapshot(cost))


def _cost_snapshot(cost: CostTracker | None) -> CostSnapshot | None:
    return cost.snapshot() if cost is not None else None
