from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from paper_copilot.session import ApplicationEvent, RecoveryBase, SessionStore
from paper_copilot.session.paths import compute_paper_id
from paper_copilot.shared.errors import KnowledgeError, PdfCacheError
from paper_copilot.shared.pdf_cache import PdfCacheRef, PdfTextCache

__all__ = [
    "PaperSetInput",
    "PaperSetRun",
    "paper_set_tool_description",
    "run_paper_set",
]

_NAMESPACE = "paper_set"
_SCHEMA_VERSION = 1
_PAPER_ID_PATTERN = re.compile(r"^(?:[0-9a-f]{12}|[0-9a-f]{64})$")
_EVIDENCE_REF_PATTERN = re.compile(
    r"^\[(?P<pdf_sha256>[0-9a-f]{64}):page\[(?P<page>[1-9][0-9]*)\]\]$"
)
_READ_CHUNK_BYTES = 1024 * 1024


class PaperSetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["create", "derive", "record_evidence", "status"] = Field(
        description="Lifecycle operation to perform on an immutable paper set."
    )
    result_set_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Existing set ID for record_evidence or status.",
    )
    parent_result_set_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Existing parent set ID for derive.",
    )
    query: str | None = Field(
        default=None,
        min_length=1,
        max_length=2_000,
        description=(
            "Scope description for create, or the narrowed constraint for derive. "
            "This records a fingerprint and does not discover papers; create must "
            "also provide every authorized paper ID. Omit on derive to inherit the "
            "parent fingerprint."
        ),
    )
    paper_ids: list[str] = Field(
        default_factory=list,
        max_length=1_000,
        description=(
            "Authorized paper IDs for create, using full PDF SHA-256 values or "
            "legacy 12-character IDs."
        ),
    )
    included_paper_ids: list[str] = Field(
        default_factory=list,
        max_length=1_000,
        description="Parent members retained by derive.",
    )
    excluded_paper_ids: list[str] = Field(
        default_factory=list,
        max_length=1_000,
        description="Parent members excluded by derive.",
    )
    paper_id: str | None = Field(
        default=None,
        min_length=12,
        max_length=64,
        description="One member of result_set_id for record_evidence.",
    )
    evidence_refs: list[str] = Field(
        default_factory=list,
        max_length=1_000,
        description=(
            "Verified page refs for record_evidence, each formatted as "
            "[<pdf_sha256>:page[<page>]]."
        ),
    )
    reason: str | None = Field(
        default=None,
        min_length=1,
        max_length=2_000,
        description="Required derivation reason when any parent papers are excluded.",
    )

    @field_validator(
        "paper_ids",
        "included_paper_ids",
        "excluded_paper_ids",
    )
    @classmethod
    def _paper_ids_are_valid(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().lower() for value in values]
        if any(_PAPER_ID_PATTERN.fullmatch(value) is None for value in normalized):
            raise ValueError(
                "paper IDs must be a 12-character SHA-1 prefix or full SHA-256"
            )
        if len(normalized) != len(set(normalized)):
            raise ValueError("paper ID lists must not contain duplicates")
        return normalized

    @field_validator("paper_id")
    @classmethod
    def _paper_id_is_valid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if _PAPER_ID_PATTERN.fullmatch(normalized) is None:
            raise ValueError(
                "paper_id must be a 12-character SHA-1 prefix or full SHA-256"
            )
        return normalized

    @field_validator("evidence_refs")
    @classmethod
    def _evidence_refs_are_unique(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("evidence_refs must not contain duplicates")
        return normalized


class _PaperSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    paper_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    legacy_paper_id: str = Field(pattern=r"^[0-9a-f]{12}$")
    source_locator: str = Field(min_length=1, max_length=4_096)
    ingest_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    cache_ref: PdfCacheRef

    @field_validator("source_locator")
    @classmethod
    def _source_locator_is_safe(cls, value: str) -> str:
        stripped = value.strip()
        locator = Path(stripped)
        if (
            not stripped
            or "\x00" in stripped
            or locator.is_absolute()
            or ".." in locator.parts
        ):
            raise ValueError("source_locator must be an authorized relative reference")
        return stripped


class _SetEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = _SCHEMA_VERSION
    result_set_id: str = Field(pattern=r"^ps_[0-9a-f]{16}$")
    parent_result_set_id: str | None = Field(
        default=None,
        pattern=r"^ps_[0-9a-f]{16}$",
    )
    query_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    papers: tuple[_PaperSnapshot, ...] = Field(max_length=1_000)
    excluded_paper_ids: tuple[str, ...] = Field(
        default=(),
        max_length=1_000,
    )
    reason: str | None = Field(default=None, min_length=1, max_length=2_000)


class _EvidenceEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = _SCHEMA_VERSION
    result_set_id: str = Field(pattern=r"^ps_[0-9a-f]{16}$")
    paper_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=1_000)


class _CompleteEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = _SCHEMA_VERSION
    result_set_id: str = Field(pattern=r"^ps_[0-9a-f]{16}$")


@dataclass(slots=True)
class _PaperSetState:
    result_set_id: str
    parent_result_set_id: str | None
    query_fingerprint: str
    papers: tuple[_PaperSnapshot, ...]
    excluded_paper_ids: tuple[str, ...]
    reason: str | None
    evidence_refs: dict[str, list[str]] = field(default_factory=dict)
    complete_event_recorded: bool = False


@dataclass(frozen=True, slots=True)
class PaperSetRun:
    output: dict[str, Any]
    trace_attributes: dict[str, Any]


def paper_set_tool_description() -> str:
    return (
        "Create and derive immutable sets of authorized local papers, record verified "
        "page evidence for each member, and report deterministic coverage across "
        "turns and resume. Creation snapshots the PDF SHA-256 and current text-cache "
        "revision. Evidence refs must use [<pdf_sha256>:page[<page>]] and match that "
        "snapshot. This tool does not search, extract PDFs, run RAG, or generate answers."
    )


async def run_paper_set(
    args: PaperSetInput,
    library_root: Path | None,
    cache_root: Path,
    store: SessionStore,
) -> PaperSetRun:
    root = _resolve_library_root(library_root)
    cache = PdfTextCache(cache_root.expanduser().resolve())
    states = _reconstruct_states(store)

    match args.operation:
        case "create":
            state = await _create_set(args, root, cache, store, states)
        case "derive":
            state = await _derive_set(args, root, cache, store, states)
        case "record_evidence":
            state = await _record_evidence(args, root, cache, store, states)
        case "status":
            _validate_status_args(args)
            result_set_id = _required(args.result_set_id, "result_set_id")
            state = _require_state(states, result_set_id)

    stale_paper_ids = await _stale_paper_ids(state, root, cache)
    output = _status_output(state, stale_paper_ids)
    coverage = output["coverage"]
    return PaperSetRun(
        output=output,
        trace_attributes={
            "paper_set_schema_version": _SCHEMA_VERSION,
            "operation": args.operation,
            "result_set_id": state.result_set_id,
            "parent_result_set_id": state.parent_result_set_id,
            "expected_papers": coverage["expected_papers"],
            "completed_papers": coverage["completed_papers"],
            "coverage_complete": coverage["complete"],
            "stale_paper_count": len(stale_paper_ids),
        },
    )


async def _create_set(
    args: PaperSetInput,
    library_root: Path,
    cache: PdfTextCache,
    store: SessionStore,
    states: dict[str, _PaperSetState],
) -> _PaperSetState:
    _reject_present(args.result_set_id, "result_set_id", "create")
    _reject_present(args.parent_result_set_id, "parent_result_set_id", "create")
    _reject_nonempty(args.included_paper_ids, "included_paper_ids", "create")
    _reject_nonempty(args.excluded_paper_ids, "excluded_paper_ids", "create")
    _reject_present(args.paper_id, "paper_id", "create")
    _reject_nonempty(args.evidence_refs, "evidence_refs", "create")
    _reject_present(args.reason, "reason", "create")
    query = _required(args.query, "query")
    if not args.paper_ids:
        raise KnowledgeError(
            "paper_set create requires at least one paper_id; discover authorized "
            "PDFs with library_exec first"
        )
    papers = await _snapshot_papers(args.paper_ids, library_root, cache)
    result_set_id = _new_result_set_id(states)
    payload = _SetEventPayload(
        result_set_id=result_set_id,
        query_fingerprint=_query_fingerprint(query),
        papers=papers,
    )
    state = _state_from_set_payload(payload)
    stale_paper_ids = await _stale_paper_ids(state, library_root, cache)
    if stale_paper_ids:
        raise KnowledgeError("a paper changed while paper_set create was in progress")
    store.append_application_event(
        namespace=_NAMESPACE,
        name="created",
        payload=payload.model_dump(mode="json"),
    )
    states[result_set_id] = state
    _record_complete_if_needed(state, store, stale_paper_ids=[])
    return state


async def _derive_set(
    args: PaperSetInput,
    library_root: Path,
    cache: PdfTextCache,
    store: SessionStore,
    states: dict[str, _PaperSetState],
) -> _PaperSetState:
    _reject_present(args.result_set_id, "result_set_id", "derive")
    _reject_nonempty(args.paper_ids, "paper_ids", "derive")
    _reject_present(args.paper_id, "paper_id", "derive")
    _reject_nonempty(args.evidence_refs, "evidence_refs", "derive")
    parent_id = _required(args.parent_result_set_id, "parent_result_set_id")
    parent = _require_state(states, parent_id)
    parent_stale = await _stale_paper_ids(parent, library_root, cache)
    if parent_stale:
        raise KnowledgeError(
            "cannot derive from a stale paper_set: " + ", ".join(parent_stale)
        )
    included_ids, excluded_ids = _derive_partition(
        parent,
        args.included_paper_ids,
        args.excluded_paper_ids,
    )
    if excluded_ids and args.reason is None:
        raise KnowledgeError("derive requires reason when papers are excluded")
    paper_by_id = {paper.paper_id: paper for paper in parent.papers}
    papers = tuple(paper_by_id[paper_id] for paper_id in included_ids)
    query_fingerprint = (
        _query_fingerprint(args.query)
        if args.query is not None
        else parent.query_fingerprint
    )
    result_set_id = _new_result_set_id(states)
    payload = _SetEventPayload(
        result_set_id=result_set_id,
        parent_result_set_id=parent.result_set_id,
        query_fingerprint=query_fingerprint,
        papers=papers,
        excluded_paper_ids=tuple(excluded_ids),
        reason=args.reason,
    )
    store.append_application_event(
        namespace=_NAMESPACE,
        name="derived",
        payload=payload.model_dump(mode="json"),
    )
    state = _state_from_set_payload(payload)
    states[result_set_id] = state
    _record_complete_if_needed(state, store, stale_paper_ids=[])
    return state


async def _record_evidence(
    args: PaperSetInput,
    library_root: Path,
    cache: PdfTextCache,
    store: SessionStore,
    states: dict[str, _PaperSetState],
) -> _PaperSetState:
    _reject_present(args.parent_result_set_id, "parent_result_set_id", "record_evidence")
    _reject_present(args.query, "query", "record_evidence")
    _reject_nonempty(args.paper_ids, "paper_ids", "record_evidence")
    _reject_nonempty(args.included_paper_ids, "included_paper_ids", "record_evidence")
    _reject_nonempty(args.excluded_paper_ids, "excluded_paper_ids", "record_evidence")
    _reject_present(args.reason, "reason", "record_evidence")
    result_set_id = _required(args.result_set_id, "result_set_id")
    requested_paper_id = _required(args.paper_id, "paper_id")
    if not args.evidence_refs:
        raise KnowledgeError("record_evidence requires at least one evidence_ref")
    state = _require_state(states, result_set_id)
    paper = _paper_in_set(state, requested_paper_id)
    stale_paper_ids = await _stale_paper_ids(state, library_root, cache)
    if paper.paper_id in stale_paper_ids:
        raise KnowledgeError(f"cannot record evidence for stale paper {paper.paper_id}")
    for evidence_ref in args.evidence_refs:
        await _validate_evidence_ref(evidence_ref, paper, cache)
    existing = set(state.evidence_refs.get(paper.paper_id, []))
    new_refs = tuple(ref for ref in args.evidence_refs if ref not in existing)
    if new_refs:
        payload = _EvidenceEventPayload(
            result_set_id=state.result_set_id,
            paper_id=paper.paper_id,
            evidence_refs=new_refs,
        )
        store.append_application_event(
            namespace=_NAMESPACE,
            name="evidence_recorded",
            payload=payload.model_dump(mode="json"),
        )
        state.evidence_refs.setdefault(paper.paper_id, []).extend(new_refs)
    _record_complete_if_needed(
        state,
        store,
        stale_paper_ids=stale_paper_ids,
    )
    return state


async def _snapshot_papers(
    paper_ids: list[str],
    library_root: Path,
    cache: PdfTextCache,
) -> tuple[_PaperSnapshot, ...]:
    resolved = await asyncio.to_thread(_resolve_requested_papers, library_root, paper_ids)
    snapshots: list[_PaperSnapshot] = []
    for requested_id in paper_ids:
        path, legacy_paper_id, pdf_sha256 = resolved[requested_id]
        lookup = await cache.status(path)
        if lookup.status != "hit" or lookup.cache_ref is None:
            reason = lookup.reason or lookup.status
            raise KnowledgeError(
                f"paper {requested_id} has no compatible text-cache revision: {reason}; "
                "read the paper first with paper read before creating the set"
            )
        if lookup.cache_ref.pdf_sha256 != pdf_sha256:
            raise KnowledgeError(f"paper {requested_id} changed while it was snapshotted")
        snapshots.append(
            _PaperSnapshot(
                paper_id=pdf_sha256,
                legacy_paper_id=legacy_paper_id,
                source_locator=path.relative_to(library_root).as_posix(),
                ingest_revision=pdf_sha256,
                cache_ref=lookup.cache_ref,
            )
        )
    canonical_ids = [snapshot.paper_id for snapshot in snapshots]
    if len(canonical_ids) != len(set(canonical_ids)):
        raise KnowledgeError("paper_ids resolve to duplicate PDF content")
    return tuple(snapshots)


def _resolve_requested_papers(
    library_root: Path,
    paper_ids: list[str],
) -> dict[str, tuple[Path, str, str]]:
    requested = set(paper_ids)
    resolved: dict[str, tuple[Path, str, str]] = {}
    for path in _authorized_pdfs(library_root):
        legacy_paper_id, pdf_sha256 = _paper_hashes(path)
        for candidate in (legacy_paper_id, pdf_sha256):
            if candidate not in requested:
                continue
            if candidate in resolved:
                raise KnowledgeError(
                    f"paper_id {candidate} matched more than one authorized PDF"
                )
            resolved[candidate] = (path, legacy_paper_id, pdf_sha256)
    unresolved = requested - set(resolved)
    if unresolved:
        raise KnowledgeError(
            "no authorized PDF matched paper_ids: " + ", ".join(sorted(unresolved))
        )
    return resolved


def _authorized_pdfs(library_root: Path) -> list[Path]:
    pdfs: list[Path] = []
    for path in sorted(library_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".pdf":
            continue
        resolved = path.resolve()
        try:
            resolved.relative_to(library_root)
        except ValueError:
            continue
        pdfs.append(resolved)
    return pdfs


def _paper_hashes(path: Path) -> tuple[str, str]:
    try:
        pdf_sha256 = _pdf_sha256(path)
        legacy_paper_id = compute_paper_id(path)
    except OSError as error:
        raise KnowledgeError("an authorized PDF could not be read") from error
    return legacy_paper_id, pdf_sha256


def _pdf_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as pdf_file:
        while chunk := pdf_file.read(_READ_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


async def _stale_paper_ids(
    state: _PaperSetState,
    library_root: Path,
    cache: PdfTextCache,
) -> list[str]:
    stale: list[str] = []
    current_paths = await asyncio.to_thread(
        _resolve_snapshot_paths,
        state.papers,
        library_root,
    )
    for paper in state.papers:
        path = current_paths.get(paper.paper_id)
        if path is None:
            stale.append(paper.paper_id)
            continue
        lookup = await cache.status(path)
        if lookup.status != "hit" or lookup.cache_ref != paper.cache_ref:
            stale.append(paper.paper_id)
    return stale


def _resolve_snapshot_paths(
    papers: tuple[_PaperSnapshot, ...],
    library_root: Path,
) -> dict[str, Path]:
    paths_by_revision: dict[str, list[Path]] = {}
    for path in _authorized_pdfs(library_root):
        try:
            pdf_sha256 = _pdf_sha256(path)
        except OSError as error:
            raise KnowledgeError("an authorized PDF could not be read") from error
        paths_by_revision.setdefault(pdf_sha256, []).append(path)
    resolved: dict[str, Path] = {}
    for paper in papers:
        matches = paths_by_revision.get(paper.ingest_revision, [])
        if len(matches) == 1:
            resolved[paper.paper_id] = matches[0]
    return resolved


async def _validate_evidence_ref(
    evidence_ref: str,
    paper: _PaperSnapshot,
    cache: PdfTextCache,
) -> None:
    page = _validate_evidence_ref_shape(evidence_ref, paper)
    try:
        await cache.page(paper.cache_ref, page=page)
    except PdfCacheError as error:
        raise KnowledgeError(f"evidence ref is not available: {evidence_ref}") from error


def _derive_partition(
    parent: _PaperSetState,
    included_requested: list[str],
    excluded_requested: list[str],
) -> tuple[list[str], list[str]]:
    aliases = {
        alias: paper.paper_id
        for paper in parent.papers
        for alias in (paper.paper_id, paper.legacy_paper_id)
    }
    included = _canonicalize_member_ids(included_requested, aliases, "included")
    excluded = _canonicalize_member_ids(excluded_requested, aliases, "excluded")
    parent_ids = [paper.paper_id for paper in parent.papers]
    parent_id_set = set(parent_ids)
    if included and excluded:
        if set(included) & set(excluded):
            raise KnowledgeError("included and excluded paper IDs must be disjoint")
        if set(included) | set(excluded) != parent_id_set:
            raise KnowledgeError(
                "included and excluded paper IDs must partition the parent set"
            )
    elif included:
        excluded = [paper_id for paper_id in parent_ids if paper_id not in set(included)]
    elif excluded:
        included = [paper_id for paper_id in parent_ids if paper_id not in set(excluded)]
    else:
        included = parent_ids
    included_set = set(included)
    excluded_set = set(excluded)
    return (
        [paper_id for paper_id in parent_ids if paper_id in included_set],
        [paper_id for paper_id in parent_ids if paper_id in excluded_set],
    )


def _canonicalize_member_ids(
    requested: list[str],
    aliases: dict[str, str],
    label: str,
) -> list[str]:
    canonical: list[str] = []
    for paper_id in requested:
        resolved = aliases.get(paper_id)
        if resolved is None:
            raise KnowledgeError(f"{label} paper_id is not in the parent set: {paper_id}")
        canonical.append(resolved)
    if len(canonical) != len(set(canonical)):
        raise KnowledgeError(f"{label} paper IDs resolve to duplicate PDF content")
    return canonical


def _paper_in_set(state: _PaperSetState, requested_id: str) -> _PaperSnapshot:
    matches = [
        paper
        for paper in state.papers
        if requested_id in {paper.paper_id, paper.legacy_paper_id}
    ]
    if not matches:
        raise KnowledgeError(
            f"paper_id {requested_id} is not a member of {state.result_set_id}"
        )
    return matches[0]


def _status_output(
    state: _PaperSetState,
    stale_paper_ids: list[str],
) -> dict[str, Any]:
    completed = [
        paper.paper_id
        for paper in state.papers
        if state.evidence_refs.get(paper.paper_id)
    ]
    completed_set = set(completed)
    missing = [
        paper.paper_id
        for paper in state.papers
        if paper.paper_id not in completed_set
    ]
    complete = not missing and not stale_paper_ids
    status = "stale" if stale_paper_ids else "ok" if complete else "incomplete"
    return {
        "status": status,
        "result_set_id": state.result_set_id,
        "parent_result_set_id": state.parent_result_set_id,
        "paper_ids": [paper.paper_id for paper in state.papers],
        "coverage": {
            "expected_papers": len(state.papers),
            "completed_papers": len(completed),
            "missing_paper_ids": missing,
            "complete": complete,
        },
        "stale_paper_ids": stale_paper_ids,
    }


def _record_complete_if_needed(
    state: _PaperSetState,
    store: SessionStore,
    *,
    stale_paper_ids: list[str],
) -> None:
    if state.complete_event_recorded:
        return
    if stale_paper_ids:
        return
    if any(not state.evidence_refs.get(paper.paper_id) for paper in state.papers):
        return
    payload = _CompleteEventPayload(result_set_id=state.result_set_id)
    store.append_application_event(
        namespace=_NAMESPACE,
        name="completed",
        payload=payload.model_dump(mode="json"),
    )
    state.complete_event_recorded = True


def _reconstruct_states(store: SessionStore) -> dict[str, _PaperSetState]:
    states: dict[str, _PaperSetState] = {}
    for event in _paper_set_events(store, seen_paths=set()):
        match event.name:
            case "created" | "derived":
                payload = _SetEventPayload.model_validate(event.payload)
                _validate_set_payload(payload)
                if payload.result_set_id in states:
                    raise KnowledgeError(
                        f"duplicate paper_set id in session: {payload.result_set_id}"
                    )
                if event.name == "created" and payload.parent_result_set_id is not None:
                    raise KnowledgeError("created paper_set must not have a parent")
                if event.name == "created" and (
                    payload.excluded_paper_ids or payload.reason is not None
                ):
                    raise KnowledgeError(
                        "created paper_set must not contain derivation metadata"
                    )
                if event.name == "derived":
                    parent_id = payload.parent_result_set_id
                    parent = _require_state(
                        states,
                        _required(parent_id, "parent_result_set_id"),
                    )
                    _validate_derived_payload(payload, parent)
                states[payload.result_set_id] = _state_from_set_payload(payload)
            case "evidence_recorded":
                payload = _EvidenceEventPayload.model_validate(event.payload)
                state = _require_state(states, payload.result_set_id)
                paper = _paper_in_set(state, payload.paper_id)
                if not payload.evidence_refs:
                    raise KnowledgeError("paper_set evidence event must not be empty")
                refs = state.evidence_refs.setdefault(paper.paper_id, [])
                for evidence_ref in payload.evidence_refs:
                    _validate_evidence_ref_shape(evidence_ref, paper)
                    if evidence_ref not in refs:
                        refs.append(evidence_ref)
            case "completed":
                payload = _CompleteEventPayload.model_validate(event.payload)
                state = _require_state(states, payload.result_set_id)
                if any(not state.evidence_refs.get(paper.paper_id) for paper in state.papers):
                    raise KnowledgeError(
                        f"paper_set completed event precedes full coverage: {state.result_set_id}"
                    )
                state.complete_event_recorded = True
            case _:
                raise KnowledgeError(f"unknown paper_set event: {event.name}")
    return states


def _paper_set_events(
    store: SessionStore,
    *,
    seen_paths: set[Path],
) -> list[ApplicationEvent]:
    path = store.path.resolve()
    if path in seen_paths:
        raise KnowledgeError("paper_set recovery chain contains a cycle")
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
            raise KnowledgeError("paper_set recovery source session is unavailable")
        inherited = _paper_set_events(
            SessionStore(source_path, last_id=""),
            seen_paths=seen_paths,
        )
    current = [
        entry
        for entry in entries
        if isinstance(entry, ApplicationEvent) and entry.namespace == _NAMESPACE
    ]
    return [*inherited, *current]


def _validate_derived_payload(
    payload: _SetEventPayload,
    parent: _PaperSetState,
) -> None:
    parent_papers = {paper.paper_id: paper for paper in parent.papers}
    derived_ids = {paper.paper_id for paper in payload.papers}
    excluded_ids = set(payload.excluded_paper_ids)
    if derived_ids & excluded_ids:
        raise KnowledgeError(
            "derived paper_set event has overlapping members and exclusions"
        )
    if derived_ids | excluded_ids != set(parent_papers):
        raise KnowledgeError("derived paper_set event does not partition its parent")
    for paper in payload.papers:
        if parent_papers.get(paper.paper_id) != paper:
            raise KnowledgeError("derived paper_set changed a parent paper snapshot")
    if excluded_ids and payload.reason is None:
        raise KnowledgeError("derived paper_set exclusions require a reason")


def _validate_set_payload(payload: _SetEventPayload) -> None:
    paper_ids = [paper.paper_id for paper in payload.papers]
    if len(paper_ids) != len(set(paper_ids)):
        raise KnowledgeError("paper_set event contains duplicate paper snapshots")
    for paper in payload.papers:
        if paper.ingest_revision != paper.paper_id:
            raise KnowledgeError("paper_set ingest revision does not match its paper")
        if paper.cache_ref.pdf_sha256 != paper.paper_id:
            raise KnowledgeError("paper_set cache revision does not match its paper")
    excluded_ids = list(payload.excluded_paper_ids)
    if len(excluded_ids) != len(set(excluded_ids)):
        raise KnowledgeError("paper_set event contains duplicate exclusions")
    if any(
        re.fullmatch(r"[0-9a-f]{64}", paper_id) is None
        for paper_id in excluded_ids
    ):
        raise KnowledgeError("paper_set event contains an invalid excluded paper_id")


def _validate_evidence_ref_shape(
    evidence_ref: str,
    paper: _PaperSnapshot,
) -> int:
    match = _EVIDENCE_REF_PATTERN.fullmatch(evidence_ref)
    if match is None:
        raise KnowledgeError(
            "evidence refs must use [<pdf_sha256>:page[<page>]]"
        )
    if match.group("pdf_sha256") != paper.paper_id:
        raise KnowledgeError("evidence ref does not match the target paper revision")
    return int(match.group("page"))


def _state_from_set_payload(payload: _SetEventPayload) -> _PaperSetState:
    return _PaperSetState(
        result_set_id=payload.result_set_id,
        parent_result_set_id=payload.parent_result_set_id,
        query_fingerprint=payload.query_fingerprint,
        papers=payload.papers,
        excluded_paper_ids=payload.excluded_paper_ids,
        reason=payload.reason,
    )


def _resolve_library_root(library_root: Path | None) -> Path:
    if library_root is None:
        raise KnowledgeError("paper_set requires a configured PDF library")
    root = library_root.expanduser().resolve()
    if not root.is_dir():
        raise KnowledgeError("configured PDF library is not available")
    return root


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
            "paper_set recovery source is outside the application session root"
        ) from error
    if len(relative.parts) != 2 or relative.name != "session.jsonl":
        raise KnowledgeError("paper_set recovery source is not a session file")
    return source_path


def _query_fingerprint(query: str) -> str:
    normalized = " ".join(query.split()).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _new_result_set_id(states: dict[str, _PaperSetState]) -> str:
    while True:
        candidate = f"ps_{uuid4().hex[:16]}"
        if candidate not in states:
            return candidate


def _require_state(
    states: dict[str, _PaperSetState],
    result_set_id: str,
) -> _PaperSetState:
    state = states.get(result_set_id)
    if state is None:
        raise KnowledgeError(f"paper_set not found: {result_set_id}")
    return state


def _required(value: str | None, field_name: str) -> str:
    if value is None or not value.strip():
        raise KnowledgeError(f"{field_name} is required")
    return value.strip()


def _reject_present(value: str | None, field_name: str, operation: str) -> None:
    if value is not None:
        raise KnowledgeError(f"{field_name} is not allowed for {operation}")


def _reject_nonempty(values: list[str], field_name: str, operation: str) -> None:
    if values:
        raise KnowledgeError(f"{field_name} is not allowed for {operation}")


def _validate_status_args(args: PaperSetInput) -> None:
    _reject_present(args.parent_result_set_id, "parent_result_set_id", "status")
    _reject_present(args.query, "query", "status")
    _reject_nonempty(args.paper_ids, "paper_ids", "status")
    _reject_nonempty(args.included_paper_ids, "included_paper_ids", "status")
    _reject_nonempty(args.excluded_paper_ids, "excluded_paper_ids", "status")
    _reject_present(args.paper_id, "paper_id", "status")
    _reject_nonempty(args.evidence_refs, "evidence_refs", "status")
    _reject_present(args.reason, "reason", "status")
