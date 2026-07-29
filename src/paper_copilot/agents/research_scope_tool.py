from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from paper_copilot.agents.research_evidence import (
    ActivePaperSnapshot,
    PageEvidenceFact,
)
from paper_copilot.session import ApplicationEvent, RecoveryBase, SessionStore
from paper_copilot.shared.errors import KnowledgeError

__all__ = [
    "ResearchScopeExclusion",
    "UpdateResearchScopeInput",
    "load_research_scope_exclusions",
    "research_scope_context_fragment",
    "run_update_research_scope",
    "update_research_scope_tool_description",
]

_NAMESPACE = "research_scope"
_EXCLUSIONS_UPDATED = "exclusions_updated"
_SCHEMA_VERSION = 1
_EVIDENCE_REF_PATTERN = re.compile(
    r"^\[(?P<pdf_sha256>[0-9a-f]{64}):page\[(?P<page>[1-9][0-9]*)\]\]$"
)


class ResearchScopeExclusion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=2_000)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=100)


class UpdateResearchScopeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exclusions: list[ResearchScopeExclusion] = Field(
        min_length=1,
        max_length=100,
        description=(
            "Papers newly excluded from subsequent turns. Use this only when the "
            "user explicitly asks for a persistent exclusion. Each exclusion must "
            "use a full PDF SHA-256 and page references observed in this turn."
        ),
    )


class _ResearchScopeEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = _SCHEMA_VERSION
    exclusions: tuple[ResearchScopeExclusion, ...] = Field(
        min_length=1,
        max_length=100,
    )


def update_research_scope_tool_description() -> str:
    return (
        "Persist newly excluded papers for later turns in the same conversation. "
        "Call this only when the user explicitly says an exclusion should continue "
        "in subsequent discussion. Each paper must use the full PDF SHA-256 from "
        "research_cache_index and at least one exact page reference already observed "
        "with read_page or inspect_page in this turn. This tool only adds exclusions; "
        "it does not search papers, infer exclusions, remove prior exclusions, or "
        "change the user's files."
    )


def load_research_scope_exclusions(
    store: SessionStore,
) -> tuple[ResearchScopeExclusion, ...]:
    exclusions: list[ResearchScopeExclusion] = []
    excluded_ids: set[str] = set()
    for event in _research_scope_events(store, seen_paths=set()):
        if event.name != _EXCLUSIONS_UPDATED:
            raise KnowledgeError(f"unknown research_scope event: {event.name}")
        payload = _ResearchScopeEventPayload.model_validate(event.payload)
        for exclusion in payload.exclusions:
            if exclusion.pdf_sha256 in excluded_ids:
                raise KnowledgeError(
                    "duplicate research scope exclusion: "
                    f"{exclusion.pdf_sha256}"
                )
            excluded_ids.add(exclusion.pdf_sha256)
            exclusions.append(exclusion)
    return tuple(exclusions)


def research_scope_context_fragment(
    exclusions: tuple[ResearchScopeExclusion, ...],
    active_papers: tuple[ActivePaperSnapshot, ...],
) -> str | None:
    if not exclusions:
        return None
    active_by_id = {paper.pdf_sha256: paper for paper in active_papers}
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "persistent_exclusions": [
            {
                "pdf_sha256": exclusion.pdf_sha256,
                "pdf": (
                    f"library/{active_by_id[exclusion.pdf_sha256].source_locator}"
                    if exclusion.pdf_sha256 in active_by_id
                    else None
                ),
            }
            for exclusion in exclusions
        ],
    }
    return (
        "<research_scope>\n"
        f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n"
        "</research_scope>"
    )


def run_update_research_scope(
    args: UpdateResearchScopeInput,
    *,
    store: SessionStore,
    active_papers: dict[str, ActivePaperSnapshot],
    evidence_facts: tuple[PageEvidenceFact, ...],
    existing_exclusions: dict[str, ResearchScopeExclusion],
) -> dict[str, Any]:
    requested_ids = [exclusion.pdf_sha256 for exclusion in args.exclusions]
    if len(requested_ids) != len(set(requested_ids)):
        raise KnowledgeError("research scope update contains duplicate paper IDs")
    already_excluded = sorted(set(requested_ids) & set(existing_exclusions))
    if already_excluded:
        raise KnowledgeError(
            "papers are already excluded from this conversation: "
            + ", ".join(already_excluded)
        )
    missing_papers = sorted(set(requested_ids) - set(active_papers))
    if missing_papers:
        raise KnowledgeError(
            "research scope exclusions are not in the authorized paper inventory: "
            + ", ".join(missing_papers)
        )

    observed_refs = _observed_evidence_refs(evidence_facts, active_papers)
    for exclusion in args.exclusions:
        if len(exclusion.evidence_refs) != len(set(exclusion.evidence_refs)):
            raise KnowledgeError(
                f"duplicate evidence refs for excluded paper {exclusion.pdf_sha256}"
            )
        for evidence_ref in exclusion.evidence_refs:
            match = _EVIDENCE_REF_PATTERN.fullmatch(evidence_ref)
            if match is None:
                raise KnowledgeError(
                    "research scope evidence refs must use "
                    "[<pdf_sha256>:page[<page>]]"
                )
            if match.group("pdf_sha256") != exclusion.pdf_sha256:
                raise KnowledgeError(
                    "research scope evidence ref does not match its excluded paper"
                )
            if evidence_ref not in observed_refs:
                raise KnowledgeError(
                    "research scope evidence ref was not observed in this turn: "
                    f"{evidence_ref}"
                )

    payload = _ResearchScopeEventPayload(exclusions=tuple(args.exclusions))
    store.append_application_event(
        namespace=_NAMESPACE,
        name=_EXCLUSIONS_UPDATED,
        payload=payload.model_dump(mode="json"),
    )
    for exclusion in args.exclusions:
        existing_exclusions[exclusion.pdf_sha256] = exclusion
    return {
        "status": "ok",
        "newly_excluded_paper_ids": requested_ids,
        "persistent_excluded_paper_ids": list(existing_exclusions),
    }


def _observed_evidence_refs(
    evidence_facts: tuple[PageEvidenceFact, ...],
    active_papers: dict[str, ActivePaperSnapshot],
) -> set[str]:
    observed: set[str] = set()
    for fact in evidence_facts:
        active_paper = active_papers.get(fact.pdf_sha256)
        if active_paper is None or fact.page > active_paper.page_count:
            continue
        if fact.source_kind == "cached_text_page" and (
            fact.extractor_fingerprint != active_paper.extractor_fingerprint
            or fact.cache_revision_id != active_paper.cache_revision_id
        ):
            continue
        observed.add(f"[{fact.pdf_sha256}:page[{fact.page}]]")
    return observed


def _research_scope_events(
    store: SessionStore,
    *,
    seen_paths: set[Path],
) -> list[ApplicationEvent]:
    path = store.path.resolve()
    if path in seen_paths:
        raise KnowledgeError("research scope recovery chain contains a cycle")
    seen_paths.add(path)
    entries = store.read_all()
    recovery_bases = [entry for entry in entries if isinstance(entry, RecoveryBase)]
    if len(recovery_bases) > 1:
        raise KnowledgeError("session contains more than one recovery base")
    inherited: list[ApplicationEvent] = []
    if recovery_bases:
        source_path = _recovery_source_path(
            current_session_path=path,
            source_session_path=recovery_bases[0].source_session_path,
        )
        if not source_path.is_file():
            raise KnowledgeError("research scope recovery source is unavailable")
        inherited = _research_scope_events(
            SessionStore(source_path, last_id=""),
            seen_paths=seen_paths,
        )
    current = [
        entry
        for entry in entries
        if isinstance(entry, ApplicationEvent) and entry.namespace == _NAMESPACE
    ]
    return [*inherited, *current]


def _recovery_source_path(
    *,
    current_session_path: Path,
    source_session_path: str,
) -> Path:
    sessions_root = current_session_path.parent.parent
    source_path = Path(source_session_path).expanduser().resolve()
    try:
        relative = source_path.relative_to(sessions_root)
    except ValueError as error:
        raise KnowledgeError(
            "research scope recovery source is outside the application session root"
        ) from error
    if len(relative.parts) != 2 or relative.name != "session.jsonl":
        raise KnowledgeError("research scope recovery source is not a session file")
    return source_path
