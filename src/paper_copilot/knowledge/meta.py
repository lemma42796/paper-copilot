"""Sidecar ``meta.json`` for the embedding index.

Purpose: fail loudly when the embedding model / dim drifts from what's
baked into ``embeddings.db``. A mismatched query vector silently
produces garbage distances — the check here catches it at open-time
instead. Callers must ``paper-copilot reindex`` after any change.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from paper_copilot.shared.errors import KnowledgeError


@dataclass(frozen=True, slots=True)
class IndexMeta:
    embedding_model: str
    embedding_dim: int
    indexed_at: str
    n_papers: int
    n_chunks: int

    @classmethod
    def fresh(cls, *, embedding_model: str, embedding_dim: int) -> Self:
        return cls(
            embedding_model=embedding_model,
            embedding_dim=embedding_dim,
            indexed_at=datetime.now(UTC).isoformat(),
            n_papers=0,
            n_chunks=0,
        )

    def with_counts(self, *, n_papers: int, n_chunks: int) -> Self:
        return type(self)(
            embedding_model=self.embedding_model,
            embedding_dim=self.embedding_dim,
            indexed_at=datetime.now(UTC).isoformat(),
            n_papers=n_papers,
            n_chunks=n_chunks,
        )


def read_meta(path: Path) -> IndexMeta | None:
    if not path.exists():
        return None
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    try:
        return IndexMeta(
            embedding_model=str(raw["embedding_model"]),
            embedding_dim=int(raw["embedding_dim"]),
            indexed_at=str(raw["indexed_at"]),
            n_papers=int(raw["n_papers"]),
            n_chunks=int(raw["n_chunks"]),
        )
    except KeyError as e:
        raise KnowledgeError(f"meta.json missing required field: {e}") from e


def write_meta(path: Path, meta: IndexMeta) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(meta), indent=2, sort_keys=True), encoding="utf-8")


def require_match(path: Path, *, embedding_model: str, embedding_dim: int) -> IndexMeta:
    """Open-time invariant. Raises if the on-disk index was built with a
    different model/dim — a new query vector would collide with stale
    stored vectors and return bogus distances otherwise.
    """
    meta = read_meta(path)
    if meta is None:
        raise KnowledgeError(
            f"meta.json not found at {path}; run `paper-copilot reindex` to build the index"
        )
    if meta.embedding_model != embedding_model or meta.embedding_dim != embedding_dim:
        raise KnowledgeError(
            f"embedding model mismatch: index built with "
            f"{meta.embedding_model!r} (dim={meta.embedding_dim}); "
            f"runtime is {embedding_model!r} (dim={embedding_dim}). "
            f"Run `paper-copilot reindex` to rebuild."
        )
    return meta
