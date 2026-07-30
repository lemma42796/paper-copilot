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
    TurnAborted,
    TurnCompleted,
    TurnStarted,
    WorldState,
)


@dataclass(frozen=True, slots=True)
class RecoveredRollout:
    history: list[dict[str, Any]]
    runtime_state: dict[str, Any] | None
    compaction_summary: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class _TurnSegment:
    turn_id: str
    entries: tuple[SessionEntry, ...]
    completed: bool


def reconstruct_rollout(
    entries: list[SessionEntry],
    *,
    fallback_history: list[dict[str, Any]],
) -> RecoveredRollout:
    history, start_index = _initial_history(entries, fallback_history)
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
        elif isinstance(entry, WorldState) and entry.model_visible:
            flush_assistant()
            user_blocks.append({"type": "text", "text": entry.rendered})

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


def conversation_entries_for_resume(
    entries: list[SessionEntry],
    *,
    current_turn_id: str,
) -> list[SessionEntry]:
    prefix, segments = _turn_segments(entries)
    if not segments:
        return entries
    completed_turn_ids = {
        segment.turn_id for segment in segments if segment.completed
    }
    selected = list(prefix)
    for segment in segments:
        if (
            segment.turn_id == current_turn_id
            or segment.turn_id in completed_turn_ids
        ):
            selected.extend(segment.entries)
    return selected


def entries_for_turn(
    entries: list[SessionEntry],
    *,
    turn_id: str,
) -> list[SessionEntry]:
    prefix, segments = _turn_segments(entries)
    if not segments:
        return entries
    header = prefix[:1]
    selected = [
        entry
        for segment in segments
        if segment.turn_id == turn_id
        for entry in segment.entries
    ]
    return [*header, *selected]


def _initial_history(
    entries: list[SessionEntry],
    fallback_history: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    replacement_index: int | None = None
    replacement_history: list[dict[str, Any]] | None = None
    for index, entry in enumerate(entries):
        replacement = _replacement_history(entry)
        if replacement is not None:
            replacement_index = index
            replacement_history = replacement
    if replacement_index is not None and replacement_history is not None:
        return deepcopy(replacement_history), replacement_index + 1

    first_llm_call_index = _first_llm_call_index(entries)
    if any(
        isinstance(entry, Message) and entry.role == "user"
        for entry in entries[:first_llm_call_index]
    ):
        return [], 0
    return deepcopy(fallback_history), first_llm_call_index


def _turn_segments(
    entries: list[SessionEntry],
) -> tuple[list[SessionEntry], list[_TurnSegment]]:
    prefix: list[SessionEntry] = []
    segments: list[_TurnSegment] = []
    active: list[SessionEntry] | None = None
    active_turn_id: str | None = None
    for entry in entries:
        if isinstance(entry, TurnStarted):
            if active is not None and active_turn_id is not None:
                segments.append(
                    _TurnSegment(
                        turn_id=active_turn_id,
                        entries=tuple(active),
                        completed=False,
                    )
                )
            active = [entry]
            active_turn_id = entry.turn_id
            continue
        if active is None or active_turn_id is None:
            prefix.append(entry)
            continue
        active.append(entry)
        if isinstance(entry, TurnCompleted | TurnAborted):
            segments.append(
                _TurnSegment(
                    turn_id=active_turn_id,
                    entries=tuple(active),
                    completed=isinstance(entry, TurnCompleted),
                )
            )
            active = None
            active_turn_id = None
    if active is not None and active_turn_id is not None:
        segments.append(
            _TurnSegment(
                turn_id=active_turn_id,
                entries=tuple(active),
                completed=False,
            )
        )
    return prefix, segments


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
