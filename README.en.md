# Paper Copilot

> A local-first research assistant for reading PDFs, searching a personal paper
> library, and producing evidence-grounded research notes and model-framework
> drafts.

![Python](https://img.shields.io/badge/python-3.12+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Code style](https://img.shields.io/badge/code_style-ruff-purple)
![Package manager](https://img.shields.io/badge/package-uv-orange)

[简体中文](README.md) | English

Paper Copilot is designed for a small personal library of research PDFs. It
turns papers into structured reports, builds local SQLite and sqlite-vec
indexes, and uses one natural-language input for paper Q&A, cross-paper search,
comparison, and verifiable baseline-plus-module research proposals.

It is not intended to invent results or write papers on a researcher's behalf.
Its purpose is to keep evidence, sources, costs, traces, and failure boundaries
visible so that research ideas are easier to verify.

PDFs, indexes, sessions, reports, and traces remain on the user's device by
default. Necessary text fragments selected by local retrieval may be sent to a
user-configured cloud model. "The PDF is not uploaded" does not mean that no
paper content ever leaves the device.

## Contents

- [Frontend Preview](#frontend-preview)
- [Project Status](#project-status)
- [Core Capabilities](#core-capabilities)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Running](#running)
- [Local HTTP API](#local-http-api)
- [Architecture](#architecture)
- [Data Layout](#data-layout)
- [Development](#development)
- [Roadmap](#roadmap)
- [Known Limitations](#known-limitations)
- [Contributing](#contributing)

## Frontend Preview

These screenshots show the migration-period Next.js UI: natural-language
research input, local-library status, report history, Research Idea Composer,
evidence inspection, and knowledge-Q&A reports. The active milestone is
building a native SwiftUI macOS client. The Web UI remains until the native
client reaches feature parity and is manually accepted.

### Research Workbench and Local Library

![Paper Copilot research workbench: natural-language input, report history, local-library status, and API connection status](docs/assets/paper-copilot-workbench.png)

### Research Idea Composer

![Paper Copilot Composer: Chinese research proposal, candidate-module table, and structured Composer summary](docs/assets/paper-copilot-composer.png)

### Evidence Reference Lookup

![Paper Copilot evidence panel: clicking an evidence ref opens the corresponding field or chunk evidence](docs/assets/paper-copilot-evidence.png)

### Knowledge-Q&A Report

![Paper Copilot knowledge-Q&A report: cross-paper answer, run metadata, and report history](docs/assets/paper-copilot-qa-report.png)

## Project Status

This section follows `TASKS.md`, updated on 2026-07-23.

Paper Copilot is being reorganized around two local product surfaces that share
the same Python Core:

- **SwiftUI macOS client:** M20 is complete. It owns native windows,
  folder authorization, Keychain storage, task and report presentation, and
  Python Runtime lifecycle.
- **Local MCP Server:** M21 is complete. It exposes six read-only paper tools
  over local `stdio` and has passed real Codex Agent tool discovery and query
  acceptance.

Existing Python and Web baseline:

- A host process exposes `paper_copilot.api.http.serve_http_api()`. The Web
  frontend uses persistent jobs, preferring WebSocket events and falling back
  to SSE and incremental polling. `POST /chat` remains a synchronous
  compatibility endpoint.
- `apps/web/` is the migration-period Next.js chat shell. It supports the local
  library, multi-turn conversations, task progress, costs, Composer summaries,
  and evidence inspection.
- Retrieval uses DashScope `text-embedding-v4`, SQLite FTS5/BM25, sqlite-vec,
  reciprocal-rank fusion, and multi-chunk evidence selection. Previously
  computed embeddings are cached locally.
- Persistent jobs support attempts, interruption, rollout replay, conversation
  history, context compaction, and local rollout diagnostics.
- Research Idea Composer has deterministic plan state, a proposal checker,
  field/chunk evidence lookup, and Markdown report rendering.

The intended scale is about 50-100 papers in a personal library. This is not a
hosted SaaS, multi-user platform, or open-ended autonomous literature-review
system.

## Core Capabilities

### Paper Reading

- Read a PDF into a structured Markdown report.
- Extract contributions, methods, experiments, limitations, and cross-paper
  relationships.
- Preserve an append-only `session.jsonl` for model history and recovery.

### Local Library Retrieval

- Store structured fields in `fields.db`.
- Store cross-paper chunks and vectors in `embeddings.db` with sqlite-vec.
- Combine FTS5/BM25 and dense retrieval with RRF.
- Return stable evidence references that can be inspected after generation.
- Avoid an external vector database at personal-library scale.

### Chat-first Research Entry

- Accept a plain natural-language request.
- Let the single Paper Copilot Agent decide whether to answer directly or call
  one or more bounded tools.
- Return Markdown, session/report paths, cost, termination reason, and paper
  budget.
- Persist jobs independently of the client connection.

### Model-framework Drafts From Research Directions

Given a research direction, Paper Copilot can:

1. Select one strong baseline.
2. Search candidate modules in local-library priority order.
3. Use deterministic plan state to constrain baseline selection, module
   selection, and fallback order.
4. Analyze compatibility, attachment points, and risks.
5. Produce a baseline-plus-modules proposal with ablations and evidence.
6. Downgrade unsupported implementation details and expected gains to explicit
   hypotheses.

The result is a testable proposal, not a finished paper and not proof that the
combination will work.

### Eval and Observability

- Field-level golden regression.
- Retrieval query suites.
- Run history and a static HTML trend report.
- Local rollout traces and diagnostics.
- Cache-hit, latency, token, and CNY cost tracking.

## Quick Start

### 1. Prepare the Python development environment

```bash
git clone https://github.com/lemma42796/paper-copilot.git
cd paper-copilot
uv sync --dev
```

### 2. Configure the model and paper library

```bash
cp .env.example .env
```

Edit `.env`:

```bash
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=sk-your-key-here
LLM_MODEL=qwen3.6-flash
DASHSCOPE_API_KEY=sk-your-key-here
PAPER_COPILOT_PDF_DIR=/path/to/your/papers
```

### 3. Start the existing API and migration-period Web UI

The repository does not expose a terminal product command. A desktop host or
another Python process can start the current local API:

```python
from paper_copilot.api.http import serve_http_api

serve_http_api(host="127.0.0.1", port=8765)
```

The HTTP server listens on `8765` by default, with the job WebSocket on `8766`.
The frontend discovers the WebSocket URL through `/health`.

For Web frontend development:

```bash
cd apps/web
npm ci
npm run dev
```

Open `http://127.0.0.1:3000`.

## Configuration

`.env.example` defaults to Alibaba Cloud Bailian/DashScope's OpenAI-compatible
Chat Completions endpoint and DashScope's embedding endpoint. The LLM client can
also use DeepSeek's OpenAI-compatible endpoint.

| Variable | Purpose |
| --- | --- |
| `LLM_BASE_URL` | OpenAI-compatible LLM base URL |
| `LLM_API_KEY` | API key for the configured LLM endpoint |
| `LLM_MODEL` | Model ID; defaults to `qwen3.6-flash` |
| `DASHSCOPE_API_KEY` | Embedding key for `text-embedding-v4` |
| `PAPER_COPILOT_HOME` | Runtime data root; defaults to `~/.paper-copilot` |
| `PAPER_COPILOT_PDF_DIR` | Default local PDF library |

Indexes are synchronized when the product reads papers. Changing the embedding
model or dimension requires rebuilding the index before querying it again.

For the official DeepSeek API, change the LLM variables while keeping a
separate DashScope embedding key:

```bash
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=sk-your-deepseek-key
LLM_MODEL=deepseek-v4-flash
```

## Running

The migration-period Web UI remains available for developing and exercising
the existing product flow:

```bash
cd apps/web
npm ci
npm run dev
```

Example request:

```text
For person re-identification, choose a strong baseline, find recent compatible
modules, compose a verifiable model framework, and include ablations and
evidence references.
```

### Local MCP Server

In a development checkout, add the local `stdio` server to Codex with:

```bash
codex mcp add paper-copilot -- \
  uv --directory /absolute/path/to/paper-copilot run paper-copilot-mcp
```

The server exposes the read-only tools `library_status`, `list_papers`,
`search_papers`, `get_paper`, `inspect_evidence`, and `compare_papers`, plus
the long-running job tools `start_read_paper`, `get_job_status`,
`get_job_result`, and `cancel_job`. Search uses the existing hybrid retrieval
path when `DASHSCOPE_API_KEY` or `LLM_API_KEY` is available, and local FTS5/BM25
otherwise.

In the Codex desktop MCP server settings, add
`DASHSCOPE_API_KEY=sk-...` under environment variables, save, and restart the
server. The same variable can instead be set in the project-root `.env`.
With query embedding enabled, `search_papers` reports
`retrieval_mode=hybrid` and `query_sent_to_embedding_provider=true`.

Ordinary read-only MCP calls do not enter the Paper Copilot agent loop or invoke
the default model. The MCP host, such as Codex, interprets the request and
orchestrates tools; the server performs MCP schema validation, service-level
validation, and read-only Core calls. Only hybrid search query embedding uses
`text-embedding-v4`.

`start_read_paper` is the explicit long-running entrypoint. It accepts only the
`paper_id` of a local PDF under the configured directory, returns a job id
immediately, and starts the Paper Copilot Agent through the existing
job/attempt/recovery runtime. It spends the LLM budget reported in its response
and writes local job, session, report, and index state, but cannot modify the PDF
library. Poll incrementally with the event cursor returned by `get_job_status`,
then call `get_job_result`; `cancel_job` requests cancellation, so a later
status response is authoritative.

The tools never upload a complete PDF or session and do not return local result
paths. However, an MCP client will normally pass returned paper summaries,
evidence, and job reports to its model. Treat those returned excerpts as data
that may leave the device when using a cloud client.

## Local HTTP API

The local API deliberately uses Python's standard-library HTTP server plus
`websockets`; it does not add FastAPI.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Health check and WebSocket discovery |
| `POST` | `/jobs` | Create a persistent background job |
| `GET` | `/jobs` | List recent jobs |
| `GET` | `/jobs/<id>` | Read job status and result |
| `GET` | `/jobs/<id>/events?after=N` | Read incremental progress events |
| `GET` | `/jobs/<id>/stream?after=N` | SSE event fallback |
| `GET` | `/jobs/<id>/diagnostics` | Read local rollout diagnostics |
| `POST` | `/jobs/<id>/interrupt` | Stop the running attempt |
| `POST` | `/jobs/<id>/resume` | Create a new attempt using rollout replay |
| `POST` | `/jobs/<id>/approval` | Approve or reject a pending tool action |
| `POST` | `/chat` | Synchronous compatibility endpoint |
| `GET` | `/reports` | List legacy chat/research reports |
| `GET` | `/evidence?ref=...` | Resolve an evidence reference |
| `GET` | `/composer/library` | Preview the Composer library |
| `POST` | `/library/select-directory` | Directory picker used by the Web UI |

The WebSocket endpoint is
`ws://127.0.0.1:8766/jobs/<id>/stream?after=N`. It carries `job/events`
notifications and request/response controls for interrupt, resume, and approval.
If WebSocket is unavailable, controls fall back to HTTP and events fall back to
SSE, then polling. All transports share the same event sequence cursor.

Create a job:

```bash
curl -sS -X POST http://127.0.0.1:8765/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "Find a strong ReID baseline and 2-3 compatible modules",
    "pdf_dir": "/path/to/your/papers",
    "max_turns": 16,
    "budget_cny": 2.0,
    "max_papers": 5
  }'
```

The endpoint returns immediately with a persistent job record. The final job
result includes:

- Markdown report
- session and report paths
- quality-run and eval-report paths
- termination reason
- cost and event count
- paper budget

For a follow-up turn, pass the previous job's `spec.conversation_id` in a new
job request. Completed prior turns become controlled conversation context.
Failed or interrupted output is not added to conversation memory.

## Architecture

```text
SwiftUI macOS Client ─┐
Legacy Next.js Web UI ├─> local HTTP/job API ─> Python Paper Core
Local MCP Server ────────> read-only MCP tools ─┘

Python Paper Core
  -> persistent chat.jobs lifecycle
  -> chat.runtime.handle_chat_request()
  -> single bounded Paper Copilot loop
  -> local knowledge stores
  -> Markdown reports, JSONL traces, and eval rows
```

| Path | Responsibility |
| --- | --- |
| `src/paper_copilot/api/` | Local HTTP transport |
| `src/paper_copilot/chat/` | Chat runtime, jobs, and history |
| `src/paper_copilot/mcp/` | Local read-only `stdio` MCP server |
| `src/paper_copilot/agents/` | Paper Copilot loop and bounded tools |
| `src/paper_copilot/knowledge/` | Cross-paper indexes and hybrid search |
| `src/paper_copilot/retrieval/` | Single-paper section extraction |
| `src/paper_copilot/eval/` | Regression, retrieval eval, and reports |
| `src/paper_copilot/session/` | Append-only JSONL session storage |
| `src/paper_copilot/observability/` | Local rollout traces and diagnostics |
| `apps/macos/` | M20 SwiftUI client |
| `apps/web/` | Migration-period Next.js frontend |

See [ARCHITECTURE.md](ARCHITECTURE.md) for current technical structure and
[TASKS.md](TASKS.md) for the active milestone.

## Data Layout

Runtime data lives outside the repository by default:

```text
~/.paper-copilot/
├── papers/<paper_id>/
│   ├── source.pdf
│   ├── session.jsonl
│   ├── report.md
│   └── research-report.md
├── fields.db
├── embeddings.db
├── embeddings_meta.json
├── embedding_cache.sqlite
├── graph/cross-paper-links.jsonl
├── jobs/<job_id>/
│   ├── job.json
│   ├── events.jsonl
│   └── attempts/<n>/
│       ├── manifest.json
│       ├── trace.jsonl
│       ├── state.json
│       └── payloads/
└── eval/
    ├── runs/<run_id>.jsonl
    └── report.html
```

`paper_id = SHA1(PDF bytes)[:12]`, so renaming or moving a PDF does not change
its ID.

Repository eval assets:

```text
eval/
├── goldens/<paper_id>_<field>.json
├── retrieval/queries.yaml
└── suites/smoke.yaml
```

## Development

```bash
uv sync --dev
make lint
make typecheck
make test
```

Run validation only when it is appropriate for the current task. Project
conventions do not require proactively running every check for documentation or
small scoped changes.

Before changing the default model tier, run the smoke eval and compare quality,
cost, and latency. A previous plus-tier trial passed regression but cost 2.03x
and took 2.22x as long without a measurable quality gain, so the default remains
the flash tier.

## Roadmap

The active roadmap lives in [TASKS.md](TASKS.md).

1. M20 SwiftUI macOS Client Foundation is complete.
2. M21 Local Read-only MCP is complete.
3. Work is stopped here. Begin M22 MCP Long-running Jobs only after explicit
   user approval.

## Known Limitations

- No cloud sync, accounts, multi-user ACLs, or hosted deployment.
- During M20 development, the Python Runtime is not yet bundled into the
  `.app`; dependency-free distribution belongs to M23.
- The core runtime does not discover papers on the internet.
- Local retrieval may send selected paper fragments to the configured cloud
  model.
- The active retrieval path has no cross-encoder or LLM reranker.
- Evidence grounding remains imperfect; not every generated statement should
  be treated as fully verified.
- Some eval suites require local PDFs that are not distributed with the
  repository.

## Contributing

This is an experimental local-first research tool. Read
[AGENTS.md](AGENTS.md) before opening a pull request.

- Keep changes narrow.
- Explain user-visible behavior.
- Do not add dependencies without discussing the tradeoff first.
- Prefer traceable, evaluable harness changes over prompt-only fixes.

## License

MIT. See [LICENSE](LICENSE).
