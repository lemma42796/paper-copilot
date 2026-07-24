from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
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
ApprovalMode = Literal["ask", "auto_review"]
ApprovalRequirement = Literal["approval", "explicit_confirmation"]
ApprovalReviewer = Literal["user", "auto_review"]
ApprovalReviewStatus = Literal["started", "approved", "denied", "failed"]


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
    tool_call_id: str = "legacy"
    tool_name: str
    reason: str
    effects: list[ToolEffect]
    tool_input: dict[str, Any]
    input_sha256: str = ""
    target_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    requirement: ApprovalRequirement = "explicit_confirmation"
    auto_review_allowed: bool = False


class ToolApprovalReviewEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str
    reviewer: ApprovalReviewer
    status: ApprovalReviewStatus
    risk_level: Literal["low", "medium", "high", "critical"] | None = None
    user_authorization: Literal["unknown", "low", "medium", "high"] | None = None
    rationale: str | None = None


@dataclass(frozen=True, slots=True)
class ToolPolicyDecision:
    kind: ToolDecisionKind
    reason: str | None = None
    approval: ToolApprovalRequest | None = None


def evaluate_tool_call(
    definition: ToolDefinition,
    parsed_input: BaseModel,
    *,
    tool_call_id: str = "unknown",
    library_root: Path | None = None,
) -> ToolPolicyDecision:
    effects = definition.effects
    if definition.name == "library_files":
        operation = getattr(parsed_input, "operation", None)
        if operation in {"mkdir", "copy", "move", "trash", "restore"}:
            tool_input = parsed_input.model_dump(mode="json", exclude_none=True)
            requirement = _library_mutation_requirement(tool_input)
            approval = ToolApprovalRequest(
                id=f"approval-{uuid4()}",
                tool_call_id=tool_call_id,
                tool_name=definition.name,
                reason=_library_mutation_reason(parsed_input),
                effects=["write_library"],
                tool_input=tool_input,
                input_sha256=tool_input_sha256(tool_input),
                target_snapshot=_library_target_snapshot(tool_input, library_root),
                requirement=requirement,
                auto_review_allowed=requirement == "approval",
            )
            return ToolPolicyDecision(
                kind="require_approval",
                reason=approval.reason,
                approval=approval,
            )
    return ToolPolicyDecision(kind="allow")


def tool_input_sha256(tool_input: dict[str, Any]) -> str:
    encoded = json.dumps(
        tool_input,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def approval_matches(
    approval: ToolApprovalRequest,
    *,
    tool_call_id: str,
    parsed_input: BaseModel,
    library_root: Path | None = None,
) -> bool:
    tool_input = parsed_input.model_dump(mode="json", exclude_none=True)
    return (
        approval.tool_call_id == tool_call_id
        and approval.input_sha256 == tool_input_sha256(tool_input)
        and approval.target_snapshot
        == _library_target_snapshot(tool_input, library_root)
    )


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


def _library_mutation_requirement(
    tool_input: dict[str, Any],
) -> ApprovalRequirement:
    operation = tool_input.get("operation")
    paths = tool_input.get("paths")
    path_count = len(paths) if isinstance(paths, list) else 0
    if operation in {"trash", "restore"} or path_count >= 10:
        return "explicit_confirmation"
    return "approval"


def _library_target_snapshot(
    tool_input: dict[str, Any],
    library_root: Path | None,
) -> list[dict[str, Any]]:
    if library_root is None:
        return []
    root = library_root.expanduser().resolve()
    raw_paths = tool_input.get("paths")
    paths = [str(path) for path in raw_paths] if isinstance(raw_paths, list) else []
    destination = tool_input.get("destination")
    if isinstance(destination, str):
        paths.append(destination)
    receipt_id = tool_input.get("receipt_id")
    if isinstance(receipt_id, str):
        paths.append(f".paper-copilot-trash/{receipt_id}/manifest.json")
    snapshots: list[dict[str, Any]] = []
    for raw_path in paths:
        resolved = (root / raw_path).resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            snapshots.append({"path": raw_path, "status": "outside_library"})
            continue
        if not resolved.exists():
            snapshots.append({"path": str(relative), "status": "missing"})
            continue
        stat = resolved.stat()
        snapshots.append(
            {
                "path": str(relative),
                "status": "present",
                "kind": "directory" if resolved.is_dir() else "file",
                "size_bytes": stat.st_size,
                "modified_ns": stat.st_mtime_ns,
            }
        )
    return snapshots
