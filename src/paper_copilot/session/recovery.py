from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .types import (
    Compaction,
    LLMCall,
    Message,
    Reasoning,
    RecoveryBase,
    RuntimeState,
    SessionEntry,
    ToolResult,
    ToolUse,
)


@dataclass(frozen=True, slots=True)
class RecoveredRollout:
    history: list[dict[str, Any]]
    runtime_state: dict[str, Any] | None
    compaction_summary: dict[str, Any] | None


def reconstruct_rollout(
    entries: list[SessionEntry],
    *,
    fallback_history: list[dict[str, Any]],
) -> RecoveredRollout:
    history = deepcopy(fallback_history)
    start_index = _first_llm_call_index(entries)
    compaction_summary: dict[str, Any] | None = None
    for index, entry in enumerate(entries):
        replacement = _replacement_history(entry)
        if replacement is not None:
            history = deepcopy(replacement)
            start_index = index + 1
            compaction_summary = _compaction_summary(entry)

    assistant_blocks: list[dict[str, Any]] = []
    assistant_reasoning: list[str] = []
    user_blocks: list[dict[str, Any]] = []

    def flush_assistant() -> None:
        if assistant_blocks or assistant_reasoning:
            message: dict[str, Any] = {
                "role": "assistant",
                "content": assistant_blocks.copy(),
            }
            if assistant_reasoning:
                message["reasoning_content"] = "".join(assistant_reasoning)
            history.append(message)
            assistant_blocks.clear()
            assistant_reasoning.clear()

    def flush_user() -> None:
        if user_blocks:
            history.append({"role": "user", "content": user_blocks.copy()})
            user_blocks.clear()

    for entry in entries[start_index:]:
        replacement = _replacement_history(entry)
        if replacement is not None:
            flush_assistant()
            flush_user()
            history = deepcopy(replacement)
            continue
        if isinstance(entry, LLMCall):
            flush_assistant()
            flush_user()
        elif isinstance(entry, Message) and entry.role == "assistant":
            flush_user()
            assistant_blocks.append({"type": "text", "text": entry.text})
        elif isinstance(entry, Reasoning):
            flush_user()
            assistant_reasoning.append(entry.text)
        elif isinstance(entry, ToolUse):
            flush_user()
            assistant_blocks.append(
                {
                    "type": "tool_use",
                    "id": entry.tool_use_id,
                    "name": entry.name,
                    "input": entry.input,
                }
            )
        elif isinstance(entry, ToolResult):
            flush_assistant()
            user_blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": entry.tool_use_id,
                    "content": entry.output,
                    "is_error": entry.is_error,
                }
            )
        elif isinstance(entry, Message) and entry.role == "user":
            flush_assistant()
            user_blocks.append({"type": "text", "text": entry.text})

    flush_assistant()
    flush_user()
    _insert_aborted_tool_results(history)
    runtime_state = next(
        (
            deepcopy(_runtime_state(entry))
            for entry in reversed(entries)
            if _runtime_state(entry) is not None
        ),
        None,
    )
    return RecoveredRollout(
        history=history,
        runtime_state=runtime_state,
        compaction_summary=compaction_summary,
    )


def _first_llm_call_index(entries: list[SessionEntry]) -> int:
    for index, entry in enumerate(entries):
        if isinstance(entry, LLMCall):
            return index
    return len(entries)


def _replacement_history(entry: SessionEntry) -> list[dict[str, Any]] | None:
    if isinstance(entry, RecoveryBase):
        return entry.history
    if isinstance(entry, Compaction):
        return entry.replacement_history
    return None


def _compaction_summary(entry: SessionEntry) -> dict[str, Any] | None:
    if isinstance(entry, RecoveryBase):
        return entry.compaction_summary
    if isinstance(entry, Compaction):
        return entry.summary
    return None


def _runtime_state(entry: SessionEntry) -> dict[str, Any] | None:
    if isinstance(entry, RuntimeState):
        return entry.state
    if isinstance(entry, RecoveryBase):
        return entry.runtime_state
    return None


def _insert_aborted_tool_results(history: list[dict[str, Any]]) -> None:
    completed_ids = {
        str(block["tool_use_id"])
        for message in history
        if message.get("role") == "user"
        for block in _content_blocks(message)
        if block.get("type") == "tool_result" and "tool_use_id" in block
    }
    index = 0
    while index < len(history):
        message = history[index]
        if message.get("role") != "assistant":
            index += 1
            continue
        missing_ids = [
            str(block["id"])
            for block in _content_blocks(message)
            if block.get("type") == "tool_use"
            and "id" in block
            and str(block["id"]) not in completed_ids
        ]
        if not missing_ids:
            index += 1
            continue
        aborted = [
            {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": "aborted",
                "is_error": True,
            }
            for tool_use_id in missing_ids
        ]
        if index + 1 < len(history) and history[index + 1].get("role") == "user":
            content = _content_blocks(history[index + 1])
            history[index + 1] = {
                **history[index + 1],
                "content": [*aborted, *content],
            }
        else:
            history.insert(index + 1, {"role": "user", "content": aborted})
        completed_ids.update(missing_ids)
        index += 2


def _content_blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    content = message.get("content")
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return []
