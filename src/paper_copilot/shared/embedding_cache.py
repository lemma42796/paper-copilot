from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Protocol, Self

import numpy as np

from paper_copilot.shared.chunking import CharSpan
from paper_copilot.shared.errors import KnowledgeError


class EmbeddingEncoder(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def dim(self) -> int: ...

    def token_spans(self, text: str) -> list[CharSpan]: ...

    def encode(self, texts: list[str], *, batch_size: int = 32) -> np.ndarray: ...


class EmbeddingCache:
    def __init__(self, conn: sqlite3.Connection, dim: int) -> None:
        self._conn = conn
        self._dim = dim

    @classmethod
    def open(cls, db_path: Path, *, dim: int) -> Self:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        cache = cls(conn, dim)
        cache._init_schema()
        return cache

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS embeddings (
                    model       TEXT NOT NULL,
                    dim         INTEGER NOT NULL,
                    text_sha256 TEXT NOT NULL,
                    text        TEXT NOT NULL,
                    vector      BLOB NOT NULL,
                    created_at  TEXT NOT NULL,
                    PRIMARY KEY(model, dim, text_sha256)
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

    def get_many(self, model: str, texts: list[str]) -> list[np.ndarray | None]:
        vectors: list[np.ndarray | None] = []
        for text in texts:
            row = self._conn.execute(
                """
                SELECT text, vector
                FROM embeddings
                WHERE model = ? AND dim = ? AND text_sha256 = ?
                """,
                (model, self._dim, _text_sha256(text)),
            ).fetchone()
            if row is None or row[0] != text:
                vectors.append(None)
                continue
            vector = np.frombuffer(row[1], dtype=np.float32).copy()
            if vector.shape != (self._dim,):
                raise KnowledgeError(
                    f"cached embedding shape {vector.shape} does not match dim={self._dim}"
                )
            vectors.append(vector)
        return vectors

    def put_many(self, model: str, texts: list[str], vectors: np.ndarray) -> None:
        if vectors.ndim != 2 or vectors.shape != (len(texts), self._dim):
            raise KnowledgeError(
                f"embedding shape {vectors.shape} does not match "
                f"expected ({len(texts)}, {self._dim})"
            )
        created_at = datetime.now(UTC).isoformat()
        with self._conn:
            for text, vector in zip(texts, vectors, strict=True):
                self._conn.execute(
                    """
                    INSERT INTO embeddings(model, dim, text_sha256, text, vector, created_at)
                    VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT(model, dim, text_sha256) DO UPDATE SET
                        text = excluded.text,
                        vector = excluded.vector,
                        created_at = excluded.created_at
                    """,
                    (
                        model,
                        self._dim,
                        _text_sha256(text),
                        text,
                        np.asarray(vector, dtype=np.float32).tobytes(order="C"),
                        created_at,
                    ),
                )


class CachedEmbedder:
    def __init__(self, encoder: EmbeddingEncoder, cache: EmbeddingCache) -> None:
        self._encoder = encoder
        self._cache = cache

    @property
    def model_name(self) -> str:
        return self._encoder.model_name

    @property
    def dim(self) -> int:
        return self._encoder.dim

    def token_spans(self, text: str) -> list[CharSpan]:
        return self._encoder.token_spans(text)

    def encode(self, texts: list[str], *, batch_size: int = 32) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)

        cached = self._cache.get_many(self.model_name, texts)
        rows: list[np.ndarray | None] = list(cached)
        missing_indices_by_text: dict[str, list[int]] = {}
        for index, vector in enumerate(cached):
            if vector is None:
                missing_indices_by_text.setdefault(texts[index], []).append(index)

        missing_texts = list(missing_indices_by_text)
        if missing_texts:
            fresh = self._encoder.encode(missing_texts, batch_size=batch_size)
            self._cache.put_many(self.model_name, missing_texts, fresh)
            for text, vector in zip(missing_texts, fresh, strict=True):
                for index in missing_indices_by_text[text]:
                    rows[index] = vector

        return np.vstack([_require_vector(row, self.dim) for row in rows]).astype(
            np.float32,
            copy=False,
        )


def _require_vector(vector: np.ndarray | None, dim: int) -> np.ndarray:
    if vector is None:
        raise KnowledgeError("embedding cache failed to fill a missing vector")
    if vector.shape != (dim,):
        raise KnowledgeError(f"embedding shape {vector.shape} does not match dim={dim}")
    return vector


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
