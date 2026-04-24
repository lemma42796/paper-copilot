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

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Self

import numpy as np
import sqlite_vec

from paper_copilot.shared.errors import KnowledgeError

_SCHEMA_VERSION = 1


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

    def count_chunks(self) -> int:
        (n,) = self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
        return int(n)

    def count_papers(self) -> int:
        (n,) = self._conn.execute("SELECT COUNT(DISTINCT paper_id) FROM chunks").fetchone()
        return int(n)
