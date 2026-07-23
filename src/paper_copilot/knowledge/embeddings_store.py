"""Cross-paper embedding index backed by sqlite-vec.

Layout: a regular ``chunks`` table holds metadata + original text, a
``vec0`` virtual table holds the dense vectors. Both share ``chunk_id``
as the rowid so joins are cheap.

Why not a single ``vec0`` with auxiliary columns: vec0's query language
for typed auxiliary filters is narrower than plain SQL; keeping chunks in
a normal table lets us compose ``WHERE paper_id IN (...)`` with other
``knowledge/`` queries (field filters from ``fields_store``) without
learning a second dialect.

The query pattern is: pre-filter rowids by paper_id (sub-query), then
``MATCH ? AND k = ?``. sqlite-vec pushes the rowid set into the ANN scan.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Self

import numpy as np
import sqlite_vec

from paper_copilot.shared.errors import KnowledgeError

_SCHEMA_VERSION = 2
_FTS_TOKEN_RE = re.compile(r"[\w]+", flags=re.UNICODE)
_MAX_FTS_TERMS = 16


def _f32_bytes(vec: np.ndarray) -> bytes:
    if vec.dtype != np.float32:
        vec = vec.astype(np.float32)
    return vec.tobytes(order="C")


def _create_statements(dim: int) -> tuple[str, ...]:
    return (
        """
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id   TEXT NOT NULL,
            ord        INTEGER NOT NULL,
            section    TEXT NOT NULL,
            page_start INTEGER NOT NULL,
            page_end   INTEGER NOT NULL,
            text       TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_chunks_paper ON chunks(paper_id)",
        f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(embedding float[{dim}])",
        "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(text)",
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """,
    )


@dataclass(frozen=True, slots=True)
class ChunkHit:
    chunk_id: int
    paper_id: str
    ord: int
    section: str
    page_start: int
    page_end: int
    text: str
    distance: float


@dataclass(frozen=True, slots=True)
class TextHit:
    chunk_id: int
    paper_id: str
    ord: int
    section: str
    page_start: int
    page_end: int
    text: str
    bm25: float


@dataclass(frozen=True, slots=True)
class ChunkRow:
    chunk_id: int
    paper_id: str
    ord: int
    section: str
    page_start: int
    page_end: int
    text: str


class EmbeddingsStore:
    def __init__(self, conn: sqlite3.Connection, dim: int) -> None:
        self._conn = conn
        self._dim = dim

    @classmethod
    def open(cls, db_path: Path, *, dim: int) -> Self:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        store = cls(conn, dim)
        store._init_schema()
        return store

    @classmethod
    def open_read_only(cls, db_path: Path, *, dim: int) -> Self:
        if not db_path.is_file():
            raise KnowledgeError(f"embedding index not found: {db_path}")
        uri = f"{db_path.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute("PRAGMA query_only=ON")
        return cls(conn, dim)

    @property
    def dim(self) -> int:
        return self._dim

    def _init_schema(self) -> None:
        with self._conn:
            for stmt in _create_statements(self._dim):
                self._conn.execute(stmt)
            self._conn.execute(
                "INSERT INTO schema_meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("version", str(_SCHEMA_VERSION)),
            )
            self._backfill_fts()

    def _backfill_fts(self) -> None:
        self._conn.execute(
            """
            INSERT INTO chunk_fts(rowid, text)
            SELECT c.chunk_id, c.text
            FROM chunks c
            WHERE NOT EXISTS (
                SELECT 1 FROM chunk_fts f WHERE f.rowid = c.chunk_id
            )
            """
        )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def replace_paper(
        self,
        paper_id: str,
        chunks: list[ChunkRow],
        embeddings: np.ndarray,
    ) -> None:
        """Atomically replace all chunks + vectors belonging to ``paper_id``.

        Single transaction. ``embeddings.shape[0]`` must equal ``len(chunks)``.
        """
        if embeddings.ndim != 2 or embeddings.shape[1] != self._dim:
            raise KnowledgeError(
                f"embedding shape {embeddings.shape} does not match store dim={self._dim}"
            )
        if embeddings.shape[0] != len(chunks):
            raise KnowledgeError(
                f"embeddings rows ({embeddings.shape[0]}) != chunks ({len(chunks)})"
            )
        with self._conn:
            old = [
                row[0]
                for row in self._conn.execute(
                    "SELECT chunk_id FROM chunks WHERE paper_id = ?", (paper_id,)
                )
            ]
            if old:
                placeholders = ",".join("?" * len(old))
                self._conn.execute(
                    f"DELETE FROM vec_chunks WHERE rowid IN ({placeholders})", old
                )
                self._conn.execute(
                    f"DELETE FROM chunk_fts WHERE rowid IN ({placeholders})", old
                )
                self._conn.execute(
                    f"DELETE FROM chunks WHERE chunk_id IN ({placeholders})", old
                )
            for row, vec in zip(chunks, embeddings, strict=True):
                cur = self._conn.execute(
                    "INSERT INTO chunks(paper_id, ord, section, page_start, page_end, text) "
                    "VALUES(?, ?, ?, ?, ?, ?)",
                    (
                        paper_id,
                        row.ord,
                        row.section,
                        row.page_start,
                        row.page_end,
                        row.text,
                    ),
                )
                chunk_id = cur.lastrowid
                self._conn.execute(
                    "INSERT INTO vec_chunks(rowid, embedding) VALUES(?, ?)",
                    (chunk_id, _f32_bytes(vec)),
                )
                self._conn.execute(
                    "INSERT INTO chunk_fts(rowid, text) VALUES(?, ?)",
                    (chunk_id, row.text),
                )

    def delete_paper(self, paper_id: str) -> int:
        with self._conn:
            old = [
                row[0]
                for row in self._conn.execute(
                    "SELECT chunk_id FROM chunks WHERE paper_id = ?", (paper_id,)
                )
            ]
            if not old:
                return 0
            placeholders = ",".join("?" * len(old))
            self._conn.execute(
                f"DELETE FROM vec_chunks WHERE rowid IN ({placeholders})", old
            )
            self._conn.execute(
                f"DELETE FROM chunk_fts WHERE rowid IN ({placeholders})", old
            )
            self._conn.execute(
                f"DELETE FROM chunks WHERE chunk_id IN ({placeholders})", old
            )
        return len(old)

    def knn(
        self,
        query: np.ndarray,
        *,
        k: int,
        paper_ids: list[str] | None = None,
    ) -> list[ChunkHit]:
        if query.ndim != 1 or query.shape[0] != self._dim:
            raise KnowledgeError(
                f"query shape {query.shape} does not match store dim={self._dim}"
            )
        if k <= 0:
            return []

        params: list[object] = [_f32_bytes(query), k]
        sql = (
            "SELECT v.rowid, v.distance, c.paper_id, c.ord, c.section, "
            "       c.page_start, c.page_end, c.text "
            "FROM vec_chunks v JOIN chunks c ON c.chunk_id = v.rowid "
            "WHERE v.embedding MATCH ? AND k = ?"
        )
        if paper_ids is not None:
            if not paper_ids:
                return []
            placeholders = ",".join("?" * len(paper_ids))
            sql += (
                f" AND v.rowid IN (SELECT chunk_id FROM chunks "
                f"WHERE paper_id IN ({placeholders}))"
            )
            params.extend(paper_ids)
        sql += " ORDER BY v.distance"

        hits: list[ChunkHit] = []
        for row in self._conn.execute(sql, params):
            chunk_id, distance, paper_id, ord_, section, ps, pe, text = row
            hits.append(
                ChunkHit(
                    chunk_id=int(chunk_id),
                    paper_id=str(paper_id),
                    ord=int(ord_),
                    section=str(section),
                    page_start=int(ps),
                    page_end=int(pe),
                    text=str(text),
                    distance=float(distance),
                )
            )
        return hits

    def bm25(
        self,
        query: str,
        *,
        k: int,
        paper_ids: list[str] | None = None,
    ) -> list[TextHit]:
        if k <= 0:
            return []
        match_query = _fts_match_query(query)
        if not match_query:
            return []

        params: list[object] = [match_query]
        sql = (
            "SELECT c.chunk_id, bm25(chunk_fts), c.paper_id, c.ord, c.section, "
            "       c.page_start, c.page_end, c.text "
            "FROM chunk_fts JOIN chunks c ON c.chunk_id = chunk_fts.rowid "
            "WHERE chunk_fts MATCH ?"
        )
        if paper_ids is not None:
            if not paper_ids:
                return []
            placeholders = ",".join("?" * len(paper_ids))
            sql += f" AND c.paper_id IN ({placeholders})"
            params.extend(paper_ids)
        sql += " ORDER BY bm25(chunk_fts) LIMIT ?"
        params.append(k)

        hits: list[TextHit] = []
        for row in self._conn.execute(sql, params):
            chunk_id, bm25, paper_id, ord_, section, ps, pe, text = row
            hits.append(
                TextHit(
                    chunk_id=int(chunk_id),
                    paper_id=str(paper_id),
                    ord=int(ord_),
                    section=str(section),
                    page_start=int(ps),
                    page_end=int(pe),
                    text=str(text),
                    bm25=float(bm25),
                )
            )
        return hits

    def get_chunk(self, chunk_id: int, *, paper_id: str | None = None) -> ChunkRow | None:
        params: list[object] = [chunk_id]
        sql = (
            "SELECT chunk_id, paper_id, ord, section, page_start, page_end, text "
            "FROM chunks WHERE chunk_id = ?"
        )
        if paper_id is not None:
            sql += " AND paper_id = ?"
            params.append(paper_id)
        row = self._conn.execute(sql, params).fetchone()
        if row is None:
            return None
        chunk_id_raw, paper_id_raw, ord_, section, ps, pe, text = row
        return ChunkRow(
            chunk_id=int(chunk_id_raw),
            paper_id=str(paper_id_raw),
            ord=int(ord_),
            section=str(section),
            page_start=int(ps),
            page_end=int(pe),
            text=str(text),
        )

    def count_chunks(self) -> int:
        (n,) = self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
        return int(n)

    def count_papers(self) -> int:
        (n,) = self._conn.execute("SELECT COUNT(DISTINCT paper_id) FROM chunks").fetchone()
        return int(n)


def _fts_match_query(query: str) -> str:
    terms = _FTS_TOKEN_RE.findall(query.casefold())
    if not terms:
        return ""
    unique_terms = list(dict.fromkeys(terms))[:_MAX_FTS_TERMS]
    return " OR ".join(_quote_fts_term(term) for term in unique_terms)


def _quote_fts_term(term: str) -> str:
    escaped = term.replace('"', '""')
    return f'"{escaped}"'
