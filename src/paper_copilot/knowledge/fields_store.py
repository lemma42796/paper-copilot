"""SQLite-backed field index for locally read papers.

Single-table design: every paper is one row holding the full Paper JSON
(`model_dump_json()`) in the `data` column. Expression indexes on
common scalars (year, arxiv_id) keep filter queries cheap without
normalising the schema into per-field tables — this is what TASKS.md
M10 calls "JSON column + expression indexes, avoid multi-table joins".

Array substring queries (e.g. "method contains 'contrastive'") scan
inline via ``json_each(data, '$.methods')`` + ``LIKE``. At the Phase 2
scale (< 100 papers) this stays well under the 50ms DoD; FTS5 is held
back until the signal justifies it.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from paper_copilot.shared.errors import KnowledgeError

_SCHEMA_VERSION = 1

_CREATE_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS papers (
        paper_id   TEXT PRIMARY KEY,
        indexed_at TEXT NOT NULL,
        data       TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_papers_year
        ON papers(CAST(json_extract(data, '$.meta.year') AS INTEGER))
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_papers_arxiv
        ON papers(json_extract(data, '$.meta.arxiv_id'))
    """,
    """
    CREATE TABLE IF NOT EXISTS schema_meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
)

# Searchable string sub-fields per array. Adding a new one later only
# broadens the match set — it does not require a schema migration,
# because the full JSON is always present in `data`.
_CONTAINS_FIELDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "method": ("$.methods", ("name", "description", "novelty_vs_prior")),
    "contribution": ("$.contributions", ("claim",)),
    "experiment": ("$.experiments", ("dataset", "metric", "raw", "comparison_baseline")),
    "limitation": ("$.limitations", ("description",)),
}


def available_fields() -> tuple[str, ...]:
    return tuple(_CONTAINS_FIELDS)


@dataclass(frozen=True, slots=True)
class PaperRow:
    paper_id: str
    indexed_at: str
    data: dict[str, Any]


class FieldsStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    def open(cls, db_path: Path) -> Self:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        store = cls(conn)
        store._init_schema()
        return store

    def _init_schema(self) -> None:
        with self._conn:
            for stmt in _CREATE_STATEMENTS:
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

    def upsert(self, paper_id: str, payload: dict[str, Any], indexed_at: str) -> None:
        data_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self._conn:
            self._conn.execute(
                "INSERT INTO papers(paper_id, indexed_at, data) VALUES(?, ?, ?) "
                "ON CONFLICT(paper_id) DO UPDATE SET "
                "indexed_at=excluded.indexed_at, data=excluded.data",
                (paper_id, indexed_at, data_json),
            )

    def begin_batch(self) -> sqlite3.Connection:
        """Return the underlying connection for callers that want to wrap
        many ``upsert`` calls in a single transaction. Use as
        ``with store.begin_batch(): ...``.
        """
        return self._conn

    def get(self, paper_id: str) -> PaperRow | None:
        cur = self._conn.execute(
            "SELECT paper_id, indexed_at, data FROM papers WHERE paper_id = ?",
            (paper_id,),
        )
        row = cur.fetchone()
        return _row(row) if row else None

    def count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM papers")
        (n,) = cur.fetchone()
        return int(n)

    def list_all(self, *, year: int | None = None) -> list[PaperRow]:
        if year is None:
            cur = self._conn.execute(
                "SELECT paper_id, indexed_at, data FROM papers "
                "ORDER BY CAST(json_extract(data, '$.meta.year') AS INTEGER) DESC, "
                "paper_id"
            )
        else:
            cur = self._conn.execute(
                "SELECT paper_id, indexed_at, data FROM papers "
                "WHERE CAST(json_extract(data, '$.meta.year') AS INTEGER) = ? "
                "ORDER BY paper_id",
                (year,),
            )
        return [_row(r) for r in cur.fetchall()]

    def query_contains(
        self,
        field: str,
        term: str,
        *,
        year: int | None = None,
    ) -> list[PaperRow]:
        if field not in _CONTAINS_FIELDS:
            raise KnowledgeError(
                f"unknown field {field!r}; choose from {sorted(_CONTAINS_FIELDS)}"
            )
        if not term:
            raise KnowledgeError("contains term must be non-empty")

        path, subfields = _CONTAINS_FIELDS[field]
        or_clauses = " OR ".join(
            f"lower(json_extract(e.value, '$.{s}')) LIKE ?" for s in subfields
        )
        sql = (
            "SELECT DISTINCT p.paper_id, p.indexed_at, p.data "
            "FROM papers p, json_each(p.data, ?) AS e "
            f"WHERE ({or_clauses})"
        )
        like = f"%{term.lower()}%"
        params: list[Any] = [path, *(like for _ in subfields)]
        if year is not None:
            sql += " AND CAST(json_extract(p.data, '$.meta.year') AS INTEGER) = ?"
            params.append(year)
        sql += " ORDER BY CAST(json_extract(p.data, '$.meta.year') AS INTEGER) DESC, p.paper_id"

        cur = self._conn.execute(sql, params)
        return [_row(r) for r in cur.fetchall()]


def _row(raw: tuple[str, str, str]) -> PaperRow:
    paper_id, indexed_at, data_json = raw
    return PaperRow(
        paper_id=paper_id,
        indexed_at=indexed_at,
        data=json.loads(data_json),
    )
