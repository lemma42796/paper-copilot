"""Single convergence point for OpenAI-compatible LLM calls."""

from __future__ import annotations

import json
import os
import time
from contextlib import nullcontext
from typing import Any, Final
from urllib.parse import urlparse

import httpx

from paper_copilot.agents.loop import (
    ContentBlock,
    LLMResponse,
    StopReason,
    TextBlock,
    ToolUseBlock,
)
from paper_copilot.observability import current_recorder, set_last_llm_call_id
from paper_copilot.shared.env import load_env
from paper_copilot.shared.errors import AgentError

__all__ = [
    "AUTO_COMPACT_TRIGGER_TOKENS",
    "COMPACTED_TARGET_TOKENS",
    "COMPACTION_MAX_OUTPUT_TOKENS",
    "DEFAULT_MODEL",
    "EMERGENCY_COMPACT_TOKENS",
    "MODEL_CONTEXT_WINDOW_TOKENS",
    "RECENT_HISTORY_BUDGET_TOKENS",
    "WORKING_CONTEXT_LIMIT_TOKENS",
    "LLMClient",
]

load_env()

DEFAULT_MODEL: Final[str] = os.environ.get("LLM_MODEL") or "qwen3.6-flash"
MODEL_CONTEXT_WINDOW_TOKENS: Final[int] = 1_000_000
WORKING_CONTEXT_LIMIT_TOKENS: Final[int] = 256_000
AUTO_COMPACT_TRIGGER_TOKENS: Final[int] = 200_000
COMPACTED_TARGET_TOKENS: Final[int] = 80_000
RECENT_HISTORY_BUDGET_TOKENS: Final[int] = 40_000
COMPACTION_MAX_OUTPUT_TOKENS: Final[int] = 8_000
EMERGENCY_COMPACT_TOKENS: Final[int] = 240_000
_DEFAULT_MAX_TOKENS: Final[int] = 1500
_DEFAULT_TIMEOUT_S: Final[float] = 60.0
_DEFAULT_BASE_URL: Final[str] = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class LLMClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self._base_url = (base_url or os.environ.get("LLM_BASE_URL") or _DEFAULT_BASE_URL).rstrip(
            "/"
        )
        self._endpoint = _chat_completions_endpoint(self._base_url)
        self._is_dashscope = "dashscope.aliyuncs.com" in (urlparse(self._base_url).hostname or "")
        self._api_key = api_key or os.environ.get("LLM_API_KEY")
        if not self._api_key and self._is_dashscope:
            self._api_key = os.environ.get("DASHSCOPE_API_KEY")
        if not self._api_key:
            raise AgentError(
                "environment variable LLM_API_KEY is not set — see README for configuration"
            )
        self._client = httpx.AsyncClient(timeout=timeout)

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
        system: str | list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": DEFAULT_MODEL,
            "max_tokens": max_tokens if max_tokens is not None else _DEFAULT_MAX_TOKENS,
            "messages": _convert_messages(
                messages,
                system=system,
                preserve_cache_control=self._is_dashscope,
            ),
            "stream": False,
        }
        if tools:
            payload["tools"] = _convert_tools(
                tools,
                preserve_cache_control=self._is_dashscope,
            )
        if tool_choice is not None:
            payload["tool_choice"] = _convert_tool_choice(tool_choice)
        if self._is_dashscope:
            payload["enable_thinking"] = False
        elif DEFAULT_MODEL.startswith("deepseek-"):
            payload["thinking"] = {"type": "disabled"}

        recorder = current_recorder()
        llm_call_id = recorder.new_entity_id("llm") if recorder is not None else ""
        trace = (
            recorder.operation(
                "llm_call",
                llm_call_id,
                attributes={"model": DEFAULT_MODEL, "endpoint": self._endpoint},
                input_payload=payload,
            )
            if recorder is not None
            else nullcontext()
        )
        with trace as operation:
            t0 = time.perf_counter()
            try:
                response = await self._client.post(
                    self._endpoint,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            except httpx.TimeoutException as exc:
                raise AgentError(f"LLM request timed out: {exc}") from exc
            except httpx.RequestError as exc:
                raise AgentError(f"cannot reach LLM endpoint: {exc}") from exc
            latency_ms = int((time.perf_counter() - t0) * 1000)
            if operation is not None:
                operation.set_result(
                    status="failed" if response.is_error else "completed",
                    output_payload={
                        "http_status": response.status_code,
                        "body": response.text,
                    },
                    attributes={
                        "http_status": response.status_code,
                        "latency_ms": latency_ms,
                    },
                )

            if response.status_code == 401:
                raise AgentError("authentication failed — check LLM_API_KEY")
            if response.status_code == 429:
                raise AgentError(f"upstream rate limited: {_compact_response(response)}")
            if response.is_error:
                raise AgentError(
                    f"upstream {response.status_code}: {_compact_response(response)}"
                )

            try:
                body = response.json()
            except json.JSONDecodeError as exc:
                raise AgentError("LLM endpoint returned invalid JSON") from exc
            if not isinstance(body, dict):
                raise AgentError("LLM endpoint returned a non-object response")
            converted = _convert_response(body, latency_ms=latency_ms)
            if operation is not None:
                operation.set_result(
                    output_payload=body,
                    attributes={
                        "http_status": response.status_code,
                        "latency_ms": latency_ms,
                        "stop_reason": converted.stop_reason,
                    },
                )
                set_last_llm_call_id(llm_call_id)
            return converted


def _chat_completions_endpoint(base_url: str) -> str:
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def _convert_messages(
    messages: list[dict[str, Any]],
    *,
    system: str | list[dict[str, Any]] | None,
    preserve_cache_control: bool,
) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    if system is not None:
        converted.append(
            {
                "role": "system",
                "content": _convert_text_content(
                    system,
                    preserve_cache_control=preserve_cache_control,
                ),
            }
        )
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role == "assistant":
            converted.append(_convert_assistant_message(content))
        elif role == "user":
            converted.extend(
                _convert_user_message(
                    content,
                    preserve_cache_control=preserve_cache_control,
                )
            )
        elif role in {"system", "tool"}:
            converted.append(
                {
                    **message,
                    "content": _convert_text_content(
                        content,
                        preserve_cache_control=preserve_cache_control,
                    ),
                }
            )
        else:
            raise AgentError(f"unsupported message role: {role!r}")
    return converted


def _convert_user_message(
    content: Any,
    *,
    preserve_cache_control: bool,
) -> list[dict[str, Any]]:
    if not isinstance(content, list):
        return [{"role": "user", "content": str(content)}]

    converted: list[dict[str, Any]] = []
    text_blocks: list[dict[str, Any]] = []

    def flush_text() -> None:
        if text_blocks:
            text_content: str | list[dict[str, Any]]
            if preserve_cache_control:
                text_content = [*text_blocks]
            else:
                text_content = "\n".join(str(block.get("text", "")) for block in text_blocks)
            converted.append({"role": "user", "content": text_content})
            text_blocks.clear()

    for block in content:
        if not isinstance(block, dict):
            raise AgentError("message content block must be an object")
        if block.get("type") == "tool_result":
            flush_text()
            converted.append(
                {
                    "role": "tool",
                    "tool_call_id": str(block.get("tool_use_id", "")),
                    "content": _tool_result_text(block.get("content")),
                }
            )
            continue
        text_blocks.append(
            _strip_cache_control(block) if not preserve_cache_control else dict(block)
        )
    flush_text()
    return converted


def _convert_assistant_message(content: Any) -> dict[str, Any]:
    if not isinstance(content, list):
        return {"role": "assistant", "content": str(content)}

    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            raise AgentError("assistant content block must be an object")
        match block.get("type"):
            case "text":
                text_parts.append(str(block.get("text", "")))
            case "tool_use":
                tool_calls.append(
                    {
                        "id": str(block.get("id", "")),
                        "type": "function",
                        "function": {
                            "name": str(block.get("name", "")),
                            "arguments": json.dumps(
                                block.get("input", {}),
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        },
                    }
                )
            case other:
                raise AgentError(f"unsupported assistant content block type: {other!r}")
    message: dict[str, Any] = {
        "role": "assistant",
        "content": "\n".join(part for part in text_parts if part) or None,
    }
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message


def _convert_text_content(content: Any, *, preserve_cache_control: bool) -> Any:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    converted: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            raise AgentError("text content block must be an object")
        converted.append(
            dict(block) if preserve_cache_control else _strip_cache_control(block)
        )
    if preserve_cache_control:
        return converted
    return "\n".join(str(block.get("text", "")) for block in converted)


def _convert_tools(
    tools: list[dict[str, Any]],
    *,
    preserve_cache_control: bool,
) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for tool in tools:
        name = tool.get("name")
        parameters = tool.get("input_schema")
        if not isinstance(name, str) or not isinstance(parameters, dict):
            raise AgentError("tool must contain string name and object input_schema")
        converted_tool: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": name,
                "description": str(tool.get("description", "")),
                "parameters": parameters,
            },
        }
        if preserve_cache_control and "cache_control" in tool:
            converted_tool["cache_control"] = tool["cache_control"]
        converted.append(converted_tool)
    return converted


def _convert_tool_choice(tool_choice: dict[str, Any]) -> str | dict[str, Any]:
    choice_type = tool_choice.get("type")
    if choice_type == "tool":
        name = tool_choice.get("name")
        if not isinstance(name, str):
            raise AgentError("forced tool_choice must contain a string name")
        return {"type": "function", "function": {"name": name}}
    if choice_type in {"auto", "none", "required"}:
        return str(choice_type)
    raise AgentError(f"unsupported tool_choice type: {choice_type!r}")


def _strip_cache_control(block: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in block.items() if key != "cache_control"}


def _tool_result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text", "")) if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


def _convert_response(body: dict[str, Any], *, latency_ms: int) -> LLMResponse:
    error = body.get("error")
    if isinstance(error, dict):
        raise AgentError(str(error.get("message") or "LLM endpoint returned an error"))
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise AgentError("LLM response did not contain a completion choice")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        raise AgentError("LLM completion choice did not contain a message")

    content: list[ContentBlock] = []
    text = message.get("content")
    if isinstance(text, str) and text:
        content.append(TextBlock(text=text))
    elif isinstance(text, list):
        for block in text:
            if isinstance(block, dict) and block.get("type") == "text":
                content.append(TextBlock(text=str(block.get("text", ""))))

    tool_calls = message.get("tool_calls")
    if tool_calls is not None:
        if not isinstance(tool_calls, list):
            raise AgentError("LLM response tool_calls must be a list")
        content.extend(_convert_tool_call(tool_call) for tool_call in tool_calls)

    finish_reason = choice.get("finish_reason")
    if tool_calls:
        stop_reason: StopReason = "tool_use"
    elif finish_reason == "stop":
        stop_reason = "end_turn"
    else:
        raise AgentError(
            f"LLM returned unsupported finish_reason={finish_reason!r} "
            f"(max_tokens cap? refusal? content filter?)"
        )
    return LLMResponse(
        content=content,
        stop_reason=stop_reason,
        usage=_convert_usage(body.get("usage")),
        latency_ms=latency_ms,
    )


def _convert_tool_call(tool_call: Any) -> ToolUseBlock:
    if not isinstance(tool_call, dict):
        raise AgentError("LLM response tool call must be an object")
    function = tool_call.get("function")
    if not isinstance(function, dict):
        raise AgentError("LLM response tool call did not contain a function")
    raw_arguments = function.get("arguments")
    if isinstance(raw_arguments, str):
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise AgentError("LLM tool call arguments were not valid JSON") from exc
    else:
        arguments = raw_arguments
    if not isinstance(arguments, dict):
        raise AgentError(
            f"tool call arguments are not an object: got {type(arguments).__name__}"
        )
    return ToolUseBlock(
        id=str(tool_call.get("id", "")),
        name=str(function.get("name", "")),
        input=arguments,
    )


def _convert_usage(usage: Any) -> dict[str, int] | None:
    if not isinstance(usage, dict):
        return None
    prompt_tokens = _usage_int(usage, "prompt_tokens")
    completion_tokens = _usage_int(usage, "completion_tokens")
    cache_read = _usage_int(usage, "prompt_cache_hit_tokens")
    cache_miss = usage.get("prompt_cache_miss_tokens")
    cache_creation = 0

    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict):
        cache_read = _usage_int(details, "cached_tokens")
        cache_creation = _usage_int(details, "cache_creation_input_tokens")
        creation = details.get("cache_creation")
        if isinstance(creation, dict):
            cache_creation = max(
                cache_creation,
                _usage_int(creation, "cache_creation_input_tokens"),
            )
    if isinstance(cache_miss, int) and not isinstance(cache_miss, bool):
        input_tokens = max(cache_miss, 0)
    else:
        input_tokens = max(prompt_tokens - cache_read - cache_creation, 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": completion_tokens,
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": cache_read,
    }


def _usage_int(usage: dict[str, Any], name: str) -> int:
    value = usage.get(name, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _compact_response(response: httpx.Response, *, limit: int = 300) -> str:
    text = " ".join(response.text.split())
    return text if len(text) <= limit else f"{text[:limit]}..."
