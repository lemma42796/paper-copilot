from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from paper_copilot.session import ApplicationEvent, RecoveryBase, SessionStore
from paper_copilot.shared.errors import KnowledgeError

__all__ = [
    "ActivePaperSnapshot",
    "PageEvidenceFact",
    "append_page_evidence",
    "load_page_evidence",
]

_NAMESPACE = "research_evidence"
_PAGE_OBSERVED = "page_observed"
_SCHEMA_VERSION = 1


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
    source_kind: Literal[
        "cached_text_page",
        "pdf_page_render",
        "pdf_formula_ocr",
    ]
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
