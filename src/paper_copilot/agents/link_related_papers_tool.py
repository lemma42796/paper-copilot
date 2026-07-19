"""LinkRelatedPapersTool: cross-paper linker invoked at the end of `read`.

One forced tool_use call. Builds a query vector from the new paper's title +
top contributions, asks `knowledge.hybrid_search` for up to K candidates (with
self filtered out), and lets the LLM pick at most 3 concrete relationships
from a fixed `relation_type` enum. If the library is too small or no strong
candidates remain after filtering, the tool short-circuits to an empty list
and makes no LLM call.

Like the other read tools, it skips `agents.loop` because it has no autonomous
planning loop. It returns the raw response so the caller records usage on its
own CostTracker.

Cache strategy (M9 lesson): system + tools marked, user NOT marked — the
~2K-token candidate payload sits on the boundary where Dashscope qwen-flash
flips to net-negative, so we stay on the safe side.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from paper_copilot.agents.llm_client import DEFAULT_MODEL, LLMClient
from paper_copilot.agents.loop import LLMResponse
from paper_copilot.agents.tool_validation import call_validated_tool
from paper_copilot.knowledge.embeddings_store import EmbeddingsStore
from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.knowledge.hybrid_search import SearchResult, search
from paper_copilot.schemas.paper import CrossPaperLink, Paper
from paper_copilot.session import SessionStore
from paper_copilot.shared.cache import cached_system, mark_tools_cached
from paper_copilot.shared.embedding_cache import EmbeddingEncoder
from paper_copilot.shared.jsonschema import inline_refs
from paper_copilot.shared.logging import get_logger

__all__ = ["LinkRelatedPapersTool", "LinkRelatedPapersToolRun", "RelatedResult"]

_log = get_logger(__name__)

_TOOL_NAME = "emit_related_links"
_COMPONENT_NAME = "LinkRelatedPapersTool"
_CANDIDATE_K = 10
_MIN_CANDIDATES_AFTER_SELF_FILTER = 2
_MAX_LINKS = 3
_NEW_PAPER_TOP_CONTRIBUTIONS = 3
_NEW_PAPER_TOP_METHODS = 4
_CANDIDATE_TOP_CONTRIBUTIONS = 2
_CANDIDATE_TOP_METHODS = 3

# Relation types where the new paper must be at least as recent as the
# candidate. Symmetric relations (`shares_method`, `contrasts_with`) carry no
# temporal direction and are exempt. Empirical signal: M12 first run on
# Bahdanau (2015) had the model emit `builds_on` toward Transformer (2017) —
# a temporal impossibility no amount of prompt anchoring fixed in M8-style
# tests, so we enforce it post-hoc.
_DIRECTIONAL_RELATIONS: frozenset[str] = frozenset(
    {"builds_on", "compares_against", "applies_in_different_domain"}
)

_SYSTEM_PROMPT = (
    "You are a research assistant linking a newly-read paper to the existing "
    "local library. You will receive one new paper and up to 10 candidates "
    "already in the library, ranked by vector similarity.\n\n"
    "Task: From the candidates, pick those that have a CONCRETE, mechanism-"
    "level relationship with the new paper. Emit them via the "
    "`emit_related_links` tool, at most 3 links, sorted most-relevant first. "
    "Call the tool exactly once, even when returning zero links.\n\n"
    "Quality bar: Low recall is better than a false link. If a candidate only "
    "shares a topic area or a benchmark without a shared mechanism, do not "
    "link it. Similarity rank is a suggestion, not a guarantee — a rank-1 "
    "candidate with no mechanism in common should be dropped.\n\n"
    "For each kept candidate, pick the single closest `relation_type` from "
    "the enum; if none fit cleanly, drop the candidate entirely. Use the "
    "`related_paper_id` and `related_title` from the candidate list verbatim."
)


class _RelatedToolInput(BaseModel):
    """Wire-level tool-input schema. Private to LinkRelatedPapersTool."""

    model_config = ConfigDict(extra="forbid")

    links: list[CrossPaperLink] = Field(
        description=(
            "Up to 3 cross-paper links, sorted most-relevant first. Empty list "
            "is valid and preferred over forcing a weak link. Each link's "
            "`related_paper_id` must match one of the provided candidates."
        ),
        max_length=_MAX_LINKS,
    )


@dataclass(frozen=True, slots=True)
class RelatedResult:
    links: list[CrossPaperLink]


@dataclass(frozen=True, slots=True)
class LinkRelatedPapersToolRun:
    result: RelatedResult
    response: LLMResponse | None
    responses: tuple[LLMResponse, ...] = ()
    request_messages: list[dict[str, Any]] = field(default_factory=list)
    request_tools: list[dict[str, Any]] = field(default_factory=list)
    skipped_reason: str | None = None


class LinkRelatedPapersTool:
    def __init__(self, client: LLMClient, store: SessionStore | None = None) -> None:
        self._client = client
        self._store = store

    async def run(
        self,
        new_paper: Paper,
        new_paper_id: str,
        *,
        embedder: EmbeddingEncoder,
        fields_store: FieldsStore,
        embeddings_store: EmbeddingsStore,
    ) -> LinkRelatedPapersToolRun:
        query_text = _build_query_text(new_paper)
        query_vec = embedder.encode([query_text])[0]

        raw_hits = search(
            query_vec,
            fields_store=fields_store,
            embeddings_store=embeddings_store,
            k=_CANDIDATE_K + 1,  # +1 in case self is the nearest neighbor
        )
        candidates = [h for h in raw_hits if h.paper_id != new_paper_id][:_CANDIDATE_K]

        if len(candidates) < _MIN_CANDIDATES_AFTER_SELF_FILTER:
            reason = f"library_too_small (got {len(candidates)} candidates after self-filter)"
            _log.info("related.skipped", reason=reason, new_paper_id=new_paper_id)
            return LinkRelatedPapersToolRun(
                result=RelatedResult(links=[]),
                response=None,
                skipped_reason=reason,
            )

        user_text = _build_user_text(new_paper, candidates)
        messages = [{"role": "user", "content": user_text}]
        tools = mark_tools_cached([_build_tool()])

        if self._store is not None:
            self._store.append_system_message(_SYSTEM_PROMPT)
            self._store.append_message(role="user", text=user_text)

        validated = await call_validated_tool(
            self._client,
            component_name=_COMPONENT_NAME,
            model=DEFAULT_MODEL,
            messages=messages,
            tools=tools,
            tool_name=_TOOL_NAME,
            tool_input_model=_RelatedToolInput,
            store=self._store,
            system=cached_system(_SYSTEM_PROMPT),
        )
        parsed = validated.parsed

        links = _validate_links(
            parsed.links,
            candidates,
            new_paper_id=new_paper_id,
            new_paper_year=new_paper.meta.year,
        )

        return LinkRelatedPapersToolRun(
            result=RelatedResult(links=links),
            response=validated.response,
            responses=validated.responses,
            request_messages=messages,
            request_tools=tools,
        )


def _build_tool() -> dict[str, Any]:
    return {
        "name": _TOOL_NAME,
        "description": (
            "Emit up to 3 cross-paper links between the new paper and "
            "candidates from the local library. Call exactly once per read."
        ),
        "input_schema": inline_refs(_RelatedToolInput.model_json_schema()),
    }


def _build_query_text(new_paper: Paper) -> str:
    parts: list[str] = [new_paper.meta.title]
    for c in new_paper.contributions[:_NEW_PAPER_TOP_CONTRIBUTIONS]:
        parts.append(c.claim)
    for m in new_paper.methods[:_NEW_PAPER_TOP_METHODS]:
        parts.append(m.name)
    return ". ".join(parts)


def _build_user_text(new_paper: Paper, candidates: list[SearchResult]) -> str:
    lines: list[str] = []
    lines.append("## New paper")
    lines.append(f"Title: {new_paper.meta.title}")
    if new_paper.meta.year:
        lines.append(f"Year: {new_paper.meta.year}")
    if new_paper.contributions:
        lines.append("Top contributions:")
        for contribution in new_paper.contributions[:_NEW_PAPER_TOP_CONTRIBUTIONS]:
            lines.append(f"- {contribution.claim}")
    if new_paper.methods:
        method_names = [m.name for m in new_paper.methods[:_NEW_PAPER_TOP_METHODS]]
        lines.append(f"Key methods: {', '.join(method_names)}")

    lines.append("")
    lines.append(f"## Candidates (ranked by vector similarity, {len(candidates)} total)")
    for rank, candidate in enumerate(candidates, start=1):
        lines.append("")
        lines.append(
            f"[{rank}] related_paper_id={candidate.paper_id} "
            f"distance={candidate.best_chunk.distance:.3f}"
        )
        lines.append(f"related_title: {candidate.title}")
        if candidate.year:
            lines.append(f"Year: {candidate.year}")
        cand_contribs = candidate.paper_data.get("contributions", []) or []
        if cand_contribs:
            lines.append("Top contributions:")
            for contrib in cand_contribs[:_CANDIDATE_TOP_CONTRIBUTIONS]:
                claim = contrib.get("claim", "")
                if claim:
                    lines.append(f"- {claim}")
        cand_methods = candidate.paper_data.get("methods", []) or []
        if cand_methods:
            names = [
                m.get("name", "") for m in cand_methods[:_CANDIDATE_TOP_METHODS] if m.get("name")
            ]
            if names:
                lines.append(f"Key methods: {', '.join(names)}")

    return "\n".join(lines)


def _validate_links(
    links: list[CrossPaperLink],
    candidates: list[SearchResult],
    *,
    new_paper_id: str,
    new_paper_year: int,
) -> list[CrossPaperLink]:
    candidate_by_id = {c.paper_id: c for c in candidates}
    kept: list[CrossPaperLink] = []
    for link in links:
        if link.related_paper_id == new_paper_id:
            _log.warning(
                "related.link_points_to_self_dropped",
                new_paper_id=new_paper_id,
            )
            continue
        candidate = candidate_by_id.get(link.related_paper_id)
        if candidate is None:
            _log.warning(
                "related.link_not_in_candidates_dropped",
                new_paper_id=new_paper_id,
                related_paper_id=link.related_paper_id,
            )
            continue
        if (
            link.relation_type in _DIRECTIONAL_RELATIONS
            and candidate.year > new_paper_year > 0
            and candidate.year > 0
        ):
            _log.warning(
                "related.link_dropped_temporal_direction",
                new_paper_id=new_paper_id,
                new_paper_year=new_paper_year,
                related_paper_id=link.related_paper_id,
                candidate_year=candidate.year,
                relation_type=link.relation_type,
            )
            continue
        kept.append(link)
    return kept
