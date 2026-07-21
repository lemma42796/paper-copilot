from __future__ import annotations

import asyncio
from typing import Any

import pytest

from paper_copilot.agents.loop import (
    Event,
    LoopConfig,
    ToolResultData,
    ToolUseRequest,
    run_agent_loop,
)
from paper_copilot.agents.mock_llm import MockLLM, MockResponse, TextBlock, ToolUseBlock
from paper_copilot.shared.errors import AgentError


async def _unused_dispatch(req: ToolUseRequest) -> ToolResultData:
    raise AssertionError(f"unexpected tool call: {req.name}")


def test_loop_does_not_compact_below_trigger() -> None:
    llm = MockLLM(
        [MockResponse(content=[TextBlock(text="done")], stop_reason="end_turn")]
    )
    compact_calls: list[int] = []

    async def compact(
        history: list[dict[str, Any]], estimated_tokens: int
    ) -> list[dict[str, Any]]:
        compact_calls.append(estimated_tokens)
        return history

    async def run() -> list[Event]:
        events: list[Event] = []
        async for event in run_agent_loop(
            messages=[{"role": "user", "content": "original"}],
            tools=[],
            config=LoopConfig(
                max_turns=2,
                max_budget_cny=10.0,
                auto_compact_trigger_tokens=200_000,
                compacted_target_tokens=80_000,
                emergency_compact_tokens=240_000,
            ),
            llm=llm,
            dispatch_tool=_unused_dispatch,
            context_token_estimator=lambda history: 199_999,
            compact_history_callback=compact,
        ):
            events.append(event)
        return events

    asyncio.run(run())
    assert compact_calls == []
    assert len(llm.calls) == 1


def test_loop_compacts_at_trigger_before_model_call() -> None:
    llm = MockLLM(
        [MockResponse(content=[TextBlock(text="done")], stop_reason="end_turn")]
    )
    compact_calls: list[int] = []

    def estimate(history: list[dict[str, Any]]) -> int:
        return 10 if history[0].get("content") == "compacted" else 200_000

    async def compact(
        history: list[dict[str, Any]], estimated_tokens: int
    ) -> list[dict[str, Any]]:
        compact_calls.append(estimated_tokens)
        return [{"role": "user", "content": "compacted"}]

    async def run() -> None:
        async for _ in run_agent_loop(
            messages=[{"role": "user", "content": "original"}],
            tools=[],
            config=LoopConfig(
                max_turns=2,
                max_budget_cny=10.0,
                auto_compact_trigger_tokens=200_000,
                compacted_target_tokens=80_000,
                emergency_compact_tokens=240_000,
            ),
            llm=llm,
            dispatch_tool=_unused_dispatch,
            context_token_estimator=estimate,
            compact_history_callback=compact,
        ):
            pass

    asyncio.run(run())
    assert compact_calls == [200_000]
    assert llm.calls[0].messages == [{"role": "user", "content": "compacted"}]


def test_loop_rejects_compaction_above_target() -> None:
    llm = MockLLM([])

    def estimate(history: list[dict[str, Any]]) -> int:
        return 81_000 if history[0].get("content") == "too-large" else 200_000

    async def compact(
        history: list[dict[str, Any]], estimated_tokens: int
    ) -> list[dict[str, Any]]:
        return [{"role": "user", "content": "too-large"}]

    async def run() -> None:
        async for _ in run_agent_loop(
            messages=[{"role": "user", "content": "original"}],
            tools=[],
            config=LoopConfig(
                max_turns=2,
                max_budget_cny=10.0,
                auto_compact_trigger_tokens=200_000,
                compacted_target_tokens=80_000,
                emergency_compact_tokens=240_000,
            ),
            llm=llm,
            dispatch_tool=_unused_dispatch,
            context_token_estimator=estimate,
            compact_history_callback=compact,
        ):
            pass

    with pytest.raises(AgentError, match="exceeded target"):
        asyncio.run(run())
    assert not llm.calls


def test_loop_blocks_emergency_context_without_compaction() -> None:
    llm = MockLLM([])

    async def run() -> None:
        async for _ in run_agent_loop(
            messages=[{"role": "user", "content": "original"}],
            tools=[],
            config=LoopConfig(
                max_turns=2,
                max_budget_cny=10.0,
                emergency_compact_tokens=240_000,
            ),
            llm=llm,
            dispatch_tool=_unused_dispatch,
            context_token_estimator=lambda history: 240_000,
        ):
            pass

    with pytest.raises(AgentError, match="emergency limit"):
        asyncio.run(run())
    assert not llm.calls


def test_loop_uses_actual_usage_plus_appended_history_for_trigger() -> None:
    llm = MockLLM(
        [
            MockResponse(
                content=[ToolUseBlock(id="t1", name="search", input={})],
                stop_reason="tool_use",
                usage={"input_tokens": 199_995, "output_tokens": 1},
            ),
            MockResponse(content=[TextBlock(text="done")], stop_reason="end_turn"),
        ]
    )
    compact_calls: list[int] = []

    def estimate(history: list[dict[str, Any]]) -> int:
        if history[0].get("content") == "compacted":
            return 5
        return 10 if len(history) == 1 else 20

    async def compact(
        history: list[dict[str, Any]], estimated_tokens: int
    ) -> list[dict[str, Any]]:
        compact_calls.append(estimated_tokens)
        return [{"role": "user", "content": "compacted"}]

    async def dispatch(req: ToolUseRequest) -> ToolResultData:
        return ToolResultData(output="ok")

    async def run() -> None:
        async for _ in run_agent_loop(
            messages=[{"role": "user", "content": "original"}],
            tools=[],
            config=LoopConfig(
                max_turns=3,
                max_budget_cny=10.0,
                auto_compact_trigger_tokens=200_000,
                compacted_target_tokens=80_000,
                emergency_compact_tokens=240_000,
            ),
            llm=llm,
            dispatch_tool=dispatch,
            context_token_estimator=estimate,
            compact_history_callback=compact,
        ):
            pass

    asyncio.run(run())
    assert compact_calls == [200_005]
    assert llm.calls[1].messages == [{"role": "user", "content": "compacted"}]
