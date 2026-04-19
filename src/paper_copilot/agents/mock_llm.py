"""In-memory scripted LLM client for loop tests and sketches.

Returns a preset list of `LLMResponse` objects in order; exhaustion is a
programming error (not a silent end-of-stream) so tests surface
mis-scripted runs immediately.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from paper_copilot.agents.loop import LLMResponse, TextBlock, ToolUseBlock
from paper_copilot.shared.errors import AgentError

# Alias: reads clearer in tests ("MockResponse" marks it as test data),
# but carries no extra behavior — a mock response is just an LLMResponse.
MockResponse = LLMResponse

__all__ = ["MockLLM", "MockResponse", "TextBlock", "ToolUseBlock"]


class MockLLM:
    def __init__(self, responses: Iterable[LLMResponse]) -> None:
        self._responses: list[LLMResponse] = list(responses)
        self._cursor = 0

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        if self._cursor >= len(self._responses):
            raise AgentError("mock script exhausted")
        response = self._responses[self._cursor]
        self._cursor += 1
        return response
