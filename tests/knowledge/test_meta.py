from __future__ import annotations

from pathlib import Path

import pytest

from paper_copilot.knowledge.meta import IndexMeta, read_meta, require_match, write_meta
from paper_copilot.shared.errors import KnowledgeError


def test_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "meta.json"
    meta = IndexMeta.fresh(embedding_model="m", embedding_dim=4).with_counts(
        n_papers=2, n_chunks=5
    )
    write_meta(p, meta)
    assert read_meta(p) == meta


def test_read_missing_returns_none(tmp_path: Path) -> None:
    assert read_meta(tmp_path / "missing.json") is None


def test_require_match_happy(tmp_path: Path) -> None:
    p = tmp_path / "meta.json"
    write_meta(p, IndexMeta.fresh(embedding_model="m", embedding_dim=4))
    meta = require_match(p, embedding_model="m", embedding_dim=4)
    assert meta.embedding_model == "m"


def test_require_match_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(KnowledgeError, match=r"meta\.json not found"):
        require_match(tmp_path / "missing.json", embedding_model="m", embedding_dim=4)


def test_require_match_model_mismatch_raises(tmp_path: Path) -> None:
    p = tmp_path / "meta.json"
    write_meta(p, IndexMeta.fresh(embedding_model="old", embedding_dim=4))
    with pytest.raises(KnowledgeError, match="embedding model mismatch"):
        require_match(p, embedding_model="new", embedding_dim=4)


def test_require_match_dim_mismatch_raises(tmp_path: Path) -> None:
    p = tmp_path / "meta.json"
    write_meta(p, IndexMeta.fresh(embedding_model="m", embedding_dim=4))
    with pytest.raises(KnowledgeError, match="embedding model mismatch"):
        require_match(p, embedding_model="m", embedding_dim=8)
