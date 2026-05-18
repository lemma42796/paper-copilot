"""ResearchAgent: bounded tool loop for chat-first research tasks."""

from __future__ import annotations

import hashlib
import json
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

from paper_copilot.agents.llm_client import DEFAULT_MODEL
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
from paper_copilot.knowledge.compare import build_compare_payload
from paper_copilot.knowledge.embeddings_store import EmbeddingsStore
from paper_copilot.knowledge.fields_store import FieldsStore, PaperRow, available_fields
from paper_copilot.knowledge.graph_store import graph_path
from paper_copilot.knowledge.hybrid_search import ContainsFilter, SearchResult, search
from paper_copilot.session import SessionStore
from paper_copilot.session.paths import compute_paper_id, paper_dir
from paper_copilot.shared.cost import CostSnapshot, CostTracker, pricing_for_model
from paper_copilot.shared.errors import KnowledgeError

__all__ = [
    "ResearchRun",
    "ResearchTerminationSummary",
    "ResearchToolContext",
    "dispatch_research_tool",
    "research_tools",
    "run_research",
]

_AGENT_NAME = "ResearchAgent"
_MAX_LIST_LIMIT = 20
_MAX_SEARCH_K = 10
_MAX_INSPECT_ITEMS = 8
_MAX_RELATED_K = 10
_RESEARCH_MAX_TOKENS = 3000
_REPORT_FALLBACK = (
    "## Incomplete\n\n"
    "The research loop stopped before producing a final synthesis report. "
    "Review the session trace for the last tool call and termination reason."
)


type QueryEncoder = Callable[[str], np.ndarray]


@dataclass(frozen=True, slots=True)
class ResearchToolContext:
    fields_store: FieldsStore
    embeddings_store: EmbeddingsStore | None = None
    encode_query: QueryEncoder | None = None
    pdf_dir: Path | None = None
    root: Path | None = None
    max_papers: int = 5
    touched_paper_ids: set[str] = dataclass_field(default_factory=set)


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


async def run_research(
    *,
    topic: str,
    llm: LLMClientProtocol,
    context: ResearchToolContext,
    root: Path | None = None,
    max_turns: int = 16,
    max_budget_cny: float = 2.0,
) -> ResearchRun:
    session_id = _research_session_id(topic)
    store = SessionStore.create(
        session_id,
        model=DEFAULT_MODEL,
        agent=_AGENT_NAME,
        root=root,
    )
    initial_user_text = _build_initial_user_text(topic, context)
    store.append_message(role="user", text=initial_user_text)

    cost = CostTracker(pricing=pricing_for_model(DEFAULT_MODEL))
    events: list[Event] = []
    termination_reason = "unknown"
    report_markdown = _REPORT_FALLBACK

    async def dispatch(req: ToolUseRequest) -> ToolResultData:
        return dispatch_research_tool(req, context)

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

    store.append_final_output(
        {
            "topic": topic,
            "termination_reason": termination_reason,
            "report_markdown": report_markdown,
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
                "Check whether a paper has already been read/indexed. If it is "
                "already in the local library, returns session/report paths. If "
                "not, returns needs_user_action instead of reading it."
            ),
            _ReadPaperInput,
        ),
        _tool_schema(
            "search_library",
            (
                "Search the existing local paper library for papers/chunks related "
                "to a query. Returns paper ids, titles, pages, sections, snippets, "
                "and vector distance. Use this when list_papers does not surface "
                "enough candidate papers."
            ),
            _SearchLibraryInput,
        ),
        _tool_schema(
            "inspect_paper",
            (
                "Inspect structured fields for one indexed paper. Use paper_id "
                "values returned by list_papers or search_library. Valid fields "
                "are meta, contributions, methods, experiments, limitations, and "
                "cross_paper_links; omit fields to request the default useful set."
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
    except (KnowledgeError, ValidationError, ValueError) as exc:
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


def _read_paper(args: _ReadPaperInput, context: ResearchToolContext) -> dict[str, Any]:
    paper_id = args.paper_id
    pdf_path = args.pdf_path
    if pdf_path is not None:
        if not pdf_path.exists():
            raise KnowledgeError(f"pdf_path does not exist: {pdf_path}")
        paper_id = compute_paper_id(pdf_path)
    assert paper_id is not None
    _reserve_papers(context, [paper_id])

    row = context.fields_store.get(paper_id)
    pdir = paper_dir(paper_id, context.root)
    report_path = pdir / "report.md"
    session_path = pdir / "session.jsonl"
    if row is not None:
        meta = row.data.get("meta", {})
        return {
            "status": "already_read",
            "paper_id": paper_id,
            "title": meta.get("title", ""),
            "session_path": str(session_path),
            "report_path": str(report_path),
            "session_exists": session_path.exists(),
            "report_exists": report_path.exists(),
            "paper_budget": _paper_budget_payload(context),
        }

    command = (
        f"paper-copilot read {json.dumps(str(pdf_path))}"
        if pdf_path is not None
        else f"paper-copilot read <pdf-for-{paper_id}>"
    )
    return {
        "status": "needs_user_action",
        "paper_id": paper_id,
        "reason": "paper is not indexed; this placeholder tool does not run MainAgent",
        "next_command": command,
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
    )
    return {
        "query": args.query,
        "results": [_search_result_payload(result) for result in results],
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
    return payload


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


def _search_result_payload(result: SearchResult) -> dict[str, Any]:
    chunk = result.best_chunk
    return {
        "paper_id": result.paper_id,
        "title": result.title,
        "year": result.year,
        "distance": chunk.distance,
        "section": chunk.section,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "snippet": _truncate(chunk.text, 500),
    }


def _build_initial_user_text(topic: str, context: ResearchToolContext) -> str:
    pdf_dir = str(context.pdf_dir) if context.pdf_dir is not None else "(not provided)"
    return (
        "You are Paper Copilot ResearchAgent, a bounded planner/controller. "
        "Use the available tools to inspect the local paper library before "
        "answering. Do not invent citations or claim that an unread PDF was "
        "analyzed. If evidence is missing, say exactly what is missing.\n\n"
        f"Research topic: {topic}\n"
        f"PDF directory: {pdf_dir}\n\n"
        f"Paper touch limit: at most {context.max_papers} unique paper_ids may be "
        "inspected or compared in this run. Reusing the same paper_id is allowed; "
        "new paper_ids beyond the limit will return a tool error.\n\n"
        "Tool-use guidance: call list_papers once at the start unless you need a "
        "specific filter, then inspect or compare the selected paper_ids. Use "
        "compare_papers for direct pairwise comparison tasks. Use "
        "find_related_papers only when you need to expand from an already relevant "
        "paper to nearby candidates. Tool inputs must match the JSON schema exactly; "
        "numbers such as year, k, limit, and max_items must be JSON numbers.\n\n"
        "When you have enough information, stop calling tools and write a "
        "concise Markdown report with these sections: Findings, Evidence, "
        "Gaps, Next Steps. Keep every concrete claim tied to a paper_id or "
        "explicitly mark it as a gap. The final answer must be the report itself; "
        "keep the whole report under 900 words. "
        "Do not include process narration such as 'I have inspected...', 'Now I "
        "will...', or 'Let me compile...'."
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
