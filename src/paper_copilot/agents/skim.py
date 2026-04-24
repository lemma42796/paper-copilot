"""SkimAgent: first-pass read of a paper PDF.

Calls the LLM exactly once with a forced tool_choice that emits a
`PaperMeta` + `PaperSkeleton` pair in one tool_use block. Does NOT go
through `agents.loop` — skimming has no real tools, so the loop's
tool-dispatch machinery would spin for no reason.

Cost accounting is the caller's job: `run()` returns the raw
`LLMResponse` (wrapped in `SkimRun`), and the caller passes
`response.usage` to `CostTracker.record`.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from paper_copilot.agents.llm_client import LLMClient
from paper_copilot.agents.loop import LLMResponse, TextBlock, ToolUseBlock
from paper_copilot.schemas.paper import PaperMeta, PaperSkeleton
from paper_copilot.session import SessionStore
from paper_copilot.shared.errors import AgentError
from paper_copilot.shared.jsonschema import inline_refs
from paper_copilot.shared.logging import get_logger
from paper_copilot.shared.pdf import PdfFrontMatter, load_front_matter

__all__ = ["SkimAgent", "SkimResult", "SkimRun"]

_log = get_logger(__name__)

_TOOL_NAME = "emit_skim"
_FRONT_MATTER_PAGES_WITH_OUTLINE = 3
_FRONT_MATTER_PAGES_WITHOUT_OUTLINE = 8

_SYSTEM_PROMPT = (
    "You are a research assistant performing a first-pass skim of an academic "
    "paper PDF.\n\n"
    "Task: Extract the paper's bibliographic metadata and top-level section "
    "structure, then emit BOTH via the `emit_skim` tool. Call the tool exactly "
    "once.\n\n"
    "Input format: You will receive the first few pages of the paper as text "
    "extracted by a PDF library. The text may contain layout artifacts — broken "
    "hyphens, out-of-order columns, isolated page-number footers. Pages are "
    "separated by '--- page K ---' markers where K is the 1-based page number. "
    "If the PDF has an embedded outline, it will be provided separately as JSON; "
    "prefer the outline as the authoritative signal for section titles, pages, "
    "and depth. If no outline is provided, infer the structure from in-text "
    "headings.\n\n"
    "Output guidance: Do not guess. When a piece of information is not visible "
    "in the provided pages, set the field to null where the schema allows it. "
    "When a section continues past the provided pages, set its page_end to null. "
    "Copy identifiers (arXiv id, author names) exactly as printed — the "
    "per-field descriptions are strict, follow them literally."
)

_ARXIV_RE = re.compile(
    r"^\s*(?:arXiv:)?"
    r"(?P<id>"
    r"[a-z\-]+(?:\.[A-Z]{2})?/\d{7}"
    r"|\d{4}\.\d{4,5}"
    r")"
    r"(?:v\d+)?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SkimResult:
    meta: PaperMeta
    skeleton: PaperSkeleton


@dataclass(frozen=True, slots=True)
class SkimRun:
    """Envelope returned by `SkimAgent.run`. Exposes enough state for the
    caller to record cost and dump debug context (request + raw response).
    """

    result: SkimResult
    response: LLMResponse
    request_messages: list[dict[str, Any]]
    request_tools: list[dict[str, Any]]


class _SkimToolInput(BaseModel):
    """Private tool-input schema composed of PaperMeta + PaperSkeleton.

    Intentionally lives in skim.py (not schemas/) — it's a wire-level
    contract between SkimAgent and the LLM, not a domain type.
    """

    model_config = ConfigDict(extra="forbid")

    meta: PaperMeta
    skeleton: PaperSkeleton


class SkimAgent:
    def __init__(self, client: LLMClient, store: SessionStore | None = None) -> None:
        self._client = client
        self._store = store

    async def run(self, pdf_path: Path) -> SkimRun:
        front_matter = await asyncio.to_thread(
            load_front_matter,
            pdf_path,
            _FRONT_MATTER_PAGES_WITH_OUTLINE,
            _FRONT_MATTER_PAGES_WITHOUT_OUTLINE,
        )
        messages = _build_messages(front_matter)
        tools = [_build_tool()]
        if self._store is not None:
            self._store.append_system_message(_SYSTEM_PROMPT)
            self._store.append_message(role="user", text=messages[0]["content"])
        response = await self._client.generate(
            messages=messages,
            tools=tools,
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            system=_SYSTEM_PROMPT,
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

        parsed = _SkimToolInput.model_validate(block.input)
        if self._store is not None:
            self._store.append_schema_validation(success=True)

        meta = parsed.meta
        if meta.arxiv_id is not None:
            normalized = _normalize_arxiv_id(meta.arxiv_id)
            if normalized != meta.arxiv_id:
                meta = meta.model_copy(update={"arxiv_id": normalized})

        result = SkimResult(meta=meta, skeleton=parsed.skeleton)
        return SkimRun(
            result=result,
            response=response,
            request_messages=messages,
            request_tools=tools,
        )


def _build_tool() -> dict[str, Any]:
    return {
        "name": _TOOL_NAME,
        "description": (
            "Emit the paper's bibliographic metadata and its top-level section "
            "skeleton. Call exactly once per paper."
        ),
        "input_schema": inline_refs(_SkimToolInput.model_json_schema()),
    }


def _build_messages(front_matter: PdfFrontMatter) -> list[dict[str, Any]]:
    parts: list[str] = []
    if front_matter.outline is None:
        parts.append("No embedded outline available; infer section structure from the text below.")
    else:
        outline_json = json.dumps(
            [{"title": e.title, "page": e.page, "depth": e.depth} for e in front_matter.outline],
            indent=2,
            ensure_ascii=False,
        )
        parts.append(
            "Embedded PDF outline (prefer this as authoritative for section "
            "titles, pages, and depth):\n" + outline_json
        )
    parts.append("")
    parts.append(
        f"Total pages in PDF: {front_matter.page_count}. "
        f"Text of the first {front_matter.pages_loaded} pages follows. "
        f"Pages are delimited by '--- page K ---' markers."
    )
    parts.append("")
    parts.append(front_matter.text)
    return [{"role": "user", "content": "\n".join(parts)}]


def _normalize_arxiv_id(raw: str) -> str | None:
    match = _ARXIV_RE.match(raw)
    if match is None:
        _log.warning("arxiv_id.unparseable", raw=raw)
        return None
    return match.group("id")
