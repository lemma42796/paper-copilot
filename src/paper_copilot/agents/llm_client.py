"""Single convergence point for all LLM calls (Dashscope Anthropic-compat endpoint).

All agents in this project route LLM calls through `LLMClient.generate`. The
model id is pinned here as a `Final[str]`; any other module hard-coding
'qwen3.6-flash' is a boundary violation (see ARCHITECTURE.md "Cost discipline").

This module owns the translation between the anthropic SDK's response shape
and the internal `LLMResponse` dataclass defined in `agents.loop`. It does
NOT touch `CostTracker` — the caller records `response.usage` itself.
"""

from __future__ import annotations

import os
from typing import Any, Final

import anthropic

from paper_copilot.agents.loop import ContentBlock, LLMResponse, TextBlock, ToolUseBlock
from paper_copilot.shared.errors import AgentError

__all__ = ["DEFAULT_MODEL", "LLMClient"]

DEFAULT_MODEL: Final[str] = "qwen3.6-flash"
_DEFAULT_MAX_TOKENS: Final[int] = 1500
_DEFAULT_TIMEOUT_S: Final[float] = 60.0


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise AgentError(
            f"environment variable {name} is not set — see README for configuration"
        )
    return value


class LLMClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(
            base_url=base_url or _require_env("ANTHROPIC_BASE_URL"),
            api_key=api_key or _require_env("ANTHROPIC_API_KEY"),
            timeout=timeout,
        )

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": DEFAULT_MODEL,
            "max_tokens": _DEFAULT_MAX_TOKENS,
            "thinking": {"type": "disabled"},
            "messages": messages,
        }
        if system is not None:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice

        try:
            resp = await self._client.messages.create(**kwargs)
        except anthropic.APIConnectionError as e:
            raise AgentError(f"cannot reach LLM endpoint: {e}") from e
        except anthropic.AuthenticationError as e:
            raise AgentError(f"authentication failed — check ANTHROPIC_API_KEY: {e}") from e
        except anthropic.RateLimitError as e:
            raise AgentError(f"upstream rate limited: {e}") from e
        except anthropic.APIStatusError as e:
            raise AgentError(f"upstream {e.status_code}: {e.message}") from e

        stop_reason = resp.stop_reason
        if stop_reason not in ("end_turn", "tool_use"):
            raise AgentError(
                f"LLM returned unsupported stop_reason={stop_reason!r} "
                f"(max_tokens cap? refusal? pause?); "
                f"content had {len(resp.content)} block(s)"
            )
        content: list[ContentBlock] = [_convert_block(b) for b in resp.content]
        return LLMResponse(content=content, stop_reason=stop_reason, usage=resp.usage)


def _convert_block(block: Any) -> ContentBlock:
    block_type = block.type
    if block_type == "text":
        return TextBlock(text=block.text)
    if block_type == "tool_use":
        tool_input = block.input
        if not isinstance(tool_input, dict):
            raise AgentError(
                f"tool_use input is not a dict: got {type(tool_input).__name__}"
            )
        return ToolUseBlock(id=block.id, name=block.name, input=tool_input)
    raise AgentError(f"unexpected content block type: {block_type!r}")
