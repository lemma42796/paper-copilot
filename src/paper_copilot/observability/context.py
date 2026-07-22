from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from paper_copilot.observability.recorder import RolloutRecorder

_recorder: ContextVar[RolloutRecorder | None] = ContextVar(
    "paper_copilot_rollout_recorder",
    default=None,
)
_entity_id: ContextVar[str | None] = ContextVar(
    "paper_copilot_trace_entity_id",
    default=None,
)
_last_llm_call_id: ContextVar[str | None] = ContextVar(
    "paper_copilot_last_llm_call_id",
    default=None,
)


def current_recorder() -> RolloutRecorder | None:
    return _recorder.get()


def current_entity_id() -> str | None:
    return _entity_id.get()


def current_llm_call_id() -> str | None:
    return _last_llm_call_id.get()


def set_last_llm_call_id(llm_call_id: str) -> None:
    _last_llm_call_id.set(llm_call_id)


@contextmanager
def activate_recorder(recorder: RolloutRecorder) -> Iterator[None]:
    recorder_token = _recorder.set(recorder)
    entity_token = _entity_id.set(recorder.rollout_entity_id)
    llm_token = _last_llm_call_id.set(None)
    try:
        yield
    finally:
        _last_llm_call_id.reset(llm_token)
        _entity_id.reset(entity_token)
        _recorder.reset(recorder_token)


def set_current_entity(entity_id: str) -> Token[str | None]:
    return _entity_id.set(entity_id)


def reset_current_entity(token: Token[str | None]) -> None:
    _entity_id.reset(token)
