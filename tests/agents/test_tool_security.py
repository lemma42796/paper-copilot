from __future__ import annotations

import asyncio
import json
from pathlib import Path

from paper_copilot.agents.library_files_tool import LibraryFilesInput
from paper_copilot.agents.loop import ToolUseRequest
from paper_copilot.agents.paper_copilot import (
    PaperCopilotContext,
    dispatch_paper_copilot_tool_async,
)
from paper_copilot.agents.tool_security import (
    ToolDefinition,
    cap_tool_output,
    evaluate_tool_call,
)
from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.shared.cost import CostTracker, pricing_for_model


def _library_definition() -> ToolDefinition:
    return ToolDefinition(
        name="library_files",
        description="test",
        input_model=LibraryFilesInput,
        effects=frozenset({"read_library", "write_library"}),
        output_max_chars=100,
    )


def test_library_reads_are_allowed_but_mutations_require_approval() -> None:
    allowed = evaluate_tool_call(
        _library_definition(),
        LibraryFilesInput(operation="list"),
    )
    guarded = evaluate_tool_call(
        _library_definition(),
        LibraryFilesInput(operation="trash", paths=["paper.pdf"]),
    )

    assert allowed.kind == "allow"
    assert guarded.kind == "require_approval"
    assert guarded.approval is not None
    assert guarded.approval.tool_input["paths"] == ["paper.pdf"]


def test_tool_output_cap_returns_auditable_envelope() -> None:
    capped = json.loads(cap_tool_output("x" * 1_000, 100))

    assert capped["status"] == "truncated"
    assert capped["original_length"] == 1_000
    assert len(capped["sha256"]) == 64


def test_approved_library_mutation_executes_once(tmp_path: Path) -> None:
    approvals: list[str] = []

    async def approve(request: object) -> bool:
        approvals.append(getattr(request, "tool_name"))
        return True

    with FieldsStore.open(tmp_path / "fields.db") as fields_store:
        context = PaperCopilotContext(
            fields_store=fields_store,
            pdf_dir=tmp_path,
        )
        tool_result = asyncio.run(
            dispatch_paper_copilot_tool_async(
                ToolUseRequest(
                    id="mkdir-1",
                    name="library_files",
                    input={"operation": "mkdir", "destination": "new"},
                ),
                context,
                read_llm=None,
                cost=CostTracker(pricing=pricing_for_model("qwen3.6-flash")),
                max_budget_cny=1.0,
                request_tool_approval=approve,
            )
        )

    assert tool_result.is_error is False
    assert approvals == ["library_files"]
    assert (tmp_path / "new").is_dir()
