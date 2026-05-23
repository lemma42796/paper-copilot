# Paper Copilot

> Local-first research copilot for reading PDFs, searching a personal paper
> library, and composing evidence-grounded research notes and model-framework
> drafts.

![Python](https://img.shields.io/badge/python-3.12+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Code style](https://img.shields.io/badge/code_style-ruff-purple)
![Package manager](https://img.shields.io/badge/package-uv-orange)

[简体中文](README.md) | English

Paper Copilot is built for a small local library of research PDFs. It reads
papers into structured reports, builds local SQLite / sqlite-vec indexes,
answers questions over the library, compares papers, and helps turn a research
direction into a verifiable baseline + module model-framework draft.

It is not meant to invent results or write a paper for you. The goal is to keep
evidence, sources, costs, traces, and failure boundaries visible so research
ideas are easier to verify.

## Contents

- [Frontend Demo](#frontend-demo)
- [Status](#status)
- [Features](#features)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running](#running)
- [Local HTTP API](#local-http-api)
- [Data Layout](#data-layout)
- [Development](#development)
- [Roadmap](#roadmap)
- [Known Limitations](#known-limitations)
- [Contributing](#contributing)

## Frontend Demo

The screenshots below cover the main frontend surface: natural-language
research input, local-library status, report history, Research Idea Composer,
evidence lookup, and knowledge-QA reports.

### Research Workbench and Local Library

![Paper Copilot research workbench: natural-language input, report history, local-library status, and API connection status](docs/assets/paper-copilot-workbench.jpg)

### Research Idea Composer

![Paper Copilot Composer: Chinese research proposal, candidate-module table, and structured Composer summary](docs/assets/paper-copilot-composer.jpg)

### Evidence Reference Lookup

![Paper Copilot evidence panel: clicking an evidence ref in the report opens field evidence details](docs/assets/paper-copilot-evidence.jpg)

### Knowledge-QA Report

![Paper Copilot knowledge-QA report: cross-paper answer, run metadata, and report history](docs/assets/paper-copilot-qa-report.jpg)

## Status

Current status is synced from `TASKS.md`, last updated on 2026-05-23.

Paper Copilot has moved toward a local chat-first research assistant:

- The local API runs via `paper-copilot serve`; the main runtime endpoint is
  `POST /chat`.
- `apps/web/` contains a Next.js macOS-style chat shell with library selection,
  report history, route/status display, cost display, Composer summaries, and
  evidence inspection.
- Retrieval now uses DashScope `text-embedding-v4` with FTS5/BM25 + vector RRF +
  multi-chunk evidence; previously computed text embeddings are reused from a
  local cache to avoid repeated model calls.
- The current local test library contains 34 papers / 2066 chunks.
- M19 Research Idea Composer now includes local-library-first tool constraints,
  deterministic plan/state, a proposal checker, field/chunk evidence lookup, and
  Markdown table rendering in reports.
- Current validation boundary: the VI-ReID single-case demo passes the quality
  gate cleanly; the 2-3 fixed-task cross-task acceptance suite was intentionally
  skipped, so this is not claimed as stable across tasks yet.

Current retrieval gate:

| Metric | Result | Notes |
| --- | ---: | --- |
| paper `recall@5` | 98.4% | Mean over 36 seed queries |
| paper `recall@10` | 100.0% | Paper-level recall is good enough for now |
| paper `precision@5` | 32.8% | Relevant papers among topK |
| paper `precision@10` | 16.9% | Expected to drop as topK expands |
| evidence `recall@5` | 87.2% | Mean over 13 anchor-labeled queries; exact + semantic window match |
| evidence `recall@10` | 89.7% | Evidence chunk coverage remains a known grounding risk |
| evidence anchor `precision@5` | 44.9% | Anchor/semantic-window hit metric, not full relevance |
| evidence anchor `precision@10` | 45.3% | Same metric boundary; unlabeled chunks are not full relevance judgments |

This is still an experimental, local-first, personal-library tool. The intended
scale is roughly 50-100 papers, not a hosted SaaS, multi-user platform, or
open-ended autonomous literature reviewer.

## Features

### Paper Reading

- Read a PDF into a structured Markdown report.
- Extract contributions, methods, experiments, limitations, and cross-paper
  links.
- Preserve `session.jsonl` for LLM calls, schema outputs, traces, and costs.

### Local Library Retrieval

- Store structured fields in `fields.db`.
- Store cross-paper chunks in `embeddings.db` with `sqlite-vec`.
- Return relevant papers and evidence chunks with FTS5/BM25 + dense retrieval +
  RRF fusion.
- Avoid external vector databases for the intended personal-library scale.

### Chat-first Research Entry

- Accept a natural-language request.
- Route it to `knowledge_qa` or `framework_composer`.
- Return Markdown, route, session/report paths, cost, termination reason, and
  paper budget.

### Model-framework Drafts From Research Directions

Given a research direction, Paper Copilot can:

1. Select a strong baseline.
2. Search candidate modules with a CCF A -> CCF B -> Other local-library-first
   priority.
3. Use deterministic Composer plan/state to constrain baseline selection, module
   selection, and fallback order.
4. Analyze compatibility, attachment points, and risks.
5. Compose a baseline + modules model-framework draft with ablations and
   evidence citations.
6. Use a proposal checker to catch unsupported metric gains, training
   hyperparameters, complexity changes, and similar claims, then downgrade
   uncertain content into hypotheses.

The output is a verifiable research draft, not a finished paper and not proof of
effectiveness.

### Eval and Observability

- Field-level golden regression.
- Retrieval query suites.
- Run history and static HTML trend reports.
- Cache-hit, latency, token, and CNY cost diagnostics.

## Quick Start

### 1. Install the local backend

```bash
git clone https://github.com/lemma42796/paper-copilot.git
cd paper-copilot
uv tool install .
```

For local development:

```bash
uv sync --dev
```

### 2. Configure models and your paper folder

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

### 3. Run the local API and web UI

Terminal 1:

```bash
paper-copilot serve --host 127.0.0.1 --port 8765
```

Terminal 2:

```bash
cd apps/web
npm ci
npm run dev
```

Open `http://127.0.0.1:3000`.

## Installation

Requirements:

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- Node.js 20+ for the web UI
- DashScope / Bailian API keys

Install:

```bash
git clone https://github.com/lemma42796/paper-copilot.git
cd paper-copilot
uv tool install .
```

Reinstall current code:

```bash
uv tool install . --reinstall
```

Development mode:

```bash
uv sync --dev
```

## Configuration

`.env.example` defaults to Alibaba Cloud Bailian / DashScope's
Anthropic-compatible LLM endpoint and OpenAI-compatible embedding endpoint.

| Variable | Purpose |
| --- | --- |
| `ANTHROPIC_BASE_URL` | LLM endpoint; defaults to Bailian's Anthropic-compatible API |
| `ANTHROPIC_API_KEY` | LLM API key |
| `DASHSCOPE_API_KEY` | Embedding key for `text-embedding-v4` |
| `PAPER_COPILOT_HOME` | Runtime data root; defaults to `~/.paper-copilot` |
| `PAPER_COPILOT_PDF_DIR` | Default local PDF folder for chat/research |

For a new environment, point `PAPER_COPILOT_PDF_DIR` at your paper folder. If
you already have previous sessions, rebuild indexes from those sessions plus the
PDF folder:

```bash
paper-copilot reindex --pdf-dir /path/to/your/papers
```

## Running

The web UI is the current product entry:

```bash
paper-copilot serve --host 127.0.0.1 --port 8765
cd apps/web
npm ci
npm run dev
```

Example prompt:

```text
For person re-identification, choose a strong baseline, find recent pluggable
modules, compose a verifiable new model framework, and include ablations and
evidence citations.
```

## Local HTTP API

The local API intentionally stays lightweight. It uses Python's stdlib HTTP
server and does not add FastAPI.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Health check |
| `POST` | `/chat` | Run a natural-language request |
| `GET` | `/reports` | List recent chat/research reports |
| `GET` | `/evidence?ref=...` | Resolve an evidence ref to chunk text |
| `POST` | `/library/select-directory` | Desktop directory picker for the web UI |

`POST /chat` example:

```bash
curl -sS -X POST http://127.0.0.1:8765/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "find a ReID strong baseline, then 2-3 compatible modules and an experiment plan",
    "pdf_dir": "/path/to/your/papers",
    "max_turns": 16,
    "budget_cny": 2.0,
    "max_papers": 5
  }'
```

The response includes:

- route / task profile
- Markdown report
- session path / report path
- quality run path / eval report path
- termination reason
- cost
- events count
- paper budget

## Architecture

```text
apps/web
  -> local HTTP API
  -> chat.runtime.handle_chat_request()
  -> ResearchAgent bounded tool loop
  -> local knowledge stores
  -> Markdown reports + JSONL traces + eval rows
```

Main modules:

| Path | Responsibility |
| --- | --- |
| `src/paper_copilot/api/` | Local HTTP API |
| `src/paper_copilot/chat/` | Single-input routing and runtime |
| `src/paper_copilot/agents/` | Reading agents and research loop |
| `src/paper_copilot/knowledge/` | Cross-paper indexes and hybrid search |
| `src/paper_copilot/retrieval/` | Single-paper chunk / section utilities |
| `src/paper_copilot/eval/` | Regression, retrieval eval, and reports |
| `src/paper_copilot/session/` | JSONL session storage |
| `apps/web/` | Next.js local frontend |

See [ARCHITECTURE.md](ARCHITECTURE.md) and the
[chat-first roadmap](docs/design/chat_first_research_copilot_plan.md) for more
detail.

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
└── eval/
    ├── runs/<run_id>.jsonl
    └── report.html
```

`paper_id = SHA1(PDF bytes)[:12]`, so renaming or moving a PDF does not change
its ID. `embeddings.db` stores paper-library chunk vectors; `embedding_cache.sqlite`
stores reusable vectors for queries, evidence anchors, semantic windows, and
similar text keyed by model and dimension.

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

For docs-only changes:

```bash
git diff --check -- README.md README.en.md
```

Before changing the default model tier, run the smoke eval and compare both
quality and cost/latency. The previous plus-tier trial passed regression, but
cost was about 2.03x and latency about 2.22x with no measured quality gain, so
the default remains the flash tier.

## Roadmap

Near-term work is tracked in [TASKS.md](TASKS.md).

Current priorities:

1. Freeze the current feature surface and focus on README, demo screenshots, and
   resume-ready project framing.
2. Keep the local-library-first Composer ReID demo easy to show, while naming the
   cross-task generalization boundary clearly.
3. If development continues, add fixed Composer task acceptance, frontend
   retrieval miss/top-k diagnostics, and manual unsupported-claim sampling.

## Known Limitations

- No cloud sync, accounts, multi-user ACL, or hosted deployment.
- No internet paper discovery in the core runtime; it works from local PDFs and
  local indexes.
- No cross-encoder or LLM reranker in the active retrieval path.
- Evidence grounding is still a known risk; generated claims are not all fully
  grounded yet.
- Research Idea Composer currently has one clean VI-ReID demo, but no multi-task
  stability acceptance suite.
- Some eval suites depend on local PDFs that are not shipped with the repository.

## Contributing

This is an experimental local-first research tool. Please read
[AGENTS.md](AGENTS.md) before opening a pull request.

Basic principles:

- Keep changes narrow.
- Explain user-visible behavior.
- Do not add dependencies without discussing the tradeoff first.
- Prefer traceable, evaluable harness improvements over prompt-only fixes.

## License

MIT. See [LICENSE](LICENSE).
