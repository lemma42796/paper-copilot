"""DeepAgent: single-pass deep read producing Contribution + Method + Experiment
+ Limitation in one forced tool_choice call.

Like SkimAgent, does NOT go through `agents.loop` — there are no real tools to
execute, the tool is purely a structured-output channel. Input is the full body
text of the paper, concatenated section by section using the `PaperSkeleton`
produced by SkimAgent.

Cost accounting is the caller's job: `run()` returns the raw `LLMResponse`
(wrapped in `DeepRun`), and the caller passes `response.usage` to
`CostTracker.record`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from paper_copilot.agents.llm_client import LLMClient
from paper_copilot.agents.loop import LLMResponse, TextBlock, ToolUseBlock
from paper_copilot.retrieval import SectionText, split_by_sections
from paper_copilot.schemas.paper import (
    Contribution,
    Experiment,
    Limitation,
    Method,
    PaperSkeleton,
)
from paper_copilot.session import SessionStore
from paper_copilot.shared.errors import AgentError
from paper_copilot.shared.jsonschema import inline_refs

__all__ = ["DeepAgent", "DeepResult", "DeepRun"]

_TOOL_NAME = "emit_deep"
_MAX_TOKENS = 3000

_LANGUAGE_INSTRUCTION: dict[str, str] = {
    "en": "",
    "zh": (
        "\n\nOutput language: write Contribution.claim, Method.description, "
        "Method.novelty_vs_prior, and Limitation.description in Simplified "
        "Chinese (简体中文). All other fields stay in English verbatim as "
        "printed in the paper (Method.name, dataset, metric, raw, numeric "
        "values, authors, enum values). Emit only fields the tool schema "
        "defines."
    ),
}

_SYSTEM_PROMPT = (
    "You are a research assistant performing a deep read of an academic paper.\n\n"
    "Task: Given the full body of the paper, extract four lists via the "
    "`emit_deep` tool — contributions, methods, experiments, limitations. "
    "Call the tool exactly once.\n\n"
    "Input format: the paper body is concatenated section by section; each "
    "section is preceded by a '## <section title>' heading. Text was extracted "
    "by a PDF library and may contain layout artifacts — broken hyphens, "
    "out-of-order columns, isolated page-number footers. Work through the "
    "artifacts; do not refuse.\n\n"
    "Extraction guidance:\n"
    "- Contributions: every distinct claim the paper makes. If a paper both "
    "proposes a method and reports an empirical result, emit two separate "
    "entries. Prefer atomic paper-level claims over component-level details.\n"
    "- Methods: every named component the paper introduces OR builds on "
    "(include well-known components the paper explicitly uses).\n"
    "- Experiments: one entry per (dataset, metric) pair. Copy the paper's own "
    "reported numbers exactly as printed — do not round or approximate.\n"
    "- Limitations: prefer those stated by the authors; for inferred ones, "
    "prefix `description` with 'Not stated but likely:'.\n\n"
    "Follow each field description in the tool schema literally — those are "
    "instructions for you, not developer comments. Do not guess numeric values; "
    "use null where the schema allows it."
)


@dataclass(frozen=True, slots=True)
class DeepResult:
    contributions: list[Contribution]
    methods: list[Method]
    experiments: list[Experiment]
    limitations: list[Limitation]


@dataclass(frozen=True, slots=True)
class DeepRun:
    """Envelope returned by `DeepAgent.run`. Exposes enough state for the
    caller to record cost and dump debug context (request + raw response).
    """

    result: DeepResult
    response: LLMResponse
    request_messages: list[dict[str, Any]]
    request_tools: list[dict[str, Any]]


class _DeepToolInput(BaseModel):
    """Private tool-input schema composed of the four field lists.

    Intentionally lives in deep.py (not schemas/) — it's a wire-level contract
    between DeepAgent and the LLM, not a domain type.
    """

    model_config = ConfigDict(extra="forbid")

    contributions: list[Contribution]
    methods: list[Method]
    experiments: list[Experiment]
    limitations: list[Limitation]


class DeepAgent:
    def __init__(self, client: LLMClient, store: SessionStore | None = None) -> None:
        self._client = client
        self._store = store

    async def run(
        self,
        pdf_path: Path,
        skeleton: PaperSkeleton,
        *,
        language: Literal["en", "zh"] = "en",
    ) -> DeepRun:
        sections = await asyncio.to_thread(split_by_sections, pdf_path, skeleton)
        messages = _build_messages(sections)
        tools = [_build_tool()]
        system = _SYSTEM_PROMPT + _LANGUAGE_INSTRUCTION[language]
        if self._store is not None:
            self._store.append_system_message(system)
            self._store.append_message(role="user", text=messages[0]["content"])
        response = await self._client.generate(
            messages=messages,
            tools=tools,
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            system=system,
            max_tokens=_MAX_TOKENS,
        )

        if self._store is not None:
            for block in response.content:
                if isinstance(block, TextBlock):
                    self._store.append_message(role="assistant", text=block.text)
                elif isinstance(block, ToolUseBlock):
                    self._store.append_tool_use(block.id, block.name, block.input)

        tool_use_blocks = [b for b in response.content if isinstance(b, ToolUseBlock)]
        if len(tool_use_blocks) != 1:
            raise AgentError(
                f"expected exactly 1 tool_use block, got {len(tool_use_blocks)} "
                f"(stop_reason={response.stop_reason!r}, "
                f"total content blocks={len(response.content)})"
            )
        block = tool_use_blocks[0]
        if block.name != _TOOL_NAME:
            raise AgentError(f"expected tool_use name={_TOOL_NAME!r}, got {block.name!r}")

        parsed = _DeepToolInput.model_validate(block.input)
        if self._store is not None:
            self._store.append_schema_validation(success=True)

        result = DeepResult(
            contributions=parsed.contributions,
            methods=parsed.methods,
            experiments=parsed.experiments,
            limitations=parsed.limitations,
        )
        return DeepRun(
            result=result,
            response=response,
            request_messages=messages,
            request_tools=tools,
        )


def _build_tool() -> dict[str, Any]:
    return {
        "name": _TOOL_NAME,
        "description": (
            "Emit the paper's contributions, methods, experiments, and limitations "
            "in four parallel lists. Call exactly once per paper."
        ),
        "input_schema": inline_refs(_DeepToolInput.model_json_schema()),
    }


def _build_messages(sections: list[SectionText]) -> list[dict[str, Any]]:
    parts = [f"## {s.title}\n\n{s.text}" for s in sections]
    return [{"role": "user", "content": "\n\n".join(parts)}]
