from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from paper_copilot.agents.llm_client import LLMClient
from paper_copilot.agents.loop import LLMResponse, TextBlock, ToolUseBlock
from paper_copilot.session import SessionStore
from paper_copilot.shared.cost import UsageLike
from paper_copilot.shared.errors import AgentError, SchemaValidationError


@dataclass(frozen=True, slots=True)
class ValidatedToolCall[T: BaseModel]:
    parsed: T
    response: LLMResponse
    responses: tuple[LLMResponse, ...]


async def call_validated_tool[ToolInputT: BaseModel](
    client: LLMClient,
    *,
    agent_name: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_name: str,
    tool_input_model: type[ToolInputT],
    store: SessionStore | None = None,
    system: str | list[dict[str, Any]] | None = None,
    max_tokens: int | None = None,
    max_schema_retries: int = 1,
) -> ValidatedToolCall[ToolInputT]:
    attempt_messages = messages
    responses: list[LLMResponse] = []
    for attempt in range(max_schema_retries + 1):
        response = await client.generate(
            messages=attempt_messages,
            tools=tools,
            tool_choice={"type": "tool", "name": tool_name},
            system=system,
            max_tokens=max_tokens,
        )
        responses.append(response)
        _record_response(store, agent_name=agent_name, model=model, response=response)

        block = _single_tool_block(response, tool_name)
        try:
            parsed = tool_input_model.model_validate(block.input)
        except ValidationError as exc:
            error = _summarize_validation_error(exc)
            if store is not None:
                store.append_schema_validation(
                    success=False,
                    error=error,
                    retry_count=attempt,
                )
            if attempt >= max_schema_retries:
                raise SchemaValidationError(
                    f"{agent_name} schema validation failed for {tool_name!r} "
                    f"after {attempt + 1} attempts: {error}"
                ) from exc
            if store is not None:
                store.append_tool_result(block.id, error, is_error=True)
            attempt_messages = _build_retry_messages(messages, block, error)
        else:
            if store is not None:
                store.append_schema_validation(success=True, retry_count=attempt)
            return ValidatedToolCall(
                parsed=parsed,
                response=response,
                responses=tuple(responses),
            )

    raise AssertionError("schema retry loop exhausted without returning or raising")


def _record_response(
    store: SessionStore | None,
    *,
    agent_name: str,
    model: str,
    response: LLMResponse,
) -> None:
    if store is None:
        return
    usage: UsageLike = response.usage if response.usage is not None else {}
    store.append_llm_call(
        agent=agent_name,
        model=model,
        usage=usage,
        latency_ms=response.latency_ms,
        stop_reason=response.stop_reason,
    )
    for block in response.content:
        if isinstance(block, TextBlock):
            store.append_message(role="assistant", text=block.text)
        elif isinstance(block, ToolUseBlock):
            store.append_tool_use(block.id, block.name, block.input)


def _single_tool_block(response: LLMResponse, tool_name: str) -> ToolUseBlock:
    tool_use_blocks = [b for b in response.content if isinstance(b, ToolUseBlock)]
    if len(tool_use_blocks) != 1:
        raise AgentError(
            f"expected exactly 1 tool_use block, got {len(tool_use_blocks)} "
            f"(stop_reason={response.stop_reason!r}, "
            f"total content blocks={len(response.content)})"
        )
    block = tool_use_blocks[0]
    if block.name != tool_name:
        raise AgentError(f"expected tool_use name={tool_name!r}, got {block.name!r}")
    return block


def _build_retry_messages(
    messages: list[dict[str, Any]],
    block: ToolUseBlock,
    error: str,
) -> list[dict[str, Any]]:
    return [
        *messages,
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "is_error": True,
                    "content": (
                        "Schema validation failed. Call the same tool again with "
                        f"corrected input that satisfies the schema. Error: {error}"
                    ),
                }
            ],
        },
    ]


def _summarize_validation_error(exc: ValidationError) -> str:
    errors = exc.errors(include_url=False)
    parts: list[str] = []
    for item in errors[:5]:
        loc = ".".join(str(part) for part in item["loc"]) or "<root>"
        parts.append(f"{loc}: {item['msg']}")
    if len(errors) > 5:
        parts.append(f"... {len(errors) - 5} more")
    return "; ".join(parts)
