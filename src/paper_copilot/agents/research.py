"""ResearchAgent: bounded tool loop for chat-first research tasks."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from paper_copilot.agents.llm_client import DEFAULT_MODEL, LLMClient
from paper_copilot.agents.loop import (
    AssistantMessage,
    Event,
    LLMClientProtocol,
    LoopConfig,
    Terminated,
    TextBlock,
    ToolResult,
    ToolResultData,
    ToolUseRequest,
    run_agent_loop,
)
from paper_copilot.agents.read_pipeline import ReadPipelineRun, run_read_pipeline
from paper_copilot.chat.router import ChatRoute, route_chat_request
from paper_copilot.knowledge.compare import build_compare_payload
from paper_copilot.knowledge.embeddings_store import ChunkHit, EmbeddingsStore
from paper_copilot.knowledge.fields_store import FieldsStore, PaperRow, available_fields
from paper_copilot.knowledge.graph_store import graph_path
from paper_copilot.knowledge.hybrid_search import (
    ChunkScore,
    ContainsFilter,
    SearchResult,
    search,
)
from paper_copilot.session import SessionStore
from paper_copilot.session.paths import compute_paper_id, paper_dir
from paper_copilot.shared.cost import CostSnapshot, CostTracker, pricing_for_model
from paper_copilot.shared.embedder import Embedder
from paper_copilot.shared.errors import KnowledgeError, PaperCopilotError

__all__ = [
    "ResearchRun",
    "ResearchTerminationSummary",
    "ResearchToolContext",
    "dispatch_research_tool",
    "dispatch_research_tool_async",
    "research_tools",
    "run_research",
]

_AGENT_NAME = "ResearchAgent"
_MAX_LIST_LIMIT = 20
_MAX_SEARCH_K = 10
_MAX_SEARCH_CHUNKS_PER_PAPER = 5
_MAX_INSPECT_ITEMS = 8
_MAX_RELATED_K = 10
_RESEARCH_MAX_TOKENS = 3000
_REPORT_FALLBACK = (
    "## Incomplete\n\n"
    "The research loop stopped before producing a final synthesis report. "
    "Review the session trace for the last tool call and termination reason."
)
_EVIDENCE_REF_RE = re.compile(
    r"\[(?P<paper_id>[A-Za-z0-9_-]{3,64}):(?P<field>[A-Za-z_][A-Za-z0-9_.\[\]-]*)\]"
)
_CLAIM_BOUNDARY_RE = re.compile(r"(?<=[.!?。！？])\s+")  # noqa: RUF001


type QueryEncoder = Callable[[str], np.ndarray]


@dataclass(frozen=True, slots=True)
class ResearchToolContext:
    fields_store: FieldsStore
    embeddings_store: EmbeddingsStore | None = None
    encode_query: QueryEncoder | None = None
    embedder: Embedder | None = None
    pdf_dir: Path | None = None
    root: Path | None = None
    max_papers: int = 5
    touched_paper_ids: set[str] = dataclass_field(default_factory=set)
    worker_costs: list[CostSnapshot] = dataclass_field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ResearchRun:
    topic: str
    report_markdown: str
    termination_reason: str
    termination_summary: ResearchTerminationSummary
    cost: CostSnapshot
    session_path: Path
    events: tuple[Event, ...]


@dataclass(frozen=True, slots=True)
class ResearchTerminationSummary:
    reason: str
    cost_cny: float
    events_count: int
    paper_budget: dict[str, Any]
    last_tool_error: dict[str, Any] | None


class _ListPapersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: StrictInt | None = Field(
        default=None,
        description="Optional exact publication year filter.",
    )
    limit: StrictInt = Field(default=8, ge=1, le=_MAX_LIST_LIMIT)


class _ListPdfsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contains: str | None = Field(
        default=None,
        description="Optional case-insensitive substring filter on the PDF filename.",
    )
    limit: StrictInt = Field(default=8, ge=1, le=_MAX_LIST_LIMIT)


class _SearchLibraryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    k: StrictInt = Field(default=5, ge=1, le=_MAX_SEARCH_K)
    max_chunks_per_paper: StrictInt = Field(
        default=3,
        ge=1,
        le=_MAX_SEARCH_CHUNKS_PER_PAPER,
    )
    year: StrictInt | None = None
    field: str | None = None
    contains: str | None = None

    @field_validator("field")
    @classmethod
    def _field_is_known(cls, value: str | None) -> str | None:
        if value is not None and value not in available_fields():
            choices = ", ".join(available_fields())
            raise ValueError(f"unknown field {value!r}; choose from {choices}")
        return value


class _InspectPaperInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str = Field(min_length=1)
    fields: list[str] = Field(
        default_factory=lambda: ["meta", "contributions", "methods", "experiments", "limitations"]
    )
    max_items: StrictInt = Field(default=5, ge=1, le=_MAX_INSPECT_ITEMS)

    @field_validator("fields")
    @classmethod
    def _fields_are_known(cls, value: list[str]) -> list[str]:
        allowed = {
            "meta",
            "contributions",
            "methods",
            "experiments",
            "limitations",
            "cross_paper_links",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown fields: {', '.join(unknown)}")
        return value


class _ComparePapersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id_a: str = Field(min_length=1)
    paper_id_b: str = Field(min_length=1)

    @field_validator("paper_id_b")
    @classmethod
    def _papers_differ(cls, value: str, info: Any) -> str:
        if value == info.data.get("paper_id_a"):
            raise ValueError("paper_id_a and paper_id_b must differ")
        return value


class _FindRelatedPapersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str = Field(min_length=1)
    k: StrictInt = Field(default=5, ge=1, le=_MAX_RELATED_K)


class _ReadPaperInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str | None = Field(default=None, min_length=1)
    pdf_path: Path | None = None

    @model_validator(mode="after")
    def _exactly_one_identifier(self) -> _ReadPaperInput:
        if (self.paper_id is None) == (self.pdf_path is None):
            raise ValueError("provide exactly one of paper_id or pdf_path")
        return self


@dataclass(frozen=True, slots=True)
class _ReadTarget:
    paper_id: str
    pdf_path: Path | None


async def run_research(
    *,
    topic: str,
    llm: LLMClientProtocol,
    context: ResearchToolContext,
    root: Path | None = None,
    max_turns: int = 16,
    max_budget_cny: float = 2.0,
    read_llm: LLMClient | None = None,
) -> ResearchRun:
    session_id = _research_session_id(topic)
    store = SessionStore.create(
        session_id,
        model=DEFAULT_MODEL,
        agent=_AGENT_NAME,
        root=root,
    )
    route = route_chat_request(topic)
    initial_user_text = _build_initial_user_text(topic, context, route)
    store.append_message(role="user", text=initial_user_text)

    cost = CostTracker(pricing=pricing_for_model(DEFAULT_MODEL))
    events: list[Event] = []
    termination_reason = "unknown"
    report_markdown = _REPORT_FALLBACK

    async def dispatch(req: ToolUseRequest) -> ToolResultData:
        return await dispatch_research_tool_async(
            req,
            context,
            read_llm=read_llm,
            cost=cost,
            max_budget_cny=max_budget_cny,
        )

    async for event in run_agent_loop(
        messages=[{"role": "user", "content": initial_user_text}],
        tools=research_tools(),
        config=LoopConfig(
            max_turns=max_turns,
            max_budget_cny=max_budget_cny,
            max_tokens=_RESEARCH_MAX_TOKENS,
        ),
        llm=llm,
        dispatch_tool=dispatch,
        cost=cost,
        store=store,
        agent_name=_AGENT_NAME,
        model=DEFAULT_MODEL,
    ):
        events.append(event)
        if isinstance(event, AssistantMessage):
            text = _assistant_text(event)
            if text:
                report_markdown = text
        elif isinstance(event, Terminated):
            termination_reason = event.reason

    termination_summary = _build_termination_summary(
        reason=termination_reason,
        cost=cost.snapshot(),
        events=events,
        context=context,
    )
    evidence_refs = _extract_evidence_refs(report_markdown)
    quality = _quality_summary(report_markdown, evidence_refs)

    store.append_final_output(
        {
            "topic": topic,
            "request_route": route.to_payload(),
            "termination_reason": termination_reason,
            "report_markdown": report_markdown,
            "evidence_refs": evidence_refs,
            "quality": quality,
            "cost": asdict(cost.snapshot()),
            "paper_budget": _paper_budget_payload(context),
            "termination_summary": asdict(termination_summary),
        }
    )
    return ResearchRun(
        topic=topic,
        report_markdown=report_markdown,
        termination_reason=termination_reason,
        termination_summary=termination_summary,
        cost=cost.snapshot(),
        session_path=store.path,
        events=tuple(events),
    )


def research_tools() -> list[dict[str, Any]]:
    return [
        _tool_schema(
            "list_papers",
            (
                "List papers already indexed in the local library. Use before "
                "searching when you need to know what is available. Prefer one "
                "broad call, then inspect returned paper_ids instead of repeating "
                "many year-filtered calls. `year` must be an integer, not a string."
            ),
            _ListPapersInput,
        ),
        _tool_schema(
            "list_pdfs",
            (
                "List PDF files in the provided --pdf-dir. This does not read "
                "or index them; it only reports candidate filenames and paper_ids."
            ),
            _ListPdfsInput,
        ),
        _tool_schema(
            "read_paper",
            (
                "Read and index one local PDF under --pdf-dir, or report an "
                "already-indexed paper. Counts toward max_papers and consumes "
                "the shared run budget. If a paper_id cannot be mapped to a "
                "local PDF, returns needs_user_action instead of inventing. "
                "When status is read or already_read, normally call inspect_paper "
                "next on the same paper_id; it does not consume another paper slot."
            ),
            _ReadPaperInput,
        ),
        _tool_schema(
            "search_library",
            (
                "Search the existing local paper library for papers/chunks related "
                "to a query. Returns paper ids, titles, pages, sections, snippets, "
                "vector distance, and citation-grade evidence refs. Use this when "
                "list_papers does not surface enough candidate papers. Use "
                "max_chunks_per_paper when a task needs multiple snippets from the "
                "same paper."
            ),
            _SearchLibraryInput,
        ),
        _tool_schema(
            "inspect_paper",
            (
                "Inspect structured fields for one indexed paper. Use paper_id "
                "values returned by list_papers or search_library. Valid fields "
                "are meta, contributions, methods, experiments, limitations, and "
                "cross_paper_links; omit fields to request the default useful set. "
                "The response also includes evidence_summary and suggested_citations "
                "for concise final-report grounding, plus recommended_followups "
                "for synthesis-oriented next steps."
            ),
            _InspectPaperInput,
        ),
        _tool_schema(
            "compare_papers",
            (
                "Compare two indexed papers using structured fields. Use this "
                "after identifying two relevant paper_ids to align methods, "
                "experiments, contributions, limitations, and cross-paper links. "
                "Use it for direct A/B comparison tasks; avoid spending turns on "
                "every pair in broad timeline tasks unless the comparison is needed."
            ),
            _ComparePapersInput,
        ),
        _tool_schema(
            "find_related_papers",
            (
                "Find papers already linked to an indexed paper by RelatedAgent. "
                "Reads the local cross-paper link graph and fields index without "
                "calling an LLM. Use this to expand from one relevant paper to "
                "nearby candidates before inspecting or comparing them; do not use "
                "it when the user already named a fixed paper set."
            ),
            _FindRelatedPapersInput,
        ),
    ]


def dispatch_research_tool(req: ToolUseRequest, context: ResearchToolContext) -> ToolResultData:
    try:
        match req.name:
            case "list_papers":
                list_args = _ListPapersInput.model_validate(req.input)
                return _ok(_list_papers(list_args, context))
            case "list_pdfs":
                pdf_args = _ListPdfsInput.model_validate(req.input)
                return _ok(_list_pdfs(pdf_args, context))
            case "read_paper":
                read_args = _ReadPaperInput.model_validate(req.input)
                return _ok(_read_paper(read_args, context))
            case "search_library":
                search_args = _SearchLibraryInput.model_validate(req.input)
                return _ok(_search_library(search_args, context))
            case "inspect_paper":
                inspect_args = _InspectPaperInput.model_validate(req.input)
                return _ok(_inspect_paper(inspect_args, context))
            case "compare_papers":
                compare_args = _ComparePapersInput.model_validate(req.input)
                return _ok(_compare_papers(compare_args, context))
            case "find_related_papers":
                related_args = _FindRelatedPapersInput.model_validate(req.input)
                return _ok(_find_related_papers(related_args, context))
            case _:
                return _err(f"unknown research tool: {req.name}")
    except (PaperCopilotError, ValidationError, ValueError) as exc:
        return _err(str(exc))


async def dispatch_research_tool_async(
    req: ToolUseRequest,
    context: ResearchToolContext,
    *,
    read_llm: LLMClient | None,
    cost: CostTracker,
    max_budget_cny: float,
) -> ToolResultData:
    if req.name != "read_paper":
        return dispatch_research_tool(req, context)
    try:
        read_args = _ReadPaperInput.model_validate(req.input)
        payload = await _read_paper_async(
            read_args,
            context,
            read_llm=read_llm,
            cost=cost,
            max_budget_cny=max_budget_cny,
        )
        return _ok(payload)
    except (PaperCopilotError, ValidationError, ValueError) as exc:
        return _err(str(exc))


def _list_papers(args: _ListPapersInput, context: ResearchToolContext) -> dict[str, Any]:
    rows = context.fields_store.list_all(year=args.year)
    return {
        "count": len(rows),
        "returned": min(len(rows), args.limit),
        "papers": [_paper_brief(row) for row in rows[: args.limit]],
    }


def _list_pdfs(args: _ListPdfsInput, context: ResearchToolContext) -> dict[str, Any]:
    if context.pdf_dir is None:
        raise KnowledgeError("no --pdf-dir was provided for this research run")
    if not context.pdf_dir.exists():
        raise KnowledgeError(f"pdf_dir does not exist: {context.pdf_dir}")
    term = args.contains.lower() if args.contains is not None else None
    pdfs = sorted(p for p in context.pdf_dir.iterdir() if p.suffix.lower() == ".pdf")
    if term is not None:
        pdfs = [p for p in pdfs if term in p.name.lower()]
    rows = [
        {"filename": p.name, "path": str(p), "paper_id": compute_paper_id(p)}
        for p in pdfs[: args.limit]
    ]
    return {"count": len(pdfs), "returned": len(rows), "pdfs": rows}


def _resolve_read_target(args: _ReadPaperInput, context: ResearchToolContext) -> _ReadTarget:
    if args.pdf_path is not None:
        pdf_path = _resolve_pdf_path(args.pdf_path, context)
        return _ReadTarget(paper_id=compute_paper_id(pdf_path), pdf_path=pdf_path)

    assert args.paper_id is not None
    if context.fields_store.get(args.paper_id) is not None:
        return _ReadTarget(paper_id=args.paper_id, pdf_path=None)
    return _ReadTarget(
        paper_id=args.paper_id,
        pdf_path=_find_pdf_by_id(args.paper_id, context),
    )


def _resolve_pdf_path(path: Path, context: ResearchToolContext) -> Path:
    if context.pdf_dir is None:
        raise KnowledgeError("read_paper requires --pdf-dir for pdf_path inputs")
    pdf_dir = context.pdf_dir.resolve()
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = pdf_dir / candidate
    candidate = candidate.resolve()
    if not candidate.exists():
        raise KnowledgeError(f"pdf_path does not exist: {candidate}")
    if candidate.suffix.lower() != ".pdf":
        raise KnowledgeError(f"pdf_path is not a PDF: {candidate}")
    try:
        candidate.relative_to(pdf_dir)
    except ValueError as exc:
        raise KnowledgeError(
            f"read_paper only reads PDFs under --pdf-dir ({pdf_dir}): {candidate}"
        ) from exc
    return candidate


def _find_pdf_by_id(paper_id: str, context: ResearchToolContext) -> Path | None:
    if context.pdf_dir is None or not context.pdf_dir.exists():
        return None
    for path in sorted(context.pdf_dir.iterdir()):
        if path.suffix.lower() != ".pdf":
            continue
        if compute_paper_id(path) == paper_id:
            return path.resolve()
    return None


def _already_read_payload(row: PaperRow, context: ResearchToolContext) -> dict[str, Any]:
    pdir = paper_dir(row.paper_id, context.root)
    report_path = pdir / "report.md"
    session_path = pdir / "session.jsonl"
    meta = row.data.get("meta", {})
    return {
        "status": "already_read",
        "paper_id": row.paper_id,
        "title": meta.get("title", ""),
        "session_path": str(session_path),
        "report_path": str(report_path),
        "session_exists": session_path.exists(),
        "report_exists": report_path.exists(),
        "can_inspect_same_paper": True,
        "recommended_next_tool": _inspect_next_tool(row.paper_id),
        "paper_budget": _paper_budget_payload(context),
    }


def _needs_user_action_payload(
    paper_id: str,
    *,
    reason: str,
    context: ResearchToolContext,
    pdf_path: Path | None = None,
) -> dict[str, Any]:
    command = (
        f"paper-copilot read {json.dumps(str(pdf_path))}"
        if pdf_path is not None
        else f"paper-copilot read <pdf-for-{paper_id}>"
    )
    return {
        "status": "needs_user_action",
        "paper_id": paper_id,
        "reason": reason,
        "next_command": command,
        "can_inspect_same_paper": False,
        "paper_budget": _paper_budget_payload(context),
    }


def _record_read_cost(cost: CostTracker, read_run: ReadPipelineRun) -> None:
    for response in read_run.llm_responses:
        if response.usage is not None:
            cost.record(response.usage)


def _read_paper(args: _ReadPaperInput, context: ResearchToolContext) -> dict[str, Any]:
    target = _resolve_read_target(args, context)
    _reserve_papers(context, [target.paper_id])

    row = context.fields_store.get(target.paper_id)
    if row is not None:
        return _already_read_payload(row, context)

    command = (
        f"paper-copilot read {json.dumps(str(target.pdf_path))}"
        if target.pdf_path is not None
        else f"paper-copilot read <pdf-for-{target.paper_id}>"
    )
    return {
        "status": "needs_user_action",
        "paper_id": target.paper_id,
        "reason": "paper is not indexed; automatic read is unavailable in sync dispatch",
        "next_command": command,
        "can_inspect_same_paper": False,
        "paper_budget": _paper_budget_payload(context),
    }


async def _read_paper_async(
    args: _ReadPaperInput,
    context: ResearchToolContext,
    *,
    read_llm: LLMClient | None,
    cost: CostTracker,
    max_budget_cny: float,
) -> dict[str, Any]:
    target = _resolve_read_target(args, context)
    _reserve_papers(context, [target.paper_id])

    row = context.fields_store.get(target.paper_id)
    if row is not None:
        return _already_read_payload(row, context)
    if target.pdf_path is None:
        return _needs_user_action_payload(
            target.paper_id,
            reason="paper is not indexed and no matching PDF was found under --pdf-dir",
            context=context,
        )
    if read_llm is None:
        return _needs_user_action_payload(
            target.paper_id,
            reason="paper is not indexed and automatic read is not configured",
            context=context,
            pdf_path=target.pdf_path,
        )
    if context.embedder is None or context.embeddings_store is None:
        return _needs_user_action_payload(
            target.paper_id,
            reason="paper is not indexed and embedding index handles are unavailable",
            context=context,
            pdf_path=target.pdf_path,
        )
    if cost.total_cost_cny >= max_budget_cny:
        return {
            "status": "budget_exhausted",
            "paper_id": target.paper_id,
            "reason": "run budget is already exhausted before read_paper",
            "cost_cny": cost.total_cost_cny,
            "max_budget_cny": max_budget_cny,
            "can_inspect_same_paper": False,
            "paper_budget": _paper_budget_payload(context),
        }

    pdir = paper_dir(target.paper_id, context.root)
    if pdir.exists():
        return _needs_user_action_payload(
            target.paper_id,
            reason=(
                "session directory exists but paper is not indexed; rerun "
                "`paper-copilot read --force` manually after checking the old artifact"
            ),
            context=context,
            pdf_path=target.pdf_path,
        )

    read_run = await run_read_pipeline(
        target.pdf_path,
        client=read_llm,
        fields_store=context.fields_store,
        embeddings_store=context.embeddings_store,
        embedder=context.embedder,
        root=context.root,
        language="en",
    )
    _record_read_cost(cost, read_run)
    context.worker_costs.append(read_run.cost)
    return {
        "status": "read",
        "paper_id": read_run.paper_id,
        "title": read_run.title,
        "session_path": str(read_run.session_path),
        "report_path": str(read_run.report_path),
        "chunks_indexed": read_run.chunks_indexed,
        "cost_cny": read_run.cost.cost_cny,
        "budget_exceeded_after_read": cost.total_cost_cny >= max_budget_cny,
        "can_inspect_same_paper": True,
        "recommended_next_tool": _inspect_next_tool(read_run.paper_id),
        "paper_budget": _paper_budget_payload(context),
    }


def _search_library(args: _SearchLibraryInput, context: ResearchToolContext) -> dict[str, Any]:
    if context.embeddings_store is None or context.encode_query is None:
        raise KnowledgeError("embedding index unavailable; run reindex before search_library")
    if (args.field is None) != (args.contains is None):
        raise KnowledgeError("field and contains must be provided together")
    contains_filter = (
        ContainsFilter(field=args.field, term=args.contains)
        if args.field is not None and args.contains is not None
        else None
    )
    results = search(
        context.encode_query(args.query),
        fields_store=context.fields_store,
        embeddings_store=context.embeddings_store,
        k=args.k,
        year=args.year,
        contains=contains_filter,
        max_chunks_per_paper=args.max_chunks_per_paper,
        query_text=args.query,
    )
    ranked = list(enumerate(results, start=1))
    evidence = _search_evidence_list(ranked)
    return {
        "query": args.query,
        "citation_format": "[paper_id:chunks[chunk_id]]",
        "evidence": evidence,
        "results": [
            _search_result_payload(result, paper_rank=rank) for rank, result in ranked
        ],
    }


def _inspect_paper(args: _InspectPaperInput, context: ResearchToolContext) -> dict[str, Any]:
    row = context.fields_store.get(args.paper_id)
    if row is None:
        raise KnowledgeError(f"paper_id not found: {args.paper_id}")
    _reserve_papers(context, [row.paper_id])
    payload: dict[str, Any] = {
        "paper_id": row.paper_id,
        "paper_budget": _paper_budget_payload(context),
    }
    for field in args.fields:
        value = row.data.get(field)
        if isinstance(value, list):
            payload[field] = value[: args.max_items]
        else:
            payload[field] = value
    payload["evidence_summary"] = _evidence_summary(row, max_items=args.max_items)
    payload["suggested_citations"] = _suggested_citations(row, max_items=args.max_items)
    payload["recommended_followups"] = _recommended_followups(row, context)
    return payload


def _recommended_followups(row: PaperRow, context: ResearchToolContext) -> list[dict[str, Any]]:
    followups: list[dict[str, Any]] = []
    if len(context.touched_paper_ids) < context.max_papers:
        followups.append(
            {
                "name": "find_related_papers",
                "input": {"paper_id": row.paper_id, "k": 3},
                "when": (
                    "Use when the task needs synthesis, comparison, or nearby "
                    "papers beyond this one."
                ),
            }
        )
        query = _followup_query(row)
        if query:
            followups.append(
                {
                    "name": "search_library",
                    "input": {"query": query, "k": 3},
                    "when": (
                        "Use when existing links are sparse or you need another "
                        "candidate from the indexed library."
                    ),
                }
            )
    if len(context.touched_paper_ids) >= 2:
        other_ids = sorted(pid for pid in context.touched_paper_ids if pid != row.paper_id)
        if other_ids:
            followups.append(
                {
                    "name": "compare_papers",
                    "input": {"paper_id_a": row.paper_id, "paper_id_b": other_ids[0]},
                    "when": "Use before final synthesis when two relevant papers are touched.",
                }
            )
    return followups


def _followup_query(row: PaperRow) -> str:
    parts: list[str] = []
    title = _row_title(row)
    if title:
        parts.append(title)
    for item in _dict_items(row.data.get("contributions"), 2):
        text = _text_value(item.get("claim"))
        if text:
            parts.append(text)
    for item in _dict_items(row.data.get("methods"), 2):
        name = _text_value(item.get("name"))
        if name:
            parts.append(name)
    return _truncate(". ".join(parts), 360)


def _evidence_summary(row: PaperRow, *, max_items: int) -> dict[str, Any]:
    data = row.data
    meta = data.get("meta", {})
    return {
        "paper_id": row.paper_id,
        "title": _text_value(meta.get("title")),
        "year": meta.get("year"),
        "venue": meta.get("venue"),
        "top_contributions": [
            {
                "field": f"contributions[{i}].claim",
                "text": _truncate(_text_value(item.get("claim")), 240),
                "type": item.get("type"),
                "evidence_type": item.get("evidence_type"),
            }
            for i, item in enumerate(_dict_items(data.get("contributions"), max_items))
        ],
        "top_methods": [
            {
                "field": f"methods[{i}]",
                "name": _truncate(_text_value(item.get("name")), 120),
                "description": _truncate(_text_value(item.get("description")), 240),
                "novelty_vs_prior": _truncate(
                    _text_value(item.get("novelty_vs_prior")), 240
                ),
            }
            for i, item in enumerate(_dict_items(data.get("methods"), max_items))
        ],
        "key_experiments": [
            {
                "field": f"experiments[{i}]",
                "dataset": item.get("dataset"),
                "metric": item.get("metric"),
                "value": item.get("value"),
                "unit": item.get("unit"),
                "comparison_baseline": item.get("comparison_baseline"),
                "raw": _truncate(_text_value(item.get("raw")), 240),
            }
            for i, item in enumerate(_dict_items(data.get("experiments"), max_items))
        ],
        "top_limitations": [
            {
                "field": f"limitations[{i}].description",
                "type": item.get("type"),
                "text": _truncate(_text_value(item.get("description")), 240),
            }
            for i, item in enumerate(_dict_items(data.get("limitations"), max_items))
        ],
    }


def _suggested_citations(row: PaperRow, *, max_items: int) -> list[dict[str, Any]]:
    data = row.data
    citations: list[dict[str, Any]] = []
    meta = data.get("meta", {})
    title = _text_value(meta.get("title"))
    if title:
        citations.append(
            {
                "paper_id": row.paper_id,
                "field": "meta.title",
                "text": title,
            }
        )

    for i, item in enumerate(_dict_items(data.get("contributions"), max_items)):
        text = _text_value(item.get("claim"))
        if text:
            citations.append(
                {
                    "paper_id": row.paper_id,
                    "field": f"contributions[{i}].claim",
                    "text": _truncate(text, 240),
                }
            )

    for i, item in enumerate(_dict_items(data.get("methods"), max_items)):
        name = _text_value(item.get("name"))
        description = _text_value(item.get("description"))
        text = " — ".join(part for part in [name, description] if part)
        if text:
            citations.append(
                {
                    "paper_id": row.paper_id,
                    "field": f"methods[{i}]",
                    "text": _truncate(text, 240),
                }
            )

    for i, item in enumerate(_dict_items(data.get("experiments"), max_items)):
        text = _experiment_text(item)
        if text:
            citations.append(
                {
                    "paper_id": row.paper_id,
                    "field": f"experiments[{i}]",
                    "text": _truncate(text, 240),
                }
            )
    return citations


def _dict_items(value: Any, max_items: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value[:max_items] if isinstance(item, dict)]


def _experiment_text(item: dict[str, Any]) -> str:
    dataset = _text_value(item.get("dataset"))
    metric = _text_value(item.get("metric"))
    baseline = _text_value(item.get("comparison_baseline"))
    value = item.get("value")
    unit = _text_value(item.get("unit"))
    raw = _text_value(item.get("raw"))
    parts: list[str] = []
    if dataset or metric:
        parts.append(" / ".join(part for part in [dataset, metric] if part))
    if value is not None:
        parts.append(f"{value}{unit}")
    if baseline:
        parts.append(f"vs {baseline}")
    if raw:
        parts.append(raw)
    return "; ".join(parts)


def _compare_papers(args: _ComparePapersInput, context: ResearchToolContext) -> dict[str, Any]:
    row_a = context.fields_store.get(args.paper_id_a)
    row_b = context.fields_store.get(args.paper_id_b)
    missing = [
        paper_id
        for paper_id, row in [(args.paper_id_a, row_a), (args.paper_id_b, row_b)]
        if row is None
    ]
    if missing:
        raise KnowledgeError(f"paper_id not found: {', '.join(missing)}")
    assert row_a is not None and row_b is not None
    _reserve_papers(context, [row_a.paper_id, row_b.paper_id])
    payload = build_compare_payload(row_a, row_b)
    payload["paper_budget"] = _paper_budget_payload(context)
    return payload


def _find_related_papers(
    args: _FindRelatedPapersInput,
    context: ResearchToolContext,
) -> dict[str, Any]:
    target = context.fields_store.get(args.paper_id)
    if target is None:
        raise KnowledgeError(f"paper_id not found: {args.paper_id}")

    rows_by_id = {row.paper_id: row for row in context.fields_store.list_all()}
    rows_by_id[target.paper_id] = target
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    for relation in _graph_relation_candidates(target.paper_id, rows_by_id, context.root):
        _add_related_candidate(candidates, seen, relation, rows_by_id)
    for relation in _field_relation_candidates(target, rows_by_id):
        _add_related_candidate(candidates, seen, relation, rows_by_id)

    selected = candidates[: args.k]
    _reserve_papers(
        context,
        [target.paper_id, *(candidate["candidate_paper_id"] for candidate in selected)],
    )
    return {
        "paper_id": target.paper_id,
        "title": _row_title(target),
        "count": len(candidates),
        "returned": len(selected),
        "related_papers": selected,
        "paper_budget": _paper_budget_payload(context),
    }


def _graph_relation_candidates(
    paper_id: str,
    rows_by_id: dict[str, PaperRow],
    root: Path | None,
) -> list[dict[str, Any]]:
    if root is None:
        return []
    relations: list[dict[str, Any]] = []
    for link in _latest_graph_links(root):
        source_id = _text_value(link.get("paper_id"))
        linked_id = _text_value(link.get("related_paper_id"))
        if source_id == paper_id:
            candidate_id = linked_id
            direction = "outgoing"
        elif linked_id == paper_id:
            candidate_id = source_id
            direction = "incoming"
        else:
            continue
        relations.append(
            _relation_payload(
                candidate_id=candidate_id,
                direction=direction,
                source_id=source_id,
                link=link,
                rows_by_id=rows_by_id,
                link_source="graph",
            )
        )
    return relations


def _latest_graph_links(root: Path) -> list[dict[str, Any]]:
    path = graph_path(root)
    if not path.exists():
        return []
    latest_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw_row = json.loads(line)
        if not isinstance(raw_row, dict):
            raise KnowledgeError(f"invalid graph link row in {path}")
        link = cast(dict[str, Any], raw_row)
        source_id = _text_value(link.get("paper_id"))
        linked_id = _text_value(link.get("related_paper_id"))
        if not source_id or not linked_id:
            raise KnowledgeError(f"invalid graph link row in {path}")
        latest_by_pair[(source_id, linked_id)] = link
    return list(reversed(list(latest_by_pair.values())))


def _field_relation_candidates(
    target: PaperRow,
    rows_by_id: dict[str, PaperRow],
) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    for link in _row_links(target):
        candidate_id = _text_value(link.get("related_paper_id"))
        relations.append(
            _relation_payload(
                candidate_id=candidate_id,
                direction="outgoing",
                source_id=target.paper_id,
                link=link,
                rows_by_id=rows_by_id,
                link_source="fields",
            )
        )

    for row in rows_by_id.values():
        if row.paper_id == target.paper_id:
            continue
        for link in _row_links(row):
            if _text_value(link.get("related_paper_id")) != target.paper_id:
                continue
            relations.append(
                _relation_payload(
                    candidate_id=row.paper_id,
                    direction="incoming",
                    source_id=row.paper_id,
                    link=link,
                    rows_by_id=rows_by_id,
                    link_source="fields",
                )
            )
    return relations


def _row_links(row: PaperRow) -> list[dict[str, Any]]:
    links = row.data.get("cross_paper_links", []) or []
    return [link for link in links if isinstance(link, dict)]


def _relation_payload(
    *,
    candidate_id: str,
    direction: str,
    source_id: str,
    link: dict[str, Any],
    rows_by_id: dict[str, PaperRow],
    link_source: str,
) -> dict[str, Any]:
    candidate = rows_by_id.get(candidate_id)
    candidate_meta = candidate.data.get("meta", {}) if candidate is not None else {}
    source = rows_by_id.get(source_id)
    return {
        "candidate_paper_id": candidate_id,
        "candidate_title": candidate_meta.get("title") or _text_value(link.get("related_title")),
        "candidate_year": candidate_meta.get("year", 0),
        "candidate_venue": candidate_meta.get("venue"),
        "indexed": candidate is not None,
        "direction": direction,
        "source_paper_id": source_id,
        "source_title": _row_title(source) if source is not None else "",
        "relation_type": _text_value(link.get("relation_type")),
        "explanation": _text_value(link.get("explanation")),
        "indexed_at": link.get("indexed_at"),
        "link_source": link_source,
    }


def _add_related_candidate(
    candidates: list[dict[str, Any]],
    seen: set[str],
    relation: dict[str, Any],
    rows_by_id: dict[str, PaperRow],
) -> None:
    candidate_id = _text_value(relation.get("candidate_paper_id"))
    if not candidate_id or candidate_id in seen:
        return
    if candidate_id not in rows_by_id:
        relation["indexed"] = False
    candidates.append(relation)
    seen.add(candidate_id)


def _reserve_papers(context: ResearchToolContext, paper_ids: list[str]) -> None:
    if context.max_papers <= 0:
        raise KnowledgeError("max_papers must be positive")
    proposed = set(context.touched_paper_ids)
    proposed.update(paper_ids)
    if len(proposed) > context.max_papers:
        requested = ", ".join(paper_ids)
        touched = ", ".join(sorted(context.touched_paper_ids)) or "(none)"
        raise KnowledgeError(
            f"max_papers exceeded: requested {requested}; "
            f"already touched {len(context.touched_paper_ids)}/{context.max_papers} "
            f"papers: {touched}"
        )
    context.touched_paper_ids.update(paper_ids)


def _paper_budget_payload(context: ResearchToolContext) -> dict[str, Any]:
    return {
        "max_papers": context.max_papers,
        "touched_count": len(context.touched_paper_ids),
        "touched_paper_ids": sorted(context.touched_paper_ids),
        "worker_cost_cny": sum(c.cost_cny for c in context.worker_costs),
    }


def _inspect_next_tool(paper_id: str) -> dict[str, Any]:
    return {
        "name": "inspect_paper",
        "input": {
            "paper_id": paper_id,
            "fields": ["meta", "contributions", "methods", "experiments", "limitations"],
        },
        "note": "Reusing this paper_id does not consume another max_papers slot.",
    }


def _build_termination_summary(
    *,
    reason: str,
    cost: CostSnapshot,
    events: list[Event],
    context: ResearchToolContext,
) -> ResearchTerminationSummary:
    return ResearchTerminationSummary(
        reason=reason,
        cost_cny=cost.cost_cny,
        events_count=len(events),
        paper_budget=_paper_budget_payload(context),
        last_tool_error=_last_tool_error(events),
    )


def _last_tool_error(events: list[Event]) -> dict[str, Any] | None:
    for event in reversed(events):
        if isinstance(event, ToolResult) and event.is_error:
            return {"tool_use_id": event.id, "output": event.output}
    return None


def _extract_evidence_refs(report_markdown: str) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in _EVIDENCE_REF_RE.finditer(report_markdown):
        key = (match.group("paper_id"), match.group("field"))
        if key in seen:
            continue
        seen.add(key)
        refs.append(
            {
                "paper_id": key[0],
                "field": key[1],
                "raw": match.group(0),
            }
        )
    return refs


def _quality_summary(
    report_markdown: str,
    evidence_refs: list[dict[str, str]],
) -> dict[str, Any]:
    findings_text = _quality_claim_section(report_markdown)
    findings_claims = _claim_units(findings_text)
    findings_refs = _extract_evidence_refs(findings_text)
    findings_claim_count = len(findings_claims)
    evidence_ref_count = len(evidence_refs)
    coverage_ratio = (
        min(1.0, evidence_ref_count / findings_claim_count)
        if findings_claim_count
        else 0.0
    )

    return {
        "method": "heuristic_v1",
        "evidence_ref_count": evidence_ref_count,
        "findings_claim_count": findings_claim_count,
        "findings_inline_ref_count": len(findings_refs),
        "claims_without_refs_count": max(0, findings_claim_count - evidence_ref_count),
        "evidence_coverage_ratio": coverage_ratio,
    }


def _quality_claim_section(report_markdown: str) -> str:
    for title in ("Findings", "Proposed Composition", "Idea", "Why It Might Work"):
        section = _markdown_section(report_markdown, title)
        if section:
            return section
    return ""


def _markdown_section(markdown: str, title: str) -> str:
    heading = re.search(
        rf"^##[ \t]+{re.escape(title)}[ \t]*$",
        markdown,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if heading is None:
        return ""

    start = heading.end()
    next_heading = re.search(r"^##[ \t]+", markdown[start:], flags=re.MULTILINE)
    end = start + next_heading.start() if next_heading is not None else len(markdown)
    return markdown[start:end].strip()


def _claim_units(section_text: str) -> list[str]:
    lines = [line.strip() for line in section_text.splitlines()]
    bullets = [line for line in lines if re.match(r"^[-*]\s+\S", line)]
    if bullets:
        return bullets

    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", section_text)
        if paragraph.strip()
    ]
    claims: list[str] = []
    for paragraph in paragraphs:
        claims.extend(
            sentence.strip()
            for sentence in _CLAIM_BOUNDARY_RE.split(paragraph)
            if sentence.strip()
        )
    return claims


def _tool_schema(name: str, description: str, model: type[BaseModel]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "input_schema": model.model_json_schema(),
    }


def _ok(payload: dict[str, Any]) -> ToolResultData:
    return ToolResultData(output=json.dumps(payload, ensure_ascii=False, indent=2))


def _err(message: str) -> ToolResultData:
    return ToolResultData(
        output=json.dumps({"error": message}, ensure_ascii=False, indent=2),
        is_error=True,
    )


def _paper_brief(row: PaperRow) -> dict[str, Any]:
    meta = row.data.get("meta", {})
    return {
        "paper_id": row.paper_id,
        "title": meta.get("title", ""),
        "year": meta.get("year", 0),
        "venue": meta.get("venue"),
        "top_methods": [m.get("name", "") for m in row.data.get("methods", [])[:3]],
        "top_contributions": [c.get("claim", "") for c in row.data.get("contributions", [])[:2]],
    }


def _row_title(row: PaperRow | None) -> str:
    if row is None:
        return ""
    title = row.data.get("meta", {}).get("title", "")
    return title if isinstance(title, str) else ""


def _search_result_payload(result: SearchResult, *, paper_rank: int) -> dict[str, Any]:
    chunk = result.best_chunk
    best_score = _chunk_score(result, chunk.chunk_id)
    evidence_chunks = [
        _search_evidence_payload(
            result,
            chunk=chunk_hit,
            score=_chunk_score(result, chunk_hit.chunk_id),
            rank=chunk_rank,
            paper_rank=paper_rank,
            chunk_rank=chunk_rank,
        )
        for chunk_rank, chunk_hit in enumerate(_result_chunks(result), start=1)
    ]
    best_evidence = evidence_chunks[0]
    return {
        "paper_id": result.paper_id,
        "title": result.title,
        "year": result.year,
        "distance": _vector_distance(best_score, fallback=chunk.distance),
        "bm25_score": best_score.bm25_score if best_score is not None else None,
        "rrf_score": best_score.rrf_score if best_score is not None else None,
        "score": best_evidence["score"],
        "citation_ref": best_evidence["citation_ref"],
        "evidence": best_evidence,
        "evidence_chunks": evidence_chunks,
        "section": chunk.section,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "snippet": _truncate(chunk.text, 500),
    }


def _search_evidence_list(ranked: list[tuple[int, SearchResult]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for paper_rank, result in ranked:
        for chunk_rank, chunk in enumerate(_result_chunks(result), start=1):
            evidence.append(
                _search_evidence_payload(
                    result,
                    chunk=chunk,
                    score=_chunk_score(result, chunk.chunk_id),
                    rank=len(evidence) + 1,
                    paper_rank=paper_rank,
                    chunk_rank=chunk_rank,
                )
            )
    return evidence


def _search_evidence_payload(
    result: SearchResult,
    *,
    chunk: ChunkHit,
    score: ChunkScore | None,
    rank: int,
    paper_rank: int,
    chunk_rank: int,
) -> dict[str, Any]:
    vector_distance = _vector_distance(score, fallback=chunk.distance)
    return {
        "rank": rank,
        "paper_rank": paper_rank,
        "chunk_rank": chunk_rank,
        "paper_id": result.paper_id,
        "title": result.title,
        "year": result.year,
        "source_kind": "pdf_text",
        "chunk_id": chunk.chunk_id,
        "section": chunk.section,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "snippet": _truncate(chunk.text, 500),
        "distance": vector_distance,
        "vector_distance": vector_distance,
        "bm25_score": score.bm25_score if score is not None else None,
        "vector_rank": score.vector_rank if score is not None else None,
        "bm25_rank": score.bm25_rank if score is not None else None,
        "score": (
            score.rrf_score if score is not None else _distance_score(chunk.distance)
        ),
        "score_kind": "rrf" if score is not None else "inverse_distance",
        "citation_ref": f"[{result.paper_id}:chunks[{chunk.chunk_id}]]",
    }


def _chunk_score(result: SearchResult, chunk_id: int) -> ChunkScore | None:
    for score in result.chunk_scores:
        if score.chunk_id == chunk_id:
            return score
    return None


def _vector_distance(score: ChunkScore | None, *, fallback: float) -> float:
    if score is not None and score.vector_distance is not None:
        return score.vector_distance
    return fallback


def _result_chunks(result: SearchResult) -> tuple[ChunkHit, ...]:
    return result.chunks or (result.best_chunk,)


def _distance_score(distance: float) -> float:
    return round(1.0 / (1.0 + max(distance, 0.0)), 6)


def _build_initial_user_text(
    topic: str,
    context: ResearchToolContext,
    route: ChatRoute,
) -> str:
    pdf_dir = str(context.pdf_dir) if context.pdf_dir is not None else "(not provided)"
    return (
        "You are Paper Copilot ResearchAgent, a bounded planner/controller. "
        "Use the available tools to inspect the local paper library before "
        "answering. Do not invent citations or claim that an unread PDF was "
        "analyzed. If evidence is missing, say exactly what is missing.\n\n"
        f"Research topic: {topic}\n"
        f"Request route: {route.kind} ({route.reason})\n"
        f"Output profile: {route.output_profile}\n"
        f"Task profile: {route.task_profile}\n"
        f"PDF directory: {pdf_dir}\n\n"
        f"Paper touch limit: at most {context.max_papers} unique paper_ids may be "
        "inspected or compared in this run. Reusing the same paper_id is allowed; "
        "new paper_ids beyond the limit will return a tool error. A successful "
        "read_paper call touches that paper_id, but you may still inspect_paper "
        "the same paper_id afterward; do not describe the one-paper limit as "
        "exhausted for same-paper follow-up.\n\n"
        "Tool-use guidance: call list_papers once at the start unless you need a "
        "specific filter, then inspect or compare the selected paper_ids. If a "
        "relevant PDF is only present in PDF directory results, call read_paper "
        "with the list_pdfs path before making claims about it, then inspect the "
        "same paper_id before writing the final report so the report can cite "
        "meta, contributions, methods, or experiments. For normal research tasks, "
        "a successful read_paper status of read or already_read should be followed "
        "by inspect_paper on that same paper_id. For synthesis or comparison tasks, "
        "do not stop after one inspected paper when max_papers still allows more: "
        "use inspect_paper recommended_followups, find_related_papers, or "
        "search_library to bring in at least one indexed related paper, then "
        "inspect or compare it before final. Use compare_papers for direct "
        "pairwise comparison tasks. Use find_related_papers when you need to "
        "expand from an already relevant paper to nearby candidates. "
        "Tool inputs must match the JSON schema exactly; "
        "numbers such as year, k, limit, and max_items must be JSON numbers.\n\n"
        f"{_task_profile_guidance(route)}\n\n"
        f"{_final_report_guidance(route)} "
        "Do not include process narration such as 'I have inspected...', 'Now I "
        "will...', or 'Let me compile...'."
    )


def _task_profile_guidance(route: ChatRoute) -> str:
    match route.task_profile:
        case "single_paper_focus":
            return (
                "Task-specific guidance: resolve one target paper, then use "
                "inspect_paper for its structured fields. Do not call "
                "find_related_papers or compare_papers unless the user explicitly "
                "asks for related work or comparison."
            )
        case "fixed_set_compare":
            return (
                "Task-specific guidance: stay inside the papers or methods named "
                "by the user. Resolve and inspect each target, then use "
                "compare_papers for direct pairwise comparison. Do not expand to "
                "extra papers unless a named target cannot be resolved."
            )
        case "evidence_lookup":
            return (
                "Task-specific guidance: prioritize search_library evidence "
                "entries, inspect_paper suggested_citations, and clear hit/miss "
                "evidence. The final answer must separate evidence found from "
                "evidence still missing."
            )
        case "claim_check":
            return (
                "Task-specific guidance: search for supporting and conflicting "
                "evidence before answering. The final answer must label the claim "
                "as supported, partially supported, or unsupported by the local "
                "library."
            )
        case "experiment_extraction":
            return (
                "Task-specific guidance: prioritize methods and experiments fields. "
                "Extract datasets, metrics, baselines, training details, and "
                "ablations when present; mark missing items as gaps."
            )
        case "timeline_synthesis":
            return (
                "Task-specific guidance: inspect multiple relevant papers and use "
                "year/title/method evidence to order the synthesis. Use "
                "compare_papers only for key transitions, not every possible pair."
            )
        case "gap_analysis":
            return (
                "Task-specific guidance: focus on limitations, experiment gaps, "
                "and cross-paper disagreements. Do not switch into proposing a new "
                "model framework unless the user asks for a proposal."
            )
        case "framework_composer":
            return (
                "Task-specific guidance: use a baseline-first path. Identify one "
                "strong baseline and 2-3 compatible modules before writing the "
                "proposal."
            )
        case "topic_survey":
            return (
                "Task-specific guidance: gather a small evidence set with "
                "search_library or find_related_papers, inspect each selected paper, "
                "then synthesize only claims that have evidence references."
            )


def _final_report_guidance(route: ChatRoute) -> str:
    evidence_rule = (
        "Prefer search_library evidence citation_ref values, inspect_paper "
        "evidence_summary and suggested_citations for final-report claims. In "
        "Evidence, each bullet must include at least one bracket reference in "
        "exact format `[paper_id:field]`, for example "
        "`[abc123:chunks[12]]` or `[abc123:contributions[0].claim]`; use "
        "citation_ref from search_library evidence or field names from "
        "suggested_citations / compare_papers output. Keep every concrete claim "
        "tied to a paper_id or explicitly mark it as a gap."
    )
    if route.output_profile == "framework_composer":
        return (
            "Task profile: framework_composer. When you have enough information, "
            "stop calling tools and write a concise Markdown proposal with "
            "these sections: Problem, Baseline, Candidate Modules, "
            "Compatibility, Proposed Composition, Experiment Plan, Risks, "
            "Evidence. This is a baseline-first workflow: first identify one "
            "strong, reproducible baseline paper or method from the local "
            "library, then identify 2-3 compatible modules or tricks from "
            "other papers, then propose a small composition that can be "
            "tested. Baseline should explain why it is a good starting point; "
            "Candidate Modules should name each module, source paper, and "
            "function; Compatibility should say where each module attaches to "
            "the baseline and what might conflict; Proposed Composition should "
            "state the actual modification. Experiment Plan should include "
            "dataset/task, baseline, metric, and ablations when the evidence "
            "supports them. "
            f"{evidence_rule} The final answer must be the proposal itself; "
            "keep the whole report under 900 words."
        )

    return (
        "When you have enough information, stop calling tools and write a "
        "concise Markdown report with these sections: Findings, Evidence, "
        "Gaps, Next Steps. For concrete Findings claims, either include "
        "bracket references inline or mirror the claim in Evidence with "
        f"bracket references. {evidence_rule} The final answer must be the "
        "report itself; keep the whole report under 900 words."
    )


def _assistant_text(event: AssistantMessage) -> str:
    return "\n".join(block.text for block in event.content if isinstance(block, TextBlock)).strip()


def _research_session_id(topic: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    digest = hashlib.sha1(topic.encode("utf-8")).hexdigest()[:8]
    return f"research-{stamp}-{digest}"


def _truncate(text: str, n: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= n else flat[: n - 1].rstrip() + "…"


def _text_value(value: Any) -> str:
    return value if isinstance(value, str) else ""
