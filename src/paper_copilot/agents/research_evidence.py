from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from paper_copilot.session import ApplicationEvent, RecoveryBase, SessionStore
from paper_copilot.shared.errors import KnowledgeError

__all__ = [
    "ActivePaperSnapshot",
    "PageEvidenceFact",
    "ResearchValidationResult",
    "append_page_evidence",
    "build_validation_continuation",
    "incomplete_research_report",
    "load_page_evidence",
    "render_research_citations",
    "validate_research_report",
]

_NAMESPACE = "research_evidence"
_PAGE_OBSERVED = "page_observed"
_SCHEMA_VERSION = 1
_EXACT_REF_RE = re.compile(
    r"\[(?P<pdf_sha256>[0-9a-f]{64}):page\[(?P<page>[1-9][0-9]*)\]\]"
)
_PAGE_LIKE_REF_RE = re.compile(
    r"\[(?P<paper_id>[^\[\]\s:]+):page\[(?P<page>[0-9]+)\]\]"
)


class ActivePaperSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_locator: str
    pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_count: int = Field(ge=1)
    extractor_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    cache_revision_id: str
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PageEvidenceFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = _SCHEMA_VERSION
    source_tool_call_id: str = Field(min_length=1)
    source_kind: Literal["cached_text_page", "pdf_page_render"]
    pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page: int = Field(ge=1)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extractor_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    cache_revision_id: str | None = None
    region: dict[str, float] | None = None
    render_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ResearchValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    enabled: bool
    passed: bool
    issues: list[str]
    active_paper_count: int = Field(ge=0)
    evidence_covered_paper_count: int = Field(ge=0)
    cited_paper_count: int = Field(ge=0)
    valid_refs: list[dict[str, Any]]
    invalid_refs: list[str]
    missing_evidence_paper_ids: list[str]
    missing_citation_paper_ids: list[str]


def append_page_evidence(
    store: SessionStore,
    *,
    tool_call_id: str,
    trace_attributes: dict[str, Any],
) -> PageEvidenceFact | None:
    raw_page_evidence = trace_attributes.get("page_evidence")
    if raw_page_evidence is None:
        return None
    if not isinstance(raw_page_evidence, dict):
        raise KnowledgeError("tool page_evidence trace attribute must be an object")
    fact = PageEvidenceFact.model_validate(
        {
            **raw_page_evidence,
            "source_tool_call_id": tool_call_id,
        }
    )
    existing = load_page_evidence(store)
    if any(item.source_tool_call_id == tool_call_id for item in existing):
        return fact
    store.append_application_event(
        namespace=_NAMESPACE,
        name=_PAGE_OBSERVED,
        payload=fact.model_dump(mode="json"),
    )
    return fact


def load_page_evidence(store: SessionStore) -> tuple[PageEvidenceFact, ...]:
    events = _research_evidence_events(store, seen_paths=set())
    facts: list[PageEvidenceFact] = []
    call_ids: set[str] = set()
    for event in events:
        if event.name != _PAGE_OBSERVED:
            raise KnowledgeError(f"unknown research_evidence event: {event.name}")
        fact = PageEvidenceFact.model_validate(event.payload)
        if fact.source_tool_call_id in call_ids:
            raise KnowledgeError(
                "duplicate research evidence source tool call id: "
                f"{fact.source_tool_call_id}"
            )
        call_ids.add(fact.source_tool_call_id)
        facts.append(fact)
    return tuple(facts)


def validate_research_report(
    report_markdown: str,
    *,
    active_papers: tuple[ActivePaperSnapshot, ...],
    evidence_facts: tuple[PageEvidenceFact, ...],
    preflight_complete: bool,
    enabled: bool,
    stale_paper_ids: frozenset[str] = frozenset(),
) -> ResearchValidationResult:
    if not enabled:
        return ResearchValidationResult(
            enabled=False,
            passed=True,
            issues=[],
            active_paper_count=len(active_papers),
            evidence_covered_paper_count=0,
            cited_paper_count=0,
            valid_refs=[],
            invalid_refs=[],
            missing_evidence_paper_ids=[],
            missing_citation_paper_ids=[],
        )

    active_by_id = {paper.pdf_sha256: paper for paper in active_papers}
    observed = {
        (fact.pdf_sha256, fact.page)
        for fact in evidence_facts
        if fact.pdf_sha256 not in stale_paper_ids
        if _fact_matches_active_snapshot(fact, active_by_id.get(fact.pdf_sha256))
    }
    evidence_covered_ids = {pdf_sha256 for pdf_sha256, _page in observed}
    missing_evidence = sorted(set(active_by_id) - evidence_covered_ids)

    valid_refs: list[dict[str, Any]] = []
    valid_ref_keys: set[tuple[str, int]] = set()
    for match in _EXACT_REF_RE.finditer(report_markdown):
        key = (match.group("pdf_sha256"), int(match.group("page")))
        if key in observed and key not in valid_ref_keys:
            valid_ref_keys.add(key)
            valid_refs.append(
                {
                    "pdf_sha256": key[0],
                    "page": key[1],
                    "raw": match.group(0),
                }
            )

    invalid_refs: list[str] = []
    seen_invalid: set[str] = set()
    for match in _PAGE_LIKE_REF_RE.finditer(report_markdown):
        raw = match.group(0)
        key = (match.group("paper_id"), int(match.group("page")))
        if (
            len(key[0]) != 64
            or not re.fullmatch(r"[0-9a-f]{64}", key[0])
            or key not in observed
        ) and raw not in seen_invalid:
            seen_invalid.add(raw)
            invalid_refs.append(raw)

    cited_ids = {item["pdf_sha256"] for item in valid_refs}
    missing_citations = sorted(set(active_by_id) - cited_ids)
    issues: list[str] = []
    if not preflight_complete:
        issues.append("active_set_preflight_incomplete")
    if missing_evidence:
        issues.append("active_set_evidence_incomplete")
    if stale_paper_ids:
        issues.append("active_set_stale")
    if any(
        re.fullmatch(r"[0-9a-f]{64}", match.group("paper_id")) is None
        for match in _PAGE_LIKE_REF_RE.finditer(report_markdown)
    ):
        issues.append("citation_id_not_full_sha256")
    if invalid_refs:
        issues.append("citation_not_observed")
    if missing_citations:
        issues.append("citation_paper_coverage_incomplete")

    return ResearchValidationResult(
        enabled=True,
        passed=not issues,
        issues=list(dict.fromkeys(issues)),
        active_paper_count=len(active_papers),
        evidence_covered_paper_count=len(evidence_covered_ids),
        cited_paper_count=len(cited_ids),
        valid_refs=valid_refs,
        invalid_refs=invalid_refs,
        missing_evidence_paper_ids=missing_evidence,
        missing_citation_paper_ids=missing_citations,
    )


def build_validation_continuation(validation: ResearchValidationResult) -> str:
    payload = validation.model_dump(mode="json")
    return (
        "The previous research draft failed deterministic Runtime validation. "
        "Continue the same task and fix every issue. Use read_page or inspect_page "
        "for each missing paper, and cite only exact observed references in the "
        "format [<64-lowercase-pdf-sha256>:page[<positive-page>]]. Do not reuse the "
        "invalid draft as a final answer.\n\n"
        "<research_validation>"
        f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
        "</research_validation>"
    )


def incomplete_research_report(validation: ResearchValidationResult) -> str:
    issues = ", ".join(validation.issues) if validation.issues else "unknown"
    missing_evidence = ", ".join(validation.missing_evidence_paper_ids[:20]) or "none"
    missing_citations = ", ".join(validation.missing_citation_paper_ids[:20]) or "none"
    return (
        "## Incomplete\n\n"
        "Runtime did not accept the final research draft because its page evidence "
        "or citation contract was incomplete.\n\n"
        f"- Validation issues: {issues}\n"
        f"- Papers missing observed page evidence: {missing_evidence}\n"
        f"- Papers missing validated final citations: {missing_citations}"
    )


def render_research_citations(
    report_markdown: str,
    *,
    active_papers: tuple[ActivePaperSnapshot, ...],
    valid_refs: list[dict[str, Any]],
) -> str:
    active_by_id = {paper.pdf_sha256: paper for paper in active_papers}
    rendered = report_markdown
    for reference in valid_refs:
        pdf_sha256 = reference.get("pdf_sha256")
        page = reference.get("page")
        raw = reference.get("raw")
        if (
            not isinstance(pdf_sha256, str)
            or not isinstance(page, int)
            or not isinstance(raw, str)
        ):
            continue
        active_paper = active_by_id.get(pdf_sha256)
        if active_paper is None:
            continue
        paper_name = Path(active_paper.source_locator).stem
        rendered = rendered.replace(raw, f"《{paper_name}》第 {page} 页")
    return rendered


def _fact_matches_active_snapshot(
    fact: PageEvidenceFact,
    active_paper: ActivePaperSnapshot | None,
) -> bool:
    if active_paper is None or fact.page > active_paper.page_count:
        return False
    if fact.source_kind == "pdf_page_render":
        return fact.render_sha256 == fact.artifact_sha256
    return (
        fact.extractor_fingerprint == active_paper.extractor_fingerprint
        and fact.cache_revision_id == active_paper.cache_revision_id
    )


def _research_evidence_events(
    store: SessionStore,
    *,
    seen_paths: set[Path],
) -> list[ApplicationEvent]:
    path = store.path.resolve()
    if path in seen_paths:
        raise KnowledgeError("research evidence recovery chain contains a cycle")
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
            raise KnowledgeError("research evidence recovery source is unavailable")
        inherited = _research_evidence_events(
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
            "research evidence recovery source is outside the session root"
        ) from error
    if len(relative.parts) != 2 or relative.name != "session.jsonl":
        raise KnowledgeError("research evidence recovery source is not a session file")
    return source_path
