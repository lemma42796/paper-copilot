from __future__ import annotations

from pathlib import Path

import numpy as np

from paper_copilot.shared.embedding_cache import CachedEmbedder, EmbeddingCache

DIM = 3


class FakeEmbedder:
    def __init__(self, *, model_name: str = "fake-model") -> None:
        self.model_name = model_name
        self.dim = DIM
        self.calls: list[tuple[str, ...]] = []

    def encode(self, texts: list[str], *, batch_size: int = 32) -> np.ndarray:
        self.calls.append(tuple(texts))
        return np.vstack([_vector_for(text) for text in texts]).astype(np.float32)


def test_cached_embedder_persists_vectors(tmp_path: Path) -> None:
    cache_path = tmp_path / "embeddings.sqlite"
    first = FakeEmbedder()

    with EmbeddingCache.open(cache_path, dim=DIM) as cache:
        cached = CachedEmbedder(first, cache)
        vectors = cached.encode(["alpha", "beta", "alpha"])

    assert first.calls == [("alpha", "beta")]
    np.testing.assert_allclose(vectors[0], _vector_for("alpha"))
    np.testing.assert_allclose(vectors[1], _vector_for("beta"))
    np.testing.assert_allclose(vectors[2], _vector_for("alpha"))

    second = FakeEmbedder()
    with EmbeddingCache.open(cache_path, dim=DIM) as cache:
        cached = CachedEmbedder(second, cache)
        vectors = cached.encode(["beta", "alpha"])

    assert second.calls == []
    np.testing.assert_allclose(vectors[0], _vector_for("beta"))
    np.testing.assert_allclose(vectors[1], _vector_for("alpha"))


def test_cached_embedder_keeps_models_separate(tmp_path: Path) -> None:
    cache_path = tmp_path / "embeddings.sqlite"
    first = FakeEmbedder(model_name="model-a")

    with EmbeddingCache.open(cache_path, dim=DIM) as cache:
        CachedEmbedder(first, cache).encode(["alpha"])

    second = FakeEmbedder(model_name="model-b")
    with EmbeddingCache.open(cache_path, dim=DIM) as cache:
        CachedEmbedder(second, cache).encode(["alpha"])

    assert first.calls == [("alpha",)]
    assert second.calls == [("alpha",)]


def _vector_for(text: str) -> np.ndarray:
    base = float(sum(ord(char) for char in text))
    return np.array([base, base + 1.0, base + 2.0], dtype=np.float32)
