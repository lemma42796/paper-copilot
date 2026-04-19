from __future__ import annotations

import asyncio

from paper_copilot.agents.loop import (
    Event,
    LoopConfig,
    Terminated,
    ToolResult,
    ToolResultData,
    ToolUse,
    ToolUseBlock,
    ToolUseRequest,
    run_agent_loop,
)
from paper_copilot.agents.mock_llm import MockLLM, MockResponse, TextBlock
from paper_copilot.shared.cost import CostSnapshot, CostTracker


def test_end_turn_terminates_with_cost_snapshot() -> None:
    llm = MockLLM(
        [
            MockResponse(
                content=[TextBlock(text="done")],
                stop_reason="end_turn",
                usage={"input_tokens": 30, "output_tokens": 10},
            ),
        ]
    )
    cost = CostTracker()
    cfg = LoopConfig(max_turns=5, max_budget_cny=10.0)

    async def dispatch_tool(req: ToolUseRequest) -> ToolResultData:
        raise AssertionError("dispatch_tool must not be called on end_turn path")

    async def run() -> list[Event]:
        collected: list[Event] = []
        async for event in run_agent_loop(
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            config=cfg,
            llm=llm,
            dispatch_tool=dispatch_tool,
            cost=cost,
        ):
            collected.append(event)
        return collected

    events = asyncio.run(run())

    assert [type(e).__name__ for e in events] == ["AssistantMessage", "Terminated"]
    term = events[-1]
    assert isinstance(term, Terminated)
    assert term.reason == "end_turn"
    assert isinstance(term.cost, CostSnapshot)
    assert term.cost.input_tokens == 30
    assert term.cost.output_tokens == 10


def test_max_turns_terminates() -> None:
    def tool_use_response(idx: int) -> MockResponse:
        return MockResponse(
            content=[
                TextBlock(text=f"turn {idx}"),
                ToolUseBlock(id=f"t{idx}", name="search", input={"i": idx}),
            ],
            stop_reason="tool_use",
            usage={"input_tokens": 10, "output_tokens": 2},
        )

    llm = MockLLM([tool_use_response(1), tool_use_response(2), tool_use_response(3)])
    cfg = LoopConfig(max_turns=2, max_budget_cny=10.0)

    async def dispatch_tool(req: ToolUseRequest) -> ToolResultData:
        return ToolResultData(output=f"ok-{req.id}")

    async def run() -> list[Event]:
        collected: list[Event] = []
        async for event in run_agent_loop(
            messages=[{"role": "user", "content": "go"}],
            tools=[],
            config=cfg,
            llm=llm,
            dispatch_tool=dispatch_tool,
            cost=None,
        ):
            collected.append(event)
        return collected

    events = asyncio.run(run())

    assert [type(e).__name__ for e in events] == [
        "AssistantMessage",
        "ToolUse",
        "ToolResult",
        "AssistantMessage",
        "ToolUse",
        "ToolResult",
        "Terminated",
    ]
    term = events[-1]
    assert isinstance(term, Terminated)
    assert term.reason == "max_turns"
    assert term.cost is None


def test_max_budget_terminates_at_exact_threshold() -> None:
    boundary_usage = {"input_tokens": 100_000, "output_tokens": 0}
    probe = CostTracker()
    probe.record(boundary_usage)
    budget_at_exactly_one_turn = probe.total_cost_cny

    llm = MockLLM(
        [
            MockResponse(
                content=[
                    TextBlock(text="searching"),
                    ToolUseBlock(id="t1", name="search", input={"q": "x"}),
                ],
                stop_reason="tool_use",
                usage=boundary_usage,
            ),
            MockResponse(
                content=[TextBlock(text="should not be consumed")],
                stop_reason="end_turn",
            ),
        ]
    )
    cost = CostTracker()
    cfg = LoopConfig(max_turns=10, max_budget_cny=budget_at_exactly_one_turn)

    async def dispatch_tool(req: ToolUseRequest) -> ToolResultData:
        return ToolResultData(output="ok")

    async def run() -> list[Event]:
        collected: list[Event] = []
        async for event in run_agent_loop(
            messages=[{"role": "user", "content": "go"}],
            tools=[],
            config=cfg,
            llm=llm,
            dispatch_tool=dispatch_tool,
            cost=cost,
        ):
            collected.append(event)
        return collected

    events = asyncio.run(run())

    assert [type(e).__name__ for e in events] == [
        "AssistantMessage",
        "ToolUse",
        "ToolResult",
        "Terminated",
    ]
    term = events[-1]
    assert isinstance(term, Terminated)
    assert term.reason == "max_budget"
    assert term.cost is not None
    assert term.cost.cost_cny == budget_at_exactly_one_turn


def test_cancel_midflight_yields_terminated() -> None:
    llm = MockLLM(
        [
            MockResponse(
                content=[
                    TextBlock(text="searching"),
                    ToolUseBlock(id="t1", name="search", input={"q": "x"}),
                ],
                stop_reason="tool_use",
                usage={"input_tokens": 10, "output_tokens": 2},
            ),
            MockResponse(
                content=[TextBlock(text="should not be consumed")],
                stop_reason="end_turn",
            ),
        ]
    )
    cfg = LoopConfig(max_turns=10, max_budget_cny=10.0)

    async def dispatch_tool(req: ToolUseRequest) -> ToolResultData:
        return ToolResultData(output="ok")

    async def run() -> list[Event]:
        gen = run_agent_loop(
            messages=[{"role": "user", "content": "go"}],
            tools=[],
            config=cfg,
            llm=llm,
            dispatch_tool=dispatch_tool,
            cost=None,
        )
        collected: list[Event] = []
        collected.append(await gen.__anext__())
        collected.append(await gen.__anext__())
        collected.append(await gen.athrow(asyncio.CancelledError))
        return collected

    events = asyncio.run(run())

    assert [type(e).__name__ for e in events] == [
        "AssistantMessage",
        "ToolUse",
        "Terminated",
    ]
    first_tool_use = events[1]
    assert isinstance(first_tool_use, ToolUse)
    assert first_tool_use.id == "t1"
    term = events[-1]
    assert isinstance(term, Terminated)
    assert term.reason == "cancelled"


def test_tool_use_round_trip_preserves_ids_and_error_flag() -> None:
    llm = MockLLM(
        [
            MockResponse(
                content=[
                    TextBlock(text="two calls"),
                    ToolUseBlock(id="t-ok", name="search", input={"q": "a"}),
                    ToolUseBlock(id="t-err", name="search", input={"q": "b"}),
                ],
                stop_reason="tool_use",
                usage={"input_tokens": 20, "output_tokens": 5},
            ),
            MockResponse(
                content=[TextBlock(text="done")],
                stop_reason="end_turn",
                usage={"input_tokens": 40, "output_tokens": 3},
            ),
        ]
    )
    cfg = LoopConfig(max_turns=5, max_budget_cny=10.0)

    async def dispatch_tool(req: ToolUseRequest) -> ToolResultData:
        if req.id == "t-err":
            return ToolResultData(output="boom", is_error=True)
        return ToolResultData(output=f"hit-{req.input['q']}")

    async def run() -> list[Event]:
        collected: list[Event] = []
        async for event in run_agent_loop(
            messages=[{"role": "user", "content": "go"}],
            tools=[],
            config=cfg,
            llm=llm,
            dispatch_tool=dispatch_tool,
            cost=None,
        ):
            collected.append(event)
        return collected

    events = asyncio.run(run())

    assert [type(e).__name__ for e in events] == [
        "AssistantMessage",
        "ToolUse",
        "ToolResult",
        "ToolUse",
        "ToolResult",
        "AssistantMessage",
        "Terminated",
    ]

    tool_use_ok = events[1]
    tool_result_ok = events[2]
    tool_use_err = events[3]
    tool_result_err = events[4]
    assert isinstance(tool_use_ok, ToolUse) and tool_use_ok.id == "t-ok"
    assert isinstance(tool_result_ok, ToolResult)
    assert tool_result_ok.id == "t-ok"
    assert tool_result_ok.is_error is False
    assert tool_result_ok.output == "hit-a"
    assert isinstance(tool_use_err, ToolUse) and tool_use_err.id == "t-err"
    assert isinstance(tool_result_err, ToolResult)
    assert tool_result_err.id == "t-err"
    assert tool_result_err.is_error is True
    assert tool_result_err.output == "boom"

    term = events[-1]
    assert isinstance(term, Terminated)
    assert term.reason == "end_turn"
