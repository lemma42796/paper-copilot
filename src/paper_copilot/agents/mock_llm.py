"""In-memory scripted LLM client for loop tests and sketches.

Returns a preset list of `LLMResponse` objects in order; exhaustion is a
programming error (not a silent end-of-stream) so tests surface
mis-scripted runs immediately.
"""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from paper_copilot.agents.loop import LLMResponse, TextBlock, ToolUseBlock
from paper_copilot.shared.errors import AgentError

# Alias: reads clearer in tests ("MockResponse" marks it as test data),
# but carries no extra behavior — a mock response is just an LLMResponse.
MockResponse = LLMResponse

__all__ = ["MockLLM", "MockLLMCall", "MockResponse", "TextBlock", "ToolUseBlock"]


@dataclass(frozen=True, slots=True)
class MockLLMCall:
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    tool_choice: dict[str, Any] | None
    system: str | list[dict[str, Any]] | None
    max_tokens: int | None


class MockLLM:
    def __init__(self, responses: Iterable[LLMResponse]) -> None:
        self._responses: list[LLMResponse] = list(responses)
        self._cursor = 0
        self.calls: list[MockLLMCall] = []

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
        system: str | list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.calls.append(
            MockLLMCall(
                messages=deepcopy(messages),
                tools=deepcopy(tools),
                tool_choice=deepcopy(tool_choice),
                system=deepcopy(system),
                max_tokens=max_tokens,
            )
        )
        if self._cursor >= len(self._responses):
            raise AgentError("mock script exhausted")
        response = self._responses[self._cursor]
        self._cursor += 1
        return response
