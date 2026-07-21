from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from paper_copilot.agents.context_compaction import (
    compact_history,
    estimate_history_tokens,
)
from paper_copilot.agents.llm_client import DEFAULT_MODEL, LLMClient
from paper_copilot.session import SessionStore
from paper_copilot.shared.cost import CostTracker, pricing_for_model
from paper_copilot.shared.errors import EvalError
from paper_copilot.shared.logging import configure_logging, get_logger

_log = get_logger(__name__)
_TARGET_INPUT_TOKENS = 205_000
_RECENT_HISTORY_TOKENS = 40_000
_MAX_OUTPUT_TOKENS = 8_000
_MAX_COMPACTED_TOKENS = 80_000

_BASELINE_ID = "baseline-a"
_MODULE_IDS = ("module-b", "module-c", "module-d")
_EVIDENCE_REFS = (
    "[baseline-a:chunks[10]]",
    "[module-b:chunks[20]]",
    "[module-c:chunks[30]]",
    "[module-d:chunks[40]]",
)
_REQUIRED_IDENTIFIERS = {
    _BASELINE_ID,
    *_MODULE_IDS,
    *_EVIDENCE_REFS,
    "max_papers=5",
    "budget_cny=2.0",
    "reranker-decision=rejected",
}


async def _run(root: Path) -> None:
    history = _build_history()
    before_tokens = estimate_history_tokens(history)
    session_id = f"context-compaction-eval-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}"
    store = SessionStore.create(
        session_id,
        model=DEFAULT_MODEL,
        agent="ContextCompactionEval",
        root=root,
    )
    cost = CostTracker(pricing=pricing_for_model(DEFAULT_MODEL))
    client = LLMClient(timeout=180.0)

    result = await compact_history(
        client,
        history=history,
        original_request=(
            "Design a grounded research proposal using baseline-a and exactly three "
            "compatible modules. Preserve evidence and clearly separate verified facts "
            "from hypotheses."
        ),
        build_runtime_context=_runtime_context,
        previous_summary=None,
        required_identifiers=set(_REQUIRED_IDENTIFIERS),
        recent_history_budget_tokens=_RECENT_HISTORY_TOKENS,
        max_output_tokens=_MAX_OUTPUT_TOKENS,
        trigger_estimated_input_tokens=before_tokens,
        model=DEFAULT_MODEL,
        cost=cost,
        store=store,
    )
    errors = _fidelity_errors(result.summary.model_dump(mode="json"))
    if result.estimated_after_tokens > _MAX_COMPACTED_TOKENS:
        errors.append(
            f"compacted history has {result.estimated_after_tokens} estimated tokens"
        )
    if errors:
        raise EvalError("context compaction eval failed: " + "; ".join(errors))

    _log.info(
        "eval.context_compaction_passed",
        model=DEFAULT_MODEL,
        before_tokens=before_tokens,
        after_tokens=result.estimated_after_tokens,
        source_message_count=result.source_message_count,
        retained_message_count=result.retained_message_count,
        cost_cny=round(cost.total_cost_cny, 6),
        session_path=str(store.path),
    )


def _build_history() -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": _runtime_context()},
                {"type": "text", "text": "Build the grounded Composer proposal."},
            ],
        }
    ]
    facts = [
        {
            "event": "baseline_selected",
            "decision": "Use baseline-a as the baseline because its limitations are explicit.",
            "paper_id": _BASELINE_ID,
            "evidence_ref": _EVIDENCE_REFS[0],
            "constraints": ["max_papers=5", "budget_cny=2.0"],
        },
        {
            "event": "modules_accepted",
            "decision": "Accept module-b, module-c, and module-d as three distinct modules.",
            "paper_ids": list(_MODULE_IDS),
            "evidence_refs": list(_EVIDENCE_REFS[1:]),
        },
        {
            "event": "failed_attempt",
            "status": "reranker-decision=rejected",
            "reason": "The measured retrieval baseline did not justify a reranker.",
        },
        {
            "event": "remaining_work",
            "open_question": "Whether the three modules remain compatible when combined.",
            "next_action": "Draft the proposal with risks marked as hypotheses.",
        },
    ]
    for index, payload in enumerate(facts, start=1):
        history.extend(_tool_round(index, payload))

    noise_index = len(facts) + 1
    while estimate_history_tokens(history) < _TARGET_INPUT_TOKENS:
        history.extend(
            _tool_round(
                noise_index,
                {
                    "event": "supporting_scan",
                    "paper_id": f"support-{noise_index}",
                    "notes": (
                        "Supporting methodological detail with no new decision. " * 1_200
                    ),
                },
            )
        )
        noise_index += 1
    return history


def _tool_round(index: int, payload: dict[str, Any]) -> list[dict[str, Any]]:
    tool_id = f"eval-tool-{index}"
    return [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": "query_paper",
                    "input": {"query_index": index},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": json.dumps(payload, ensure_ascii=False),
                    "is_error": False,
                },
                {"type": "text", "text": _runtime_context()},
            ],
        },
    ]


def _runtime_context() -> str:
    payload = {
        "latest_state_is_authoritative": True,
        "paper_budget": {
            "max_papers": 5,
            "touched_paper_ids": [_BASELINE_ID, *_MODULE_IDS],
        },
        "llm_budget": {"max_cost_cny": 2.0},
        "composer_plan": {
            "baseline": _BASELINE_ID,
            "accepted_modules": list(_MODULE_IDS),
            "report_ready": True,
        },
    }
    return (
        "<runtime_context>\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n"
        "</runtime_context>"
    )


def _fidelity_errors(summary: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    field_requirements = {
        "decisions": (_BASELINE_ID, *_MODULE_IDS),
        "failed_attempts": ("reranker-decision=rejected",),
        "next_actions": ("Draft the proposal",),
    }
    for field, required_values in field_requirements.items():
        text = json.dumps(summary.get(field, []), ensure_ascii=False)
        for value in required_values:
            if value not in text:
                errors.append(f"{field} omitted {value}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    configure_logging(log_dir=root / "logs", level="INFO")
    asyncio.run(_run(root))


if __name__ == "__main__":
    main()
