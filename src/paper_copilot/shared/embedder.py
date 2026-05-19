"""DashScope text embedding client used by the cross-paper index."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

import numpy as np

from paper_copilot.shared.chunking import CharSpan
from paper_copilot.shared.env import load_env
from paper_copilot.shared.errors import KnowledgeError

__all__ = ["EMBEDDING_DIM", "MODEL_NAME", "Embedder"]

MODEL_NAME = "text-embedding-v4"
EMBEDDING_DIM = 1024
DASHSCOPE_COMPAT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_MAX_BATCH_ROWS = 10
_TOKEN_RE = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
    r"|[A-Za-z0-9]+(?:[-_'][A-Za-z0-9]+)*"
    r"|[^\s]"
)


class Embedder:
    def __init__(
        self,
        model_name: str = MODEL_NAME,
        *,
        dimensions: int = EMBEDDING_DIM,
        base_url: str = DASHSCOPE_COMPAT_BASE_URL,
        api_key: str | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        self._model_name = model_name
        self._dimensions = dimensions
        self._endpoint = f"{base_url.rstrip('/')}/embeddings"
        self._api_key = api_key
        self._timeout_s = timeout_s

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dim(self) -> int:
        return self._dimensions

    def warmup(self) -> None:
        self._resolve_api_key()

    def token_spans(self, text: str) -> list[CharSpan]:
        return [(match.start(), match.end()) for match in _TOKEN_RE.finditer(text)]

    def encode(self, texts: list[str], *, batch_size: int = 32) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dimensions), dtype=np.float32)
        if batch_size <= 0:
            raise ValueError(f"batch_size must be positive, got {batch_size}")
        rows_per_batch = min(batch_size, _MAX_BATCH_ROWS)
        vectors: list[list[float]] = []
        for start in range(0, len(texts), rows_per_batch):
            batch = texts[start : start + rows_per_batch]
            vectors.extend(self._embed_batch(batch))
        arr: np.ndarray = np.asarray(vectors, dtype=np.float32)
        if arr.ndim != 2 or arr.shape != (len(texts), self._dimensions):
            raise KnowledgeError(
                f"embedding response shape {arr.shape} does not match "
                f"expected ({len(texts)}, {self._dimensions})"
            )
        return arr

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        payload = self._post_json(
            {
                "model": self._model_name,
                "input": texts,
                "dimensions": self._dimensions,
                "encoding_format": "float",
            }
        )
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != len(texts):
            raise KnowledgeError("embedding API returned an invalid data payload")

        indexed: list[tuple[int, list[float]]] = []
        for item in data:
            if not isinstance(item, dict):
                raise KnowledgeError("embedding API returned a non-object data item")
            index = item.get("index")
            embedding = item.get("embedding")
            if not isinstance(index, int) or not isinstance(embedding, list):
                raise KnowledgeError("embedding API returned malformed embedding data")
            indexed.append((index, [float(value) for value in embedding]))
        return [embedding for _, embedding in sorted(indexed, key=lambda pair: pair[0])]

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self._resolve_api_key()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise KnowledgeError(
                f"embedding API failed with HTTP {exc.code}: {_compact(detail)}"
            ) from exc

        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise KnowledgeError("embedding API returned a non-object response")
        error = parsed.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            raise KnowledgeError(
                str(message) if message is not None else "embedding API returned an error"
            )
        return parsed

    def _resolve_api_key(self) -> str:
        if self._api_key is not None and self._api_key:
            return self._api_key
        load_env()
        for name in ("DASHSCOPE_API_KEY", "ANTHROPIC_API_KEY"):
            value = os.environ.get(name)
            if value:
                self._api_key = value
                return value
        raise KnowledgeError("environment variable DASHSCOPE_API_KEY is not set")


def _compact(text: str, *, limit: int = 300) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= limit else f"{one_line[:limit]}..."
