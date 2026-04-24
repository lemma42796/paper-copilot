"""Lazy wrapper around BAAI/bge-m3 for cross-paper embeddings.

Owns HF model/tokenizer loading so ``shared/chunking.py`` stays
tokenizer-agnostic. Importing this module is cheap — torch is not
touched until ``encode`` or ``token_spans`` is first called.

Instantiate once per process: the first call pays ~2.3 GB download on a
cold cache plus model load; after that encode is ~fast. Designed to be
passed around (CLI/reindex share a single instance).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from paper_copilot.shared.chunking import CharSpan

__all__ = ["EMBEDDING_DIM", "MODEL_NAME", "Embedder"]

MODEL_NAME = "BAAI/bge-m3"
EMBEDDING_DIM = 1024


class Embedder:
    def __init__(self, model_name: str = MODEL_NAME) -> None:
        self._model_name = model_name
        self._model: Any = None
        self._tokenizer: Any = None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dim(self) -> int:
        return EMBEDDING_DIM

    def warmup(self) -> None:
        """Load model + tokenizer now so that the next ``encode`` is fast.
        Useful for separating cold-start cost (model load) from warm
        query-time latency when measuring/reporting.
        """
        self._get_tokenizer()
        self._get_model()

    def token_spans(self, text: str) -> list[CharSpan]:
        tok = self._get_tokenizer()
        enc = tok(
            text,
            return_offsets_mapping=True,
            add_special_tokens=False,
            truncation=False,
        )
        return [(int(s), int(e)) for s, e in enc["offset_mapping"]]

    def encode(self, texts: list[str], *, batch_size: int = 32) -> np.ndarray:
        if not texts:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        model = self._get_model()
        out = model.encode(texts, batch_size=batch_size, return_dense=True)
        vecs = out["dense_vecs"]
        arr: np.ndarray = np.asarray(vecs, dtype=np.float32)
        return arr

    def _get_tokenizer(self) -> Any:
        if self._tokenizer is None:
            import logging as _stdlib_logging

            from transformers import AutoTokenizer

            # Silence the "sequence length is longer than ... (N > 8192)"
            # warning: we only use offset_mapping for chunking and never
            # forward the oversized sequence through the model.
            _stdlib_logging.getLogger("transformers.tokenization_utils_base").setLevel(
                _stdlib_logging.ERROR
            )
            self._tokenizer = AutoTokenizer.from_pretrained(self._model_name)
        return self._tokenizer

    def _get_model(self) -> Any:
        if self._model is None:
            from FlagEmbedding import BGEM3FlagModel

            self._model = BGEM3FlagModel(self._model_name)
        return self._model
