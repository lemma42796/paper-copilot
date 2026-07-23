from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from paper_copilot.chat.evidence import (
    EvidenceChunk,
    EvidenceField,
    lookup_evidence_ref,
)
from paper_copilot.knowledge.compare import build_multi_compare_payload
from paper_copilot.knowledge.embeddings_store import EmbeddingsStore
from paper_copilot.knowledge.fields_store import FieldsStore, PaperRow
from paper_copilot.knowledge.hybrid_search import SearchResult, search
from paper_copilot.knowledge.meta import read_meta, require_match
from paper_copilot.session.paths import default_pdf_dir, default_root
from paper_copilot.shared.embedder import EMBEDDING_DIM, MODEL_NAME, Embedder
from paper_copilot.shared.env import load_env
from paper_copilot.shared.errors import KnowledgeError

CompareAspect = Literal["contributions", "methods", "experiments", "limitations"]

_PAPER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,64}$")
_MAX_LIST_LIMIT = 50
_MAX_SEARCH_LIMIT = 10
_MAX_COMPARE_PAPERS = 5
_MAX_PAPER_ITEMS = 5
_MAX_SUMMARY_TEXT = 600
_MAX_SEARCH_TEXT = 1_200
_MAX_EVIDENCE_TEXT = 4_000
_COMPARE_ASPECTS: tuple[CompareAspect, ...] = (
    "contributions",
    "methods",
    "experiments",
    "limitations",
)


@dataclass(frozen=True, slots=True)
class MCPReadService:
    root: Path
    pdf_dir: Path | None

    @classmethod
    def from_environment(
        cls,
        *,
        root: Path | None = None,
        pdf_dir: Path | None = None,
    ) -> MCPReadService:
        resolved_root = (
            root if root is not None else default_root()
        ).expanduser().resolve()
        configured_pdf_dir = pdf_dir if pdf_dir is not None else default_pdf_dir()
        resolved_pdf_dir = (
            configured_pdf_dir.expanduser().resolve()
            if configured_pdf_dir is not None
            else None
        )
        return cls(root=resolved_root, pdf_dir=resolved_pdf_dir)

    def library_status(self) -> dict[str, Any]:
        fields_db = self.root / "fields.db"
        embeddings_db = self.root / "embeddings.db"
        meta = read_meta(self.root / "embeddings_meta.json")
        indexed_papers = 0
        indexed_chunks = 0
        if fields_db.is_file():
            with FieldsStore.open_read_only(fields_db) as fields_store:
                indexed_papers = fields_store.count()
        if embeddings_db.is_file():
            with EmbeddingsStore.open_read_only(
                embeddings_db, dim=EMBEDDING_DIM
            ) as embeddings_store:
                indexed_chunks = embeddings_store.count_chunks()
        pdf_dir_available = self.pdf_dir is not None and self.pdf_dir.is_dir()
        return {
            "status": "ok",
            "data_home_configured": self.root.is_dir(),
            "fields_index_available": fields_db.is_file(),
            "embeddings_index_available": embeddings_db.is_file(),
            "indexed_papers": indexed_papers,
            "indexed_chunks": indexed_chunks,
            "pdf_library_configured": self.pdf_dir is not None,
            "pdf_library_available": pdf_dir_available,
            "local_pdf_count": (
                _count_library_pdfs(self.pdf_dir) if pdf_dir_available else 0
            ),
            "embedding_index": asdict(meta) if meta is not None else None,
            "read_only": True,
        }

    def list_papers(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        year: int | None = None,
    ) -> dict[str, Any]:
        _require_range("limit", limit, minimum=1, maximum=_MAX_LIST_LIMIT)
        if offset < 0:
            raise KnowledgeError("offset must be non-negative")
        with self._fields_store() as fields_store:
            rows = fields_store.list_all(year=year)
        selected = rows[offset : offset + limit]
        return {
            "status": "ok",
            "returned": len(selected),
            "total": len(rows),
            "offset": offset,
            "limit": limit,
            "year": year,
            "papers": [_paper_brief(row) for row in selected],
        }

    def search_papers(
        self,
        query: str,
        *,
        limit: int = 5,
        year: int | None = None,
    ) -> dict[str, Any]:
        query = query.strip()
        if not query:
            raise KnowledgeError("query must be non-empty")
        if len(query) > 1_000:
            raise KnowledgeError("query must contain at most 1000 characters")
        _require_range("limit", limit, minimum=1, maximum=_MAX_SEARCH_LIMIT)
        has_embedding_key = _embedding_key_available()
        if has_embedding_key:
            require_match(
                self.root / "embeddings_meta.json",
                embedding_model=MODEL_NAME,
                embedding_dim=EMBEDDING_DIM,
            )
            query_vector = Embedder().encode([query])[0]
        else:
            query_vector = None
        with (
            self._fields_store() as fields_store,
            EmbeddingsStore.open_read_only(
                self.root / "embeddings.db", dim=EMBEDDING_DIM
            ) as embeddings_store,
        ):
            matches = search(
                query_vector,
                fields_store=fields_store,
                embeddings_store=embeddings_store,
                k=limit,
                year=year,
                max_chunks_per_paper=2,
                evidence_pool_per_paper=20,
                query_text=query,
            )
        return {
            "status": "ok" if matches else "no_matches",
            "query": query,
            "year": year,
            "returned": len(matches),
            "retrieval_mode": "hybrid" if has_embedding_key else "lexical",
            "query_sent_to_embedding_provider": has_embedding_key,
            "papers": [
                _search_result_payload(match, rank=rank)
                for rank, match in enumerate(matches, start=1)
            ],
        }

    def get_paper(self, paper_id: str) -> dict[str, Any]:
        _validate_paper_id(paper_id)
        with self._fields_store() as fields_store:
            row = fields_store.get(paper_id)
        if row is None:
            raise KnowledgeError(f"indexed paper not found: {paper_id}")
        return {
            "status": "ok",
            "paper_id": row.paper_id,
            "indexed_at": row.indexed_at,
            "paper": {
                "meta": _bounded_value(row.data.get("meta", {})),
                "contributions": _bounded_collection(row.data, "contributions"),
                "methods": _bounded_collection(row.data, "methods"),
                "experiments": _bounded_collection(row.data, "experiments"),
                "limitations": _bounded_collection(row.data, "limitations"),
                "cross_paper_links": _bounded_collection(
                    row.data, "cross_paper_links"
                ),
            },
            "item_limit_per_field": _MAX_PAPER_ITEMS,
        }

    def inspect_evidence(self, ref: str) -> dict[str, Any]:
        evidence = lookup_evidence_ref(ref, root=self.root)
        if isinstance(evidence, EvidenceChunk):
            return {
                "status": "ok",
                "kind": "chunk",
                "citation_ref": evidence.citation_ref,
                "paper_id": evidence.paper_id,
                "title": evidence.title,
                "year": evidence.year,
                "chunk_id": evidence.chunk_id,
                "section": evidence.section,
                "page_start": evidence.page_start,
                "page_end": evidence.page_end,
                **_bounded_text_payload(evidence.text, limit=_MAX_EVIDENCE_TEXT),
            }
        assert isinstance(evidence, EvidenceField)
        return {
            "status": "ok",
            "kind": "field",
            "citation_ref": evidence.citation_ref,
            "paper_id": evidence.paper_id,
            "title": evidence.title,
            "year": evidence.year,
            "field": evidence.field,
            **_bounded_text_payload(evidence.text, limit=_MAX_EVIDENCE_TEXT),
        }

    def compare_papers(
        self,
        paper_ids: list[str],
        *,
        aspects: list[CompareAspect] | None = None,
    ) -> dict[str, Any]:
        if not 2 <= len(paper_ids) <= _MAX_COMPARE_PAPERS:
            raise KnowledgeError("compare_papers requires two to five paper_ids")
        if len(paper_ids) != len(set(paper_ids)):
            raise KnowledgeError("compare_papers requires distinct paper_ids")
        for paper_id in paper_ids:
            _validate_paper_id(paper_id)
        selected_aspects = list(_COMPARE_ASPECTS) if aspects is None else aspects
        if not selected_aspects:
            raise KnowledgeError("aspects must be non-empty")
        if len(selected_aspects) != len(set(selected_aspects)):
            raise KnowledgeError("aspects must not contain duplicates")
        invalid_aspects = set(selected_aspects) - set(_COMPARE_ASPECTS)
        if invalid_aspects:
            raise KnowledgeError(
                f"unsupported comparison aspects: {sorted(invalid_aspects)}"
            )
        with self._fields_store() as fields_store:
            rows = [fields_store.get(paper_id) for paper_id in paper_ids]
        missing = [
            paper_id
            for paper_id, row in zip(paper_ids, rows, strict=True)
            if row is None
        ]
        if missing:
            raise KnowledgeError(f"indexed papers not found: {missing}")
        payload = build_multi_compare_payload(
            [row for row in rows if row is not None],
            selected_aspects,
            max_items=4,
        )
        return {
            "status": "ok",
            **_bounded_value(payload),
        }

    def _fields_store(self) -> FieldsStore:
        return FieldsStore.open_read_only(self.root / "fields.db")


def _paper_brief(row: PaperRow) -> dict[str, Any]:
    meta = row.data.get("meta", {})
    authors = meta.get("authors", []) if isinstance(meta, dict) else []
    return {
        "paper_id": row.paper_id,
        "indexed_at": row.indexed_at,
        "title": _string_value(meta, "title"),
        "authors": [
            _truncate(str(author), _MAX_SUMMARY_TEXT)
            for author in authors[:8]
        ]
        if isinstance(authors, list)
        else [],
        "year": meta.get("year") if isinstance(meta, dict) else None,
        "venue": _string_value(meta, "venue"),
        "top_methods": [
            _truncate(str(item.get("name", "")), _MAX_SUMMARY_TEXT)
            for item in _dict_items(row.data.get("methods"), limit=3)
        ],
        "top_contributions": [
            _truncate(str(item.get("claim", "")), _MAX_SUMMARY_TEXT)
            for item in _dict_items(row.data.get("contributions"), limit=2)
        ],
    }


def _search_result_payload(match: SearchResult, *, rank: int) -> dict[str, Any]:
    meta = match.paper_data.get("meta", {})
    chunks = match.chunks or (match.best_chunk,)
    return {
        "rank": rank,
        "paper_id": match.paper_id,
        "title": match.title,
        "year": match.year,
        "venue": _string_value(meta, "venue"),
        "evidence": [
            {
                "citation_ref": f"[{match.paper_id}:chunks[{chunk.chunk_id}]]",
                "section": chunk.section,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                **_bounded_text_payload(chunk.text, limit=_MAX_SEARCH_TEXT),
            }
            for chunk in chunks[:2]
        ],
    }


def _bounded_collection(data: dict[str, Any], key: str) -> list[Any]:
    value = data.get(key, [])
    if not isinstance(value, list):
        return []
    return [_bounded_value(item) for item in value[:_MAX_PAPER_ITEMS]]


def _bounded_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 8:
        return "[nested value omitted]"
    if isinstance(value, str):
        return _truncate(value, _MAX_SUMMARY_TEXT)
    if isinstance(value, list):
        return [
            _bounded_value(item, depth=depth + 1)
            for item in value[:_MAX_PAPER_ITEMS]
        ]
    if isinstance(value, dict):
        return {
            str(key): _bounded_value(item, depth=depth + 1)
            for key, item in list(value.items())[:24]
        }
    if isinstance(value, int | float | bool) or value is None:
        return value
    return _truncate(str(value), _MAX_SUMMARY_TEXT)


def _bounded_text_payload(text: str, *, limit: int) -> dict[str, Any]:
    return {
        "text": _truncate(text, limit),
        "text_length": len(text),
        "text_truncated": len(text) > limit,
    }


def _dict_items(value: Any, *, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value[:limit] if isinstance(item, dict)]


def _string_value(value: Any, key: str) -> str | None:
    if not isinstance(value, dict):
        return None
    item = value.get(key)
    return _truncate(item, _MAX_SUMMARY_TEXT) if isinstance(item, str) else None


def _count_library_pdfs(pdf_dir: Path) -> int:
    return sum(
        1
        for path in pdf_dir.rglob("*.pdf")
        if ".paper-copilot-trash" not in path.parts
        and not any(part.startswith(".") for part in path.relative_to(pdf_dir).parts)
    )


def _embedding_key_available() -> bool:
    load_env()
    return any(os.environ.get(name) for name in ("DASHSCOPE_API_KEY", "LLM_API_KEY"))


def _validate_paper_id(paper_id: str) -> None:
    if _PAPER_ID_RE.fullmatch(paper_id) is None:
        raise KnowledgeError("paper_id must contain 3-64 letters, digits, '_' or '-'")


def _require_range(name: str, value: int, *, minimum: int, maximum: int) -> None:
    if not minimum <= value <= maximum:
        raise KnowledgeError(f"{name} must be between {minimum} and {maximum}")


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}..."
