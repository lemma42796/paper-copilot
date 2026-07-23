from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# branch_summary is reserved for a future milestone.
EntryType = Literal[
    "session_header",
    "system_message",
    "message",
    "reasoning",
    "tool_use",
    "tool_result",
    "schema_validation",
    "final_output",
    "llm_call",
    "compaction",
    "runtime_state",
    "recovery_base",
    "turn_aborted",
    "branch_summary",
]


class SessionHeader(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    ts: str
    type: Literal["session_header"] = "session_header"
    paper_id: str
    cwd: str
    model: str
    agent: str


class SystemMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    ts: str
    type: Literal["system_message"] = "system_message"
    parent_id: str | None
    text: str


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    ts: str
    type: Literal["message"] = "message"
    parent_id: str | None
    role: Literal["user", "assistant"]
    text: str


class Reasoning(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    ts: str
    type: Literal["reasoning"] = "reasoning"
    parent_id: str | None
    text: str


class ToolUse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    ts: str
    type: Literal["tool_use"] = "tool_use"
    parent_id: str | None
    tool_use_id: str
    name: str
    input: dict[str, Any]


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    ts: str
    type: Literal["tool_result"] = "tool_result"
    parent_id: str | None
    tool_use_id: str
    output: str
    is_error: bool


class SchemaValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    ts: str
    type: Literal["schema_validation"] = "schema_validation"
    parent_id: str | None
    success: bool
    error: str | None = None
    retry_count: int = 0


class FinalOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    ts: str
    type: Literal["final_output"] = "final_output"
    parent_id: str | None
    payload: dict[str, Any]


class LLMCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    ts: str
    type: Literal["llm_call"] = "llm_call"
    parent_id: str | None
    agent: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    latency_ms: int
    stop_reason: str
    prompt_sha256: str | None = None


class Compaction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    ts: str
    type: Literal["compaction"] = "compaction"
    parent_id: str | None
    summary_version: int
    source_message_count: int
    retained_message_count: int
    trigger_estimated_input_tokens: int
    estimated_before_tokens: int
    estimated_after_tokens: int
    estimated_retained_recent_tokens: int
    summary_output_tokens: int
    model: str
    summary: dict[str, Any]
    replacement_history: list[dict[str, Any]] | None = None


class RuntimeState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    ts: str
    type: Literal["runtime_state"] = "runtime_state"
    parent_id: str | None
    state: dict[str, Any]


class RecoveryBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    ts: str
    type: Literal["recovery_base"] = "recovery_base"
    parent_id: str | None
    source_session_path: str
    history: list[dict[str, Any]]
    runtime_state: dict[str, Any] | None = None
    compaction_summary: dict[str, Any] | None = None


class TurnAborted(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    ts: str
    type: Literal["turn_aborted"] = "turn_aborted"
    parent_id: str | None
    reason: str


SessionEntry = Annotated[
    SessionHeader
    | SystemMessage
    | Message
    | Reasoning
    | ToolUse
    | ToolResult
    | SchemaValidation
    | FinalOutput
    | LLMCall
    | Compaction
    | RuntimeState
    | RecoveryBase
    | TurnAborted,
    Field(discriminator="type"),
]
