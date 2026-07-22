from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

ToolEffect = Literal[
    "read_library",
    "write_library",
    "write_index",
    "spend_llm_budget",
    "update_job_state",
]
ToolDecisionKind = Literal["allow", "deny", "require_approval"]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    effects: frozenset[ToolEffect]
    output_max_chars: int


class ToolApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    tool_name: str
    reason: str
    effects: list[ToolEffect]
    tool_input: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolPolicyDecision:
    kind: ToolDecisionKind
    reason: str | None = None
    approval: ToolApprovalRequest | None = None


def evaluate_tool_call(
    definition: ToolDefinition,
    parsed_input: BaseModel,
) -> ToolPolicyDecision:
    effects = definition.effects
    if definition.name == "library_files":
        operation = getattr(parsed_input, "operation", None)
        if operation in {"mkdir", "copy", "move", "trash", "restore"}:
            approval = ToolApprovalRequest(
                id=f"approval-{uuid4()}",
                tool_name=definition.name,
                reason=_library_mutation_reason(parsed_input),
                effects=["write_library"],
                tool_input=parsed_input.model_dump(mode="json", exclude_none=True),
            )
            return ToolPolicyDecision(
                kind="require_approval",
                reason=approval.reason,
                approval=approval,
            )
    return ToolPolicyDecision(kind="allow")


def cap_tool_output(output: str, max_chars: int) -> str:
    if len(output) <= max_chars:
        return output
    preview_chars = max(max_chars - 500, 0)
    payload = {
        "status": "truncated",
        "reason": "tool output exceeded its application-defined context limit",
        "preview": output[:preview_chars],
        "original_length": len(output),
        "sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _library_mutation_reason(parsed_input: BaseModel) -> str:
    payload = parsed_input.model_dump(mode="json", exclude_none=True)
    operation = str(payload.get("operation", "write"))
    paths = payload.get("paths", [])
    destination = payload.get("destination")
    parts = [f"论文库文件操作 `{operation}` 会修改磁盘内容"]
    if paths:
        parts.append("目标: " + ", ".join(str(path) for path in paths[:5]))
    if destination:
        parts.append(f"位置: {destination}")
    return "；".join(parts) + "。"
