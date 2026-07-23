# Paper Copilot

> A local-first research assistant for reading PDFs, searching a personal paper
> library, and producing evidence-grounded notes and testable model-framework
> drafts.

![Python](https://img.shields.io/badge/python-3.12+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Code style](https://img.shields.io/badge/code_style-ruff-purple)
![Package manager](https://img.shields.io/badge/package-uv-orange)

[简体中文](README.md) | English

Paper Copilot targets personal libraries of roughly 50–100 papers. It turns
PDFs into structured reports, builds local SQLite/sqlite-vec indexes, and
supports paper Q&A, cross-paper search, comparison, and research-proposal
composition through a macOS client or MCP.

PDFs, indexes, sessions, reports, and traces remain local by default. Text
fragments selected by local retrieval may be sent to a user-configured cloud
model. “The PDF is not uploaded” does not mean that no paper content leaves the
device.

## Status

Current product surfaces:

- **SwiftUI macOS client:** paper folders, model configuration, persistent
  jobs, conversations, reports, interruption/recovery, and diagnostics.
- **Local MCP Server:** six read-only paper tools and four long-running job
  tools.
- **Python Core:** Agent, PDF parsing, hybrid retrieval, sessions, job
  recovery, eval, and observability.

M20–M24 are complete, including a self-contained Apple Silicon app, a
development-preview DMG, and retirement of the old Next.js UI. Developer ID
signing and notarization are deferred until public release. See
[TASKS.md](TASKS.md).

## Capabilities

- Extract contributions, methods, experiments, limitations, and cross-paper
  relationships from PDFs.
- Search the local library with FTS5/BM25, `text-embedding-v4`, sqlite-vec,
  and reciprocal-rank fusion.
- Let one bounded Paper Copilot loop select reading, retrieval, comparison,
  and Composer tools.
- Compose a baseline, compatible modules, risks, ablations, and evidence into
  a testable research draft.
- Preserve recovery and diagnostic evidence in append-only sessions,
  persistent job attempts, rollout replay, and local traces.
- Gate model changes with field goldens, retrieval suites, and cost/latency
  trends.

The output is a research draft, not a finished paper or proof that a proposed
combination will work.

## Quick Start

Development requires Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and a
supported model API key.

```bash
git clone https://github.com/lemma42796/paper-copilot.git
cd paper-copilot
uv sync --dev
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

For source development, open the project in Xcode:

```bash
open apps/macos/PaperCopilot.xcodeproj
```

The client starts the Python Runtime on a dynamic local port. Distribution
builds bundle the Runtime, so end users do not need Python, uv, or Node.js.

## Build the macOS Preview

```bash
./scripts/build_macos_dmg.sh
open dist/macos/PaperCopilot-arm64.dmg
```

The default artifact uses ad-hoc signing. macOS will block a downloaded build
from an unidentified developer. After verifying the source, try opening it
once, then use **System Settings → Privacy & Security → Open Anyway**. Do not
disable Gatekeeper globally.

For Developer ID signing and notarization:

```bash
PAPER_COPILOT_SIGN_IDENTITY="Developer ID Application: Example (TEAMID)" \
PAPER_COPILOT_NOTARY_PROFILE="paper-copilot-notary" \
./scripts/build_macos_dmg.sh
```

The notarytool profile must already exist in Keychain. Certificates and Apple
credentials are never stored in the repository.

## Configuration

| Variable | Purpose |
| --- | --- |
| `LLM_BASE_URL` | OpenAI-compatible LLM endpoint |
| `LLM_API_KEY` | LLM API key |
| `LLM_MODEL` | Model ID; defaults to `qwen3.6-flash` |
| `DASHSCOPE_API_KEY` | Key for `text-embedding-v4` |
| `PAPER_COPILOT_HOME` | Data root; defaults to `~/.paper-copilot` |
| `PAPER_COPILOT_PDF_DIR` | Local PDF directory |

The macOS client stores LLM keys in
`~/Library/Application Support/PaperCopilot/auth.json` with `0600` file
permissions. Existing Keychain credentials are not migrated; enter each API key
once in model settings after upgrading. Changing the embedding model or
dimension requires rebuilding the index.

To use the official DeepSeek API, replace the three LLM variables. Embeddings
still use a separate `DASHSCOPE_API_KEY`.

## Local MCP Server

Add a development checkout to Codex:

```bash
codex mcp add paper-copilot -- \
  uv --directory /absolute/path/to/paper-copilot run paper-copilot-mcp
```

Read-only tools:

```text
library_status  list_papers  search_papers
get_paper       inspect_evidence  compare_papers
```

Long-running tools:

```text
start_read_paper  get_job_status  get_job_result  cancel_job
```

Search uses hybrid retrieval when an embedding key is available and local
FTS5/BM25 otherwise. Ordinary read-only tools do not enter the Agent loop.
`start_read_paper` spends an LLM budget and writes local job, session, report,
and index state.

MCP does not return complete PDFs, sessions, or local result paths. A cloud MCP
host will normally receive returned summaries, evidence, and reports, so treat
that content as data that may leave the device.

## Local HTTP API

The local HTTP API is an internal boundary for the macOS Runtime:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Health check |
| `POST/GET` | `/jobs` | Create or list jobs |
| `GET` | `/jobs/<id>` | Status and result |
| `GET` | `/jobs/<id>/events?after=N` | Incremental events |
| `GET` | `/jobs/<id>/stream?after=N` | SSE |
| `GET` | `/jobs/<id>/diagnostics` | Attempt diagnostics |
| `POST` | `/jobs/<id>/interrupt` | Stop a job |
| `POST` | `/jobs/<id>/resume` | Create a recovery attempt |
| `POST` | `/jobs/<id>/approval` | Tool approval |

Client disconnection does not stop a job. Recovery reconstructs history from
the persistent rollout; it does not resume an old network stream or model
token.

## Architecture

```text
SwiftUI macOS Client ──► local HTTP/job API ──┐
Local MCP Server ──────► MCP services ─────────┤
                                               ▼
                                       Python Paper Core
```

Core contains one Paper Copilot loop, persistent jobs, JSONL sessions, SQLite
knowledge stores, rollout traces, and eval. See
[ARCHITECTURE.md](ARCHITECTURE.md) for module ownership, dependency rules,
model policy, and data flows.

## Data

Runtime data lives under `~/.paper-copilot/` by default:

```text
papers/<paper_id>/          # PDF, session, report
jobs/<job_id>/              # job, events, attempt traces
fields.db                   # structured fields
embeddings.db               # FTS5 + sqlite-vec chunks
embedding_cache.sqlite      # embedding cache
graph/                      # cross-paper relationships
eval/                       # local eval results
```

`paper_id = SHA1(PDF bytes)[:12]`, so renaming or moving a PDF does not change
its ID.

## Development

```bash
uv sync --dev
make lint
make typecheck
make test
```

Follow [AGENTS.md](AGENTS.md) when deciding which validation to run. Before
changing the default model, run the smoke eval and compare quality, cost, and
latency.

## Limitations

- The development preview supports Apple Silicon only, uses ad-hoc signing,
  and is not notarized.
- No accounts, cloud sync, multi-user ACLs, or hosted deployment.
- Core does not discover papers online; it only processes local PDFs and
  indexes.
- The active retrieval path has no cross-encoder or LLM reranker.
- Evidence grounding can be incomplete; generated claims require review.
- Some eval suites depend on local PDFs that are not distributed.

## Contributing

Read [AGENTS.md](AGENTS.md) before contributing. Keep changes narrow, do not add
dependencies without discussion, and prefer traceable, evaluable harness
improvements.

## License

MIT. See [LICENSE](LICENSE).
