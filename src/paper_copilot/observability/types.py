from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TraceEntityType = Literal["rollout", "turn", "llm_call", "tool_call", "compaction"]
TraceStatus = Literal["running", "completed", "failed", "cancelled", "aborted"]
TraceEventType = Literal[
    "rollout.started",
    "rollout.completed",
    "rollout.failed",
    "rollout.cancelled",
    "turn.started",
    "turn.completed",
    "turn.failed",
    "turn.cancelled",
    "llm_call.started",
    "llm_call.completed",
    "llm_call.failed",
    "llm_call.cancelled",
    "tool_call.started",
    "tool_call.completed",
    "tool_call.failed",
    "tool_call.cancelled",
    "tool_call.aborted",
    "compaction.started",
    "compaction.completed",
    "compaction.failed",
    "compaction.cancelled",
]


class TraceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    trace_id: str
    job_id: str
    attempt: int = Field(ge=1)
    session_id: str
    turn_id: str
    started_at: str
    payload_policy: Literal["local_safe_v1"] = "local_safe_v1"
    payload_max_bytes: int = Field(default=262_144, ge=1)
    payload_max_string_chars: int = Field(default=2_000, ge=1)


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    seq: int = Field(ge=1)
    event_id: str
    ts: str
    job_id: str
    attempt: int = Field(ge=1)
    session_id: str
    turn_id: str
    entity_type: TraceEntityType
    entity_id: str
    parent_entity_id: str | None = None
    event_type: TraceEventType
    status: TraceStatus
    duration_ms: int | None = Field(default=None, ge=0)
    error_type: str | None = None
    error_message: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    payload_refs: dict[str, str] = Field(default_factory=dict)


class ReducedOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: TraceEntityType
    entity_id: str
    parent_entity_id: str | None = None
    started_seq: int = Field(ge=1)
    started_at: str
    terminal_seq: int | None = Field(default=None, ge=1)
    terminal_at: str | None = None
    status: TraceStatus
    duration_ms: int | None = Field(default=None, ge=0)
    error_type: str | None = None
    error_message: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    payload_refs: dict[str, str] = Field(default_factory=dict)


class RolloutState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    trace_id: str
    job_id: str
    attempt: int = Field(ge=1)
    session_id: str
    turn_id: str
    status: TraceStatus
    event_count: int = Field(ge=0)
    operations: list[ReducedOperation]
