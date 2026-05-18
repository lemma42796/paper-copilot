import asyncio
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from paper_copilot.agents.mock_llm import MockLLM, MockResponse, ToolUseBlock
from paper_copilot.agents.tool_validation import call_validated_tool
from paper_copilot.session import SchemaValidation, SessionStore, ToolResult
from paper_copilot.shared.errors import SchemaValidationError


class _ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


def _tool_response(tool_id: str, input_: dict[str, object]) -> MockResponse:
    return MockResponse(
        content=[ToolUseBlock(id=tool_id, name="emit_test", input=input_)],
        stop_reason="tool_use",
        usage={"input_tokens": 1, "output_tokens": 2},
    )


def test_call_validated_tool_retries_once_after_schema_error(tmp_path: Path) -> None:
    store = SessionStore.create("abc", model="m", agent="test", root=tmp_path)
    llm = MockLLM([_tool_response("bad", {}), _tool_response("good", {"value": 7})])

    result = asyncio.run(
        call_validated_tool(
            llm,
            agent_name="TestAgent",
            model="m",
            messages=[{"role": "user", "content": "go"}],
            tools=[{"name": "emit_test", "input_schema": {}}],
            tool_name="emit_test",
            tool_input_model=_ToolInput,
            store=store,
            system="sys",
        )
    )

    assert result.parsed.value == 7
    assert result.response is result.responses[-1]
    assert len(result.responses) == 2

    entries = store.read_all()
    validations = [e for e in entries if isinstance(e, SchemaValidation)]
    assert [(v.success, v.retry_count) for v in validations] == [(False, 0), (True, 1)]
    assert validations[0].error is not None
    assert "value" in validations[0].error
    tool_results = [e for e in entries if isinstance(e, ToolResult)]
    assert len(tool_results) == 1
    assert tool_results[0].is_error is True


def test_call_validated_tool_raises_after_retry_is_exhausted(tmp_path: Path) -> None:
    store = SessionStore.create("abc", model="m", agent="test", root=tmp_path)
    llm = MockLLM([_tool_response("bad1", {}), _tool_response("bad2", {})])

    with pytest.raises(SchemaValidationError, match="TestAgent schema validation failed"):
        asyncio.run(
            call_validated_tool(
                llm,
                agent_name="TestAgent",
                model="m",
                messages=[{"role": "user", "content": "go"}],
                tools=[{"name": "emit_test", "input_schema": {}}],
                tool_name="emit_test",
                tool_input_model=_ToolInput,
                store=store,
                system="sys",
            )
        )

    validations = [e for e in store.read_all() if isinstance(e, SchemaValidation)]
    assert [(v.success, v.retry_count) for v in validations] == [(False, 0), (False, 1)]
