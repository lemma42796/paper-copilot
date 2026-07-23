from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from paper_copilot.knowledge.embeddings_store import EmbeddingsStore
from paper_copilot.knowledge.fields_store import FieldsStore
from paper_copilot.session.paths import default_root
from paper_copilot.shared.embedder import EMBEDDING_DIM
from paper_copilot.shared.errors import KnowledgeError

_CHUNK_REF_RE = re.compile(
    r"^\[(?P<paper_id>[A-Za-z0-9_-]{3,64}):chunks\[(?P<chunk_id>\d+)\]\]$"
)
_FIELD_REF_RE = re.compile(
    r"^\[\s*(?P<paper_id>[A-Za-z0-9_-]{3,64})\s*:\s*"
    r"(?P<field>[A-Za-z_][A-Za-z0-9_]*(?:\[\d+\])?"
    r"(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[\d+\])?)*)\s*\]$"
)
_FIELD_SEGMENT_RE = re.compile(
    r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?:\[(?P<index>\d+)\])?$"
)


@dataclass(frozen=True, slots=True)
class EvidenceChunk:
    citation_ref: str
    paper_id: str
    title: str
    year: int | None
    chunk_id: int
    section: str
    page_start: int
    page_end: int
    text: str


@dataclass(frozen=True, slots=True)
class EvidenceField:
    citation_ref: str
    paper_id: str
    title: str
    year: int | None
    field: str
    text: str


def lookup_evidence_chunk(ref: str, *, root: Path | None = None) -> EvidenceChunk:
    match = _CHUNK_REF_RE.match(ref.strip())
    if match is None:
        raise KnowledgeError("only chunk refs like [paper_id:chunks[12]] can be opened")

    home = root if root is not None else default_root()
    paper_id = match.group("paper_id")
    chunk_id = int(match.group("chunk_id"))

    with (
        FieldsStore.open_read_only(home / "fields.db") as fields_store,
        EmbeddingsStore.open_read_only(
            home / "embeddings.db", dim=EMBEDDING_DIM
        ) as embeddings_store,
    ):
        row = fields_store.get(paper_id)
        chunk = embeddings_store.get_chunk(chunk_id, paper_id=paper_id)
        if chunk is None:
            raise KnowledgeError(f"chunk not found for ref: {ref}")

        meta = row.data.get("meta", {}) if row is not None else {}
        title = meta.get("title")
        year = meta.get("year")
        return EvidenceChunk(
            citation_ref=ref,
            paper_id=paper_id,
            title=title if isinstance(title, str) else "",
            year=year if isinstance(year, int) else None,
            chunk_id=chunk.chunk_id,
            section=chunk.section,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            text=chunk.text,
        )


def lookup_evidence_ref(
    ref: str, *, root: Path | None = None
) -> EvidenceChunk | EvidenceField:
    stripped = ref.strip()
    if _CHUNK_REF_RE.match(stripped) is not None:
        return lookup_evidence_chunk(stripped, root=root)
    return lookup_evidence_field(stripped, root=root)


def lookup_evidence_field(ref: str, *, root: Path | None = None) -> EvidenceField:
    match = _FIELD_REF_RE.match(ref.strip())
    if match is None:
        raise KnowledgeError(
            "only field refs like [paper_id:methods[0]] can be opened"
        )

    home = root if root is not None else default_root()
    paper_id = match.group("paper_id")
    field = match.group("field")

    with FieldsStore.open_read_only(home / "fields.db") as fields_store:
        row = fields_store.get(paper_id)
        if row is None:
            raise KnowledgeError(f"paper not found for ref: {ref}")

        meta = row.data.get("meta", {})
        title = meta.get("title") if isinstance(meta, dict) else None
        year = meta.get("year") if isinstance(meta, dict) else None
        value = _resolve_field_path(row.data, field)
        return EvidenceField(
            citation_ref=ref,
            paper_id=paper_id,
            title=title if isinstance(title, str) else "",
            year=year if isinstance(year, int) else None,
            field=field,
            text=_format_field_value(value),
        )


def _resolve_field_path(data: object, path: str) -> object:
    current = data
    for segment in path.split("."):
        match = _FIELD_SEGMENT_RE.match(segment)
        if match is None:
            raise KnowledgeError(f"unsupported field path segment: {segment}")
        key = match.group("key")
        if not isinstance(current, dict) or key not in current:
            raise KnowledgeError(f"field path not found: {path}")
        current = current[key]
        index_raw = match.group("index")
        if index_raw is not None:
            index = int(index_raw)
            if not isinstance(current, list) or index >= len(current):
                raise KnowledgeError(f"field path not found: {path}")
            current = current[index]
    return current


def _format_field_value(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, int | float | bool) or value is None:
        return str(value)
    if isinstance(value, list):
        return "\n".join(_format_field_value(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(
            f"{key}: {_format_field_value(item)}" for key, item in value.items()
        )
    return str(value)
