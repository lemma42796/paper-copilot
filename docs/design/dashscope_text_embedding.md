# DashScope Text Embedding Notes

Runtime contract checked against the implementation on 2026-07-23. Vendor
limits and pricing were originally recorded from an Aliyun Bailian
documentation excerpt dated 2026-05-19.

This repo uses DashScope's OpenAI-compatible embedding endpoint for the
cross-paper index. The current locked model is `text-embedding-v4`.

## Runtime Contract

- Endpoint: `https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings`
- Auth header: `Authorization: Bearer $DASHSCOPE_API_KEY`
- Model: `text-embedding-v4`
- Dimensions used by paper-copilot: `1024`
- Encoding format: `float`
- Max input rows per request: `10`
- Max tokens per input row: `8192`
- API shape follows OpenAI embedding compatibility enough for `model`, `input`,
  `dimensions`, and `encoding_format`.

Example request shape:

```json
{
  "model": "text-embedding-v4",
  "input": ["query or chunk text"],
  "dimensions": 1024,
  "encoding_format": "float"
}
```

Example success shape:

```json
{
  "data": [
    {
      "embedding": [0.0023064255, -0.009327292],
      "index": 0,
      "object": "embedding"
    }
  ],
  "model": "text-embedding-v4",
  "object": "list",
  "usage": {
    "prompt_tokens": 23,
    "total_tokens": 23
  }
}
```

Example error shape:

```json
{
  "error": {
    "message": "Incorrect API key provided.",
    "type": "invalid_request_error",
    "param": null,
    "code": "invalid_api_key"
  }
}
```

## Model Facts Used Here

`text-embedding-v4` belongs to the Qwen3-Embedding series. The documentation
lists supported dimensions:

- `2048`
- `1536`
- `1024` default
- `768`
- `512`
- `256`
- `128`
- `64`

The repo pins `1024` because the existing `sqlite-vec` schema is
`float[1024]`. Changing this dimension requires rebuilding `embeddings.db` and
updating `embeddings_meta.json`.

Documented language coverage is 100+ mainstream languages plus programming
languages. This matters because the product path often uses Chinese questions
against English paper chunks.

## Historical Pricing Snapshot

The following values are retained only as the 2026-05-19 costing input. They
are not a current quote; check the vendor pricing page before making a new
cost or model decision.

Documented synchronous price:

- `0.0005` RMB per 1k input tokens
- Batch calling price: `0.00025` RMB per 1k input tokens
Current implementation uses the synchronous OpenAI-compatible endpoint, not
the batch interface.

## Important Boundaries

- This is a remote API, not a local model. Chunk text is sent to DashScope.
- Old local `BAAI/bge-m3` vectors must not be mixed with
  `text-embedding-v4` vectors. The meta check should force a reindex when
  the model name changes.
- Multimodal embedding models such as `qwen3-vl-embedding` and
  `tongyi-embedding-vision` are documented as not supported by the
  OpenAI-compatible endpoint. This repo only uses text embeddings here.
- `DASHSCOPE_API_KEY` is the preferred env var. The current implementation can
  fall back to `LLM_API_KEY` when the LLM also uses DashScope.
- The endpoint's max input rows is 10, so `Embedder.encode()` batches requests
  at most 10 rows at a time even if callers pass a larger batch size.

## Operational Consequences

After switching model or dimension, the host application must rebuild the index
from the configured PDF directory. The old `embeddings.db` should be treated as
stale once `MODEL_NAME` or `EMBEDDING_DIM` changes. Search should fail early via
`embeddings_meta.json` instead of returning mixed-model distances.
