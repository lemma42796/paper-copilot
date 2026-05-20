# Paper Copilot

> Local-first research copilot for reading papers, searching a personal paper
> library, and composing evidence-grounded research notes.

![Python](https://img.shields.io/badge/python-3.12+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Code style](https://img.shields.io/badge/code_style-ruff-purple)
![Packaged with uv](https://img.shields.io/badge/packaged_with-uv-orange)

[简体中文](README.md) | English

Paper Copilot turns a small local PDF library into a searchable, traceable
research workspace. It can read papers into structured Markdown reports, index
their fields and chunks, answer questions over the local library, compare papers,
and run bounded research loops with cost and evidence traces.

The current product direction is **chat-first**: normal use starts from one
natural-language input box, backed by a local Python HTTP API and a Next.js
macOS-style web shell. The CLI remains available for indexing, debugging, eval,
and scripted workflows.

## Project Status

Status as of `TASKS.md` updated on 2026-05-19:

- CLI reading, listing, searching, comparing, reindexing, eval, and cost
  diagnostics are implemented.
- Local HTTP API is available via `paper-copilot serve`; the main runtime
  endpoint is `POST /chat`.
- `apps/web/` contains the current Next.js chat shell with library selection,
  report history, route/status display, cost display, and evidence inspection.
- The default local test library has 34 papers / 2066 chunks indexed with
  `text-embedding-v4`.
- Paper-level retrieval seed eval is strong: mean `recall@5=98.4%`,
  `recall@10=100.0%`.
- Evidence chunk selection is the known weak point: current labeled-query mean
  `evidence_recall@5=53.8%`, `evidence_recall@10=53.8%`. The system often finds
  the right paper but does not always surface the exact answer chunk.

This is not a hosted SaaS, not a multi-user system, and not an open-ended
autonomous literature reviewer. It is a local-first research assistant for a
personal library of roughly 50-100 papers.

## Features

- **Chat-first research runtime**: route a natural-language request into
  `knowledge_qa` or `framework_composer`, run a bounded tool loop, and return a
  Markdown report with session paths, cost, termination reason, and paper budget.
- **Local paper reading pipeline**: skim / deep / related agents extract
  contributions, methods, experiments, limitations, and cross-paper links.
- **Hybrid local retrieval**: metadata filters from `fields.db`, FTS5/BM25,
  `sqlite-vec` dense retrieval, RRF fusion, and multi-chunk evidence per paper.
- **Evidence inspection**: generated reports can include parseable evidence refs;
  the API and web UI can fetch the backing chunk text.
- **SQLite-only knowledge base**: no external vector database is required for the
  intended personal-library scale.
- **Eval and observability**: golden-field regression, retrieval eval, run
  history, static HTML reports, cache-hit diagnostics, latency, and CNY cost
  tracking.
- **Traceable outputs**: each run writes human-readable Markdown plus JSONL
  session traces under `~/.paper-copilot`.

## Architecture

```text
apps/web
  -> local HTTP API
  -> chat.runtime.handle_chat_request()
  -> ResearchAgent bounded tool loop
  -> knowledge stores, paper readers, reports, eval traces
```

Main modules:

| Path | Responsibility |
| --- | --- |
| `src/paper_copilot/api/` | Local stdlib HTTP API for the web shell |
| `src/paper_copilot/chat/` | Single-input routing and runtime boundary |
| `src/paper_copilot/agents/` | Reading agents and bounded research loop |
| `src/paper_copilot/knowledge/` | Cross-paper fields, embeddings, hybrid search |
| `src/paper_copilot/retrieval/` | Single-paper chunk/section utilities |
| `src/paper_copilot/eval/` | Regression, retrieval metrics, and reports |
| `src/paper_copilot/session/` | JSONL session storage |
| `apps/web/` | Next.js local chat UI |

See [ARCHITECTURE.md](ARCHITECTURE.md) for module boundaries and
[docs/design/chat_first_research_copilot_plan.md](docs/design/chat_first_research_copilot_plan.md)
for the chat-first roadmap.

## Requirements

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- Node.js 20+ for the web UI
- API keys for the configured model providers:
  - `ANTHROPIC_API_KEY` for the Anthropic-compatible LLM endpoint
  - `DASHSCOPE_API_KEY` for DashScope `text-embedding-v4`

The default LLM endpoint in `.env.example` targets Alibaba Cloud DashScope's
Anthropic-compatible API. Embeddings use DashScope's OpenAI-compatible
`text-embedding-v4` endpoint.

## Installation

Install as a CLI tool:

```bash
git clone https://github.com/lemma42796/paper-copilot.git
cd paper-copilot
uv tool install .
paper-copilot --help
```

For local development:

```bash
git clone https://github.com/lemma42796/paper-copilot.git
cd paper-copilot
uv sync --dev
uv run paper-copilot --help
```

`pc` is also registered as a short alias for `paper-copilot`.

## Configuration

```bash
cp .env.example .env
```

Edit `.env`:

```bash
ANTHROPIC_BASE_URL=https://dashscope.aliyuncs.com/apps/anthropic
ANTHROPIC_API_KEY=sk-your-key-here
DASHSCOPE_API_KEY=sk-your-key-here
PAPER_COPILOT_PDF_DIR=/path/to/your/papers
```

`PAPER_COPILOT_HOME` controls the runtime data root. If unset, data is stored in
`~/.paper-copilot`.

`PAPER_COPILOT_PDF_DIR` is used by chat/research when a request needs local PDFs.
For a fresh clone, point it at your own PDF folder and build the index with
`read` or `reindex`.

## Quick Start

Read and index one paper:

```bash
paper-copilot read path/to/paper.pdf --lang zh
```

Search the local library:

```bash
paper-copilot search "residual connections for very deep image recognition" --k 5
```

Run a bounded research request from the CLI:

```bash
paper-copilot research "对比 Transformer 和 ViT 的注意力机制演化，给出证据引用" \
  --pdf-dir /path/to/your/papers \
  --max-papers 5 \
  --budget-cny 2.0
```

Start the local API:

```bash
paper-copilot serve --host 127.0.0.1 --port 8765
```

Call the chat endpoint:

```bash
curl -sS http://127.0.0.1:8765/health
curl -sS -X POST http://127.0.0.1:8765/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"总结本地库里和 ViT attention 相关的证据","pdf_dir":"/path/to/your/papers"}'
```

Run the web shell:

```bash
cd apps/web
npm ci
npm run dev
```

Then open `http://127.0.0.1:3000`. Keep `paper-copilot serve` running in another
terminal.

## CLI Reference

| Command | Purpose |
| --- | --- |
| `read <pdf>` | Read one PDF, write `report.md`, `session.jsonl`, and update indexes |
| `research "<topic>"` | Run the chat-first bounded research loop from the CLI |
| `serve` | Start the local HTTP API for the web shell |
| `list` | List indexed papers from `fields.db` |
| `search "<query>"` | Hybrid semantic search over the local library |
| `compare <paper_id_a> <paper_id_b>` | Compare two indexed papers without an LLM call |
| `reindex` | Rebuild local indexes from session traces and optional PDFs |
| `doctor` | Inspect recent cache hit rate, latency, tokens, and cost |
| `eval mark/run/report/retrieval` | Maintain golden evals, retrieval evals, and trend reports |

Run `paper-copilot <command> --help` for full options.

## Local HTTP API

The local API is intentionally small and dependency-light.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Health check |
| `POST` | `/chat` | Run a natural-language request through `handle_chat_request()` |
| `GET` | `/reports` | List recent chat/research reports |
| `GET` | `/evidence?ref=...` | Resolve a report evidence reference to chunk text |
| `POST` | `/library/select-directory` | Desktop directory picker for the web UI |

Typical `POST /chat` body:

```json
{
  "message": "找一个 ReID strong baseline，再找 2-3 个可接入模块，给出实验计划",
  "pdf_dir": "/path/to/your/papers",
  "max_turns": 16,
  "budget_cny": 2.0,
  "max_papers": 5
}
```

The response includes route, Markdown report, session path, report path, optional
quality/eval report paths, termination reason, cost, event count, and paper
budget.

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
├── graph/cross-paper-links.jsonl
└── eval/
    ├── runs/<run_id>.jsonl
    └── report.html
```

`paper_id` is `SHA1(PDF bytes)[:12]`, so renaming or moving a PDF does not change
its identity.

Repository eval fixtures live under `eval/`:

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

Useful focused checks:

```bash
git diff --check -- README.md README.en.md
uv run pytest tests/chat/test_runtime.py tests/api/test_http.py
```

Before changing model tiers, run the smoke eval and compare both quality and
cost/latency. The current default remains the cheaper flash tier because the
documented plus-tier trial showed higher cost and latency with no measured
quality gain.

## Roadmap

Near-term work is tracked in [TASKS.md](TASKS.md). Current priority:

1. Improve evidence chunk selection without changing paper-level ranking.
2. Track evidence pool recall, final evidence recall, and evidence anchor
   precision.
3. Continue toward the M19 minimum loop for real research-idea composition once
   grounding risk is better bounded.

## Known Limitations

- No cloud sync, accounts, multi-user ACL, or hosted deployment.
- No internet paper discovery in the core runtime; it works over local PDFs and
  local indexes.
- No cross-encoder or LLM reranker in the active retrieval path.
- Evidence chunks are not yet reliable enough to treat every generated claim as
  fully grounded.
- Some eval suites depend on local PDFs that are not shipped in the repository.

## Contributing

This is an experimental local-first research tool. Before opening a pull request:

- Read [AGENTS.md](AGENTS.md) for engineering conventions and module boundaries.
- Keep changes narrow and explain user-visible behavior.
- Do not add dependencies unless the tradeoff is discussed first.
- Prefer traceable, deterministic harness improvements over prompt-only fixes.

## License

MIT. See [LICENSE](LICENSE).
