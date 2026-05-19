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


def lookup_evidence_chunk(ref: str, *, root: Path | None = None) -> EvidenceChunk:
    match = _CHUNK_REF_RE.match(ref.strip())
    if match is None:
        raise KnowledgeError("only chunk refs like [paper_id:chunks[12]] can be opened")

    home = root if root is not None else default_root()
    paper_id = match.group("paper_id")
    chunk_id = int(match.group("chunk_id"))

    with (
        FieldsStore.open(home / "fields.db") as fields_store,
        EmbeddingsStore.open(home / "embeddings.db", dim=EMBEDDING_DIM) as embeddings_store,
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
