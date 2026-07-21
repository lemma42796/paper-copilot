from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from paper_copilot.agents.context_compaction import compact_history
from paper_copilot.agents.mock_llm import MockLLM, MockResponse, ToolUseBlock
from paper_copilot.schemas import CompactionSummary
from paper_copilot.session import Compaction, Message, SchemaValidation, SessionStore
from paper_copilot.shared.cost import CostTracker
from paper_copilot.shared.errors import AgentError


def _summary(
    *,
    evidence_refs: list[str] | None = None,
    constraints: list[str] | None = None,
) -> dict[str, object]:
    return {
        "version": 1,
        "original_goal": "compare the selected papers",
        "active_constraints": constraints or ["retain exact evidence references"],
        "decisions": ["paper-a is the baseline"],
        "completed_work": ["searched the local library"],
        "evidence_and_identifiers": evidence_refs or ["[paper-a:chunks[1]]"],
        "failed_attempts": [],
        "open_questions": ["which module should be attached next"],
        "next_actions": ["inspect paper-b"],
        "superseded_information": [],
    }


def _compaction_response(
    tool_id: str,
    summary: dict[str, object],
    *,
    input_tokens: int = 100,
    output_tokens: int = 20,
) -> MockResponse:
    return MockResponse(
        content=[
            ToolUseBlock(
                id=tool_id,
                name="record_compaction_summary",
                input=summary,
            )
        ],
        stop_reason="tool_use",
        usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
    )


def _round(index: int, *, evidence_ref: str) -> list[dict[str, object]]:
    tool_id = f"tool-{index}"
    return [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": "query_paper",
                    "input": {"paper_id": f"paper-{index}"},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": json.dumps(
                        {"paper_id": f"paper-{index}", "evidence": evidence_ref}
                    ),
                    "is_error": False,
                },
                {
                    "type": "text",
                    "text": (
                        "<runtime_context>\n"
                        f'{{"round":{index}}}\n'
                        "</runtime_context>"
                    ),
                },
            ],
        },
    ]


def _history() -> list[dict[str, object]]:
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "old runtime"},
                {"type": "text", "text": "compare papers"},
            ],
        },
        *_round(1, evidence_ref="[paper-a:chunks[1]]"),
        *_round(2, evidence_ref="[paper-b:chunks[2]]"),
        *_round(3, evidence_ref="[paper-c:chunks[3]]"),
    ]


def _runtime_context() -> str:
    return (
        "<runtime_context>\n"
        '{"latest_state_is_authoritative":true,"paper_id":"paper-a"}\n'
        "</runtime_context>"
    )


def test_compact_history_preserves_anchor_recent_round_and_session(
    tmp_path: Path,
) -> None:
    original_request = "请比较 paper-a 和 paper-b"
    store = SessionStore.create("compact", model="m", agent="test", root=tmp_path)
    store.append_message("user", original_request)
    llm = MockLLM([_compaction_response("summary-1", _summary())])
    cost = CostTracker()

    result = asyncio.run(
        compact_history(
            llm,
            history=_history(),
            original_request=original_request,
            build_runtime_context=_runtime_context,
            previous_summary=None,
            required_identifiers={"paper-a", "[paper-a:chunks[1]]"},
            recent_history_budget_tokens=1,
            max_output_tokens=8_000,
            trigger_estimated_input_tokens=200_000,
            model="m",
            cost=cost,
            store=store,
        )
    )

    assert result.source_message_count == 4
    assert result.retained_message_count == 2
    assert len(result.history) == 3
    anchor_content = result.history[0]["content"]
    assert isinstance(anchor_content, list)
    anchor_text = "\n".join(str(block.get("text", "")) for block in anchor_content)
    assert json.dumps(original_request, ensure_ascii=False) in anchor_text
    assert _runtime_context() in anchor_text
    assert '"round":1' not in json.dumps(result.history, ensure_ascii=False)
    assert '"round":2' not in json.dumps(result.history, ensure_ascii=False)
    assert '"round":3' not in json.dumps(result.history, ensure_ascii=False)

    retained_assistant = result.history[1]
    retained_user = result.history[2]
    assert retained_assistant["role"] == "assistant"
    assert retained_user["role"] == "user"
    assert "tool-3" in json.dumps(retained_assistant)
    assert "tool-3" in json.dumps(retained_user)
    assert cost.total_input_tokens == 100
    assert cost.total_output_tokens == 20

    entries = store.read_all()
    assert any(isinstance(entry, Message) and entry.text == original_request for entry in entries)
    compactions = [entry for entry in entries if isinstance(entry, Compaction)]
    assert len(compactions) == 1
    assert compactions[0].trigger_estimated_input_tokens == 200_000
    assert compactions[0].summary_output_tokens == 20


def test_compact_history_retries_deterministic_validation_and_counts_cost(
    tmp_path: Path,
) -> None:
    invalid = _summary(evidence_refs=["[fake:chunks[9]]", "paper-a"])
    valid = _summary(evidence_refs=["[paper-a:chunks[1]]", "paper-a"])
    llm = MockLLM(
        [
            _compaction_response("bad", invalid, input_tokens=11, output_tokens=2),
            _compaction_response("good", valid, input_tokens=13, output_tokens=3),
        ]
    )
    store = SessionStore.create("retry", model="m", agent="test", root=tmp_path)
    cost = CostTracker()

    result = asyncio.run(
        compact_history(
            llm,
            history=_history(),
            original_request="compare papers",
            build_runtime_context=_runtime_context,
            previous_summary=None,
            required_identifiers={"paper-a", "[paper-a:chunks[1]]"},
            recent_history_budget_tokens=1,
            max_output_tokens=8_000,
            trigger_estimated_input_tokens=200_000,
            model="m",
            cost=cost,
            store=store,
        )
    )

    assert result.summary.evidence_and_identifiers == [
        "[paper-a:chunks[1]]",
        "paper-a",
    ]
    assert len(llm.calls) == 2
    assert cost.total_input_tokens == 24
    assert cost.total_output_tokens == 5
    validations = [entry for entry in store.read_all() if isinstance(entry, SchemaValidation)]
    assert [(entry.success, entry.retry_count) for entry in validations] == [
        (False, 0),
        (True, 1),
    ]
    assert validations[0].error is not None
    assert "absent from source" in validations[0].error


def test_repeated_compaction_passes_previous_summary_to_next_call(tmp_path: Path) -> None:
    first_summary = _summary(constraints=["keep constraint-v1"])
    second_summary = _summary(constraints=["keep constraint-v1", "add constraint-v2"])
    llm = MockLLM(
        [
            _compaction_response("first", first_summary),
            _compaction_response("second", second_summary),
        ]
    )
    store = SessionStore.create("repeat", model="m", agent="test", root=tmp_path)
    cost = CostTracker()

    first = asyncio.run(
        compact_history(
            llm,
            history=_history(),
            original_request="compare papers",
            build_runtime_context=_runtime_context,
            previous_summary=None,
            required_identifiers={"paper-a", "[paper-a:chunks[1]]"},
            recent_history_budget_tokens=1,
            max_output_tokens=8_000,
            trigger_estimated_input_tokens=200_000,
            model="m",
            cost=cost,
            store=store,
        )
    )
    next_history = [
        *first.history,
        *_round(4, evidence_ref="[paper-d:chunks[4]]"),
        *_round(5, evidence_ref="[paper-e:chunks[5]]"),
    ]
    second = asyncio.run(
        compact_history(
            llm,
            history=next_history,
            original_request="compare papers",
            build_runtime_context=_runtime_context,
            previous_summary=first.summary,
            required_identifiers={"paper-a", "[paper-a:chunks[1]]"},
            recent_history_budget_tokens=1,
            max_output_tokens=8_000,
            trigger_estimated_input_tokens=200_000,
            model="m",
            cost=cost,
            store=store,
        )
    )

    assert second.summary.active_constraints == ["keep constraint-v1", "add constraint-v2"]
    second_prompt = llm.calls[1].messages[0]["content"]
    assert isinstance(second_prompt, str)
    assert "keep constraint-v1" in second_prompt
    assert len([entry for entry in store.read_all() if isinstance(entry, Compaction)]) == 2


def test_compact_history_rejects_broken_tool_pair_before_llm(tmp_path: Path) -> None:
    history = _history()
    broken_user = history[2]
    assert isinstance(broken_user["content"], list)
    broken_user["content"][0]["tool_use_id"] = "different-id"
    llm = MockLLM([])
    store = SessionStore.create("broken", model="m", agent="test", root=tmp_path)

    with pytest.raises(AgentError, match="matching tool_use and tool_result"):
        asyncio.run(
            compact_history(
                llm,
                history=history,
                original_request="compare papers",
                build_runtime_context=_runtime_context,
                previous_summary=None,
                required_identifiers=set(),
                recent_history_budget_tokens=1,
                max_output_tokens=8_000,
                trigger_estimated_input_tokens=200_000,
                model="m",
                cost=CostTracker(),
                store=store,
            )
        )
    assert not llm.calls


def test_compaction_summary_schema_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        CompactionSummary.model_validate({**_summary(), "unexpected": "value"})
