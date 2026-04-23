from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# compaction is reserved for M9+, branch_summary is reserved for M7+.
# The Union below does not include models for those variants yet.
EntryType = Literal[
    "session_header",
    "system_message",
    "message",
    "tool_use",
    "tool_result",
    "schema_validation",
    "final_output",
    "compaction",
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


SessionEntry = Annotated[
    SessionHeader | SystemMessage | Message | ToolUse | ToolResult | SchemaValidation | FinalOutput,
    Field(discriminator="type"),
]
