# Chat-first Research Copilot Plan

> Created: 2026-05-18
>
> Status: planning document. This is the product and architecture direction
> after M15. It does not replace `TASKS.md`; it explains the shape of the next
> milestones so implementation can stay disciplined.

## North Star

Paper Copilot should evolve from a command-line paper reader into a
chat-first research assistant:

- one natural-language input box for normal users
- deterministic tools behind the agent, not a giant prompt
- grounded outputs with citations, evidence snippets, and failure reasons
- local-first storage and reproducible traces
- no hidden academic laundering: every baseline, module, and idea keeps its
  source and risk visible

The product should help a researcher form **verifiable research hypotheses**:
find a strong baseline, identify compatible modules from recent papers, suggest
small modifications, and produce an experiment checklist. It should not invent
results, hide sources, or frame stitched ideas as original work.

## First Principle: Harness Engineering

The first principle is **Harness Engineering**: build the scaffold that makes
model behavior observable, bounded, recoverable, and testable before relying on
prompt cleverness.

Concretely:

- Every agent action must go through a bounded tool with explicit input,
  output, cost, latency, failure mode, and trace entry.
- Every important claim must be backed by evidence: `paper_id`, page range,
  section, and short snippet.
- Every long workflow must have budgets: max turns, max papers, max sections,
  max cost, and clear termination reasons.
- Eval comes before trust. A new agent flow needs at least a small suite that
  checks task success, evidence coverage, unsupported claim rate, and cost.
- Deterministic code owns what it can: CCF venue parsing, metadata filters,
  BM25/FTS, vector retrieval, ranking fusion, schema validation, and report
  assembly.
- The LLM plans, summarizes, judges compatibility, and writes hypotheses, but
  the harness records and constrains what happened.
- If a field is noisy, measure trend over runs rather than pretending one run is
  ground truth.

This keeps the project from becoming a pile of prompts. The strongest interview
story is not "the model is smart"; it is "the system makes a smart model useful,
auditable, and cheap enough to run."

## Scope Vocabulary

Use these names in docs, code, and interviews:

- **Paper Copilot Chat**: the single natural-language user entry point.
- **Research Idea Composer**: the baseline + module composition workflow.
- **Evidence-grounded RAG**: retrieval that returns citations and snippets, not
  just chunks.
- **Research Loop**: the agentic planner/controller that calls tools until a
  bounded research task completes or stops with a reason.

Avoid product language like "water a paper" or "paper stitching神器" in code,
docs, README, and interview slides. The user-facing framing is research ideation
and feasibility analysis.

## RAG Upgrade

Current state is a local semantic-search MVP:

```text
fields.db filter -> sqlite-vec KNN -> best chunk per paper
```

The target is a small-scale enterprise-style RAG pipeline:

```text
metadata filters
+ FTS5/BM25 keyword retrieval
+ bge-m3/sqlite-vec dense retrieval
+ RRF rank fusion
+ per-paper multi-chunk aggregation
+ evidence snippets and citations
+ retrieval eval and observability
```

### Why Not a Dedicated Vector Database Yet

Do not switch to Qdrant, Milvus, Pinecone, OpenSearch, or Azure AI Search just
to look enterprise. The project target remains local-first and small: roughly
50-100 papers. The current bottleneck is not vector scale; it is evidence,
hybrid retrieval quality, eval, and agent workflow.

Use SQLite until at least one of these becomes true:

- more than 10k papers or about 1M chunks
- multi-user concurrent access
- server-side ACL or tenant isolation
- managed cloud deployment is a requirement
- measured SQLite retrieval latency misses the product target

If migration becomes necessary, prefer a path that preserves the same retrieval
contract first. Candidates can be evaluated later: Postgres + pgvector for a
simple service, or OpenSearch/Azure AI Search for search + vector + ACL in one
platform.

### Evidence Schema

Add a reusable evidence reference shape before advanced agent work:

```text
EvidenceRef
  paper_id
  title
  page_start
  page_end
  section
  snippet
  source_kind: pdf_text | metadata | user_supplied
```

Attach evidence to:

- contributions
- methods
- experiments
- limitations when available
- cross-paper links
- generated research ideas

Reports should render citations inline:

```text
Residual shortcuts reduce degradation in very deep CNNs [ResNet, p.3].
```

### Retrieval Algorithm

First version:

1. Use `fields.db` for metadata filters: year, venue, CCF level, field,
   paper_id set.
2. Use SQLite FTS5 over chunk text for BM25-style lexical hits.
3. Use existing `sqlite-vec` + `bge-m3` for semantic hits.
4. Fuse FTS and vector ranks with RRF instead of score calibration.
5. Return top papers with top 2-3 non-duplicate chunks per paper.
6. Render chunk page/section/snippet in CLI, chat, reports, and trace.

Reranking is a later step. Start with deterministic rerank features if needed:
section weight, keyword overlap, vector rank, BM25 rank, recency, and duplicate
penalty. Do not add a cross-encoder or LLM reranker until retrieval eval shows a
real need.

### Retrieval Eval

Add a tiny retrieval suite before changing ranking repeatedly:

```yaml
queries:
  - query: "residual connections for very deep image recognition"
    expected_papers: ["resnet_id"]
    expected_terms: ["residual", "identity shortcut"]
```

Track:

- recall@5
- precision@5
- MRR
- expected term/snippet hit rate
- citation coverage
- unsupported claim rate
- query latency p50/p95
- no-result rate

This is the guardrail for future ranking changes.

## Research Idea Composer

Goal: given a user research field, suggest one strong baseline and 2-3
compatible modules from recent papers, then propose small, testable modifications
and an experiment plan.

This is a serious RAG + agent workflow. It should not output a full paper or
fake novelty. It outputs:

- baseline paper and why it is a good baseline
- candidate modules from different papers
- compatibility analysis for each module
- a proposed combined model sketch
- small modification ideas
- risks, likely failure modes, and required ablations
- citations for every baseline/module claim
- missing PDFs or paywalled sources the user must provide

### Discovery Flow

The CCF PDF is a venue whitelist, not a paper database.

Observed source context:

- The inspected local file is
  `/Users/a123/Documents/reid/第七版中国计算机学会推荐国际学术会议和期刊目录（正式版）.pdf`.
- It is the 2026 CCF recommended international conference/journal list.
- It has 72 pages and is machine-readable with `pdftotext -layout`.
- Its URLs are mostly DBLP venue pages, which are more stable for metadata
  discovery than conference homepages.
- For the AI category, A-level conferences include AAAI, NeurIPS, ACL, CVPR,
  ICCV, ICML, and ICLR. For vision-heavy deep learning topics such as
  person re-identification, likely first-pass venues are CVPR, ICCV, TPAMI,
  IJCV, ACM MM, and sometimes ICLR/NeurIPS/ICML depending on method style.

```text
user field
-> map to CCF category and A-level venues
-> use DBLP/venue pages/OpenReview/CVF/ACL Anthology/arXiv for recent metadata
-> find candidate baseline papers and module papers
-> download open PDFs when allowed
-> ask user for paywalled PDFs
-> read local PDFs deeply
-> compose grounded ideas
```

Online discovery should collect metadata and open-access links. It should not
try to bypass paywalls or rely on logged-in library access. When a PDF is not
available, the workflow stops cleanly and asks the user to place the PDF in a
directory.

### Baseline Selection Criteria

A baseline candidate should usually be:

- CCF A venue or journal, preferably from the last 1-2 years
- highly aligned with the user's field
- model/pipeline paper, not only dataset, survey, or pure theory
- clear architecture and training details
- strong public baseline or reproducible setup
- ideally has code, ablations, or enough implementation detail

Do not select only by recency. A slightly older but clean and reproducible
baseline can beat a newer ambiguous paper.

### Module Compatibility Criteria

Each module candidate needs structured extraction:

- module name
- paper source and venue
- module function
- expected input/output
- insertion point
- training loss or extra supervision
- claimed benefit
- ablation evidence
- compute/memory cost
- code availability if found

Compatibility analysis asks:

- Where does this attach to the baseline?
- Do tensor shapes, modality, task setup, and supervision match?
- Does it require a new loss, new data, or new labels?
- Does it duplicate something the baseline already does?
- Is there ablation evidence that the module is not cosmetic?
- What minimal modification would make it a research hypothesis rather than a
  mechanical copy?

### Output Contract

Output should look like:

```text
Baseline: <paper>, <venue/year>
Why: <grounded reason with citations>

Module 1: <module>, from <paper>
Attach point: <baseline component>
Required changes: <concrete integration>
Small modification idea: <bounded change>
Evidence: <page/snippet refs>
Risks: <failure modes>
Ablations: baseline / +module / +modified module
```

## Chat-first UX

The user-facing product should have one natural-language input box. CLI commands
remain for developers and tests, but normal use should be:

```text
"Read this PDF in Chinese."
"Find recent CCF A papers for person re-identification."
"Suggest one baseline and three compatible modules for my re-id topic."
"Compare these two papers."
"Which papers in my library use contrastive learning?"
```

The chat agent should translate natural language into tool calls, not replace
tools with free-form prompting.

### 2026-05-18 Frontend Decision

The product frontend should be a Next.js app, not a static HTML prototype.
The CLI remains a developer/debug shell only. Normal users should type a
natural-language request directly into the web UI, for example:

```text
基于 diffusion model 和医学图像分割，帮我找一个可做的创新点
```

The visual style is a hard product requirement: **macOS-style UI**. Keep it
quiet, native-feeling, and work-focused: a clean sidebar, top/bottom toolbar,
subtle translucent/light surfaces where useful, sharp typography, restrained
color, clear focus states, and polished Markdown/report reading. Avoid
marketing-page composition, dashboard-heavy layouts, oversized hero sections,
decorative gradients/orbs, and nested card piles.

Use the existing Python backend as the local service:

```text
GET  /health
POST /chat
```

Recommended frontend location: `apps/web/`.

### Terminal First

Historical note: the original plan said to prove the flow through a terminal
chat first:

```bash
paper-copilot chat
```

That has been superseded by the implemented backend route:
`paper-copilot serve` + `POST /chat` + `handle_chat_request()`. Do not spend
more roadmap time designing a new terminal chat product shell unless needed for
debugging.

### Tool Surface

Wrap existing commands into stable core tools:

- `read_paper(pdf_path, lang, force) -> PaperSummary`
- `search_library(query, filters, k) -> SearchResults`
- `compare_papers(a, b) -> Comparison`
- `reindex_library(pdf_dir) -> ReindexSummary`
- `doctor() -> HealthSummary`
- `ccf_find_venues(field, level) -> VenueCandidates`
- `discover_papers(field, venues, years) -> PaperCandidates`
- `compose_research_idea(field, pdf_dir, budget) -> IdeaReport`

The CLI, terminal chat, backend, and future frontend should call the same tool
surface. Avoid duplicating business logic in command handlers.

## Backend And Frontend

Current sequence after the 2026-05-18 decision:

1. Chat runtime and local HTTP API. Done: `handle_chat_request()` and
   `paper-copilot serve` expose `POST /chat`.
2. Next.js single-page chat frontend in `apps/web/`.
3. Streaming/job progress after the basic UI can submit and render results.
4. PDF upload/path entry and richer citation/report viewer.

### Backend Responsibilities

The backend owns long-running work:

- receive user messages
- run the chat planner and tool executor
- stream progress and final responses
- manage jobs and cancellation
- persist session trace
- manage local PDFs and indexes
- expose report and citation artifacts

Candidate API surface:

```text
POST /chat
GET  /events/{job_id}
POST /upload
GET  /papers
GET  /jobs/{job_id}
POST /jobs/{job_id}/cancel
```

Do not introduce a backend framework without an explicit dependency decision.
FastAPI is a reasonable candidate later, but terminal chat should come first.
As of 2026-05-18 the local backend exists without FastAPI, using the stdlib HTTP
server. Revisit framework choice only when streaming, cancellation, or upload
complexity makes the stdlib boundary too limiting.

### Frontend Responsibilities

The frontend should stay small and product-focused:

- one chat input
- conversation history
- PDF upload or local path entry
- streaming tool progress
- collapsible tool trace
- citation/snippet viewer
- report preview

No dashboard-heavy UI in the first version. The product promise is a chat-first
research workflow, not an analytics console.

Next.js first screen:

- macOS-style local app shell, not a landing page
- left sidebar for recent sessions/reports
- central composer plus Markdown report
- compact metadata surface for route, cost, paper budget, session/report/eval
  paths
- no login, cloud sync, multi-user controls, or marketing content

## Milestone Shape

### M16: Harden The Harness

Do before new product features:

- ruff/mypy/pytest green
- schema retry/fallback
- safe `read --force` via temp output then replace on success
- evidence references in schemas and reports
- retrieval eval seed suite
- agent/tool observability in `doctor` or `eval report`
- reproducible smoke demo and README story

### M17: Chat-first Tool Harness

Goal: one natural-language terminal entry point over existing deterministic
tools.

Deliver:

- tool registry over read/search/compare/reindex/doctor
- simple intent router
- bounded planner/controller loop
- streaming progress
- session trace for chat turns and tool calls
- max turns, max cost, max papers
- clear ask-user behavior when required input is missing

### M18: Evidence-grounded RAG

Goal: move from vector-search MVP to citation-grade RAG.

Deliver:

- FTS5/BM25 chunk index
- vector + lexical RRF fusion
- multi-chunk per-paper search results
- citation rendering
- retrieval eval metrics
- RAG observability in reports

M18 can be pulled before M17 if chat exposes too much retrieval weakness. The
dependency is evidence: do not build Research Idea Composer without grounded
evidence.

### M19: Research Idea Composer

Goal: a bounded workflow for baseline + module ideation.

Deliver:

- CCF PDF parser or cached venue map
- field-to-venue recommendation
- DBLP/open metadata discovery
- open PDF discovery; paywalled PDFs delegated to the user
- baseline selector
- module selector
- compatibility analyzer
- idea composer with citations, risks, and ablation checklist
- 2-3 fixed demo tasks with human acceptance notes

### M20: Local Web UI

Goal: same agent, nicer shell.

Deliver:

- local backend for jobs and streaming
- Next.js single-page chat frontend with macOS-style UI
- PDF upload/path entry
- tool trace viewer
- citation/report viewer

The first M20 slice is no longer mere presentation polish: it is the product
entry point. Keep scope tight, but start from the Next.js shell now that the
runtime and HTTP API are available.

## Interview Story

Good framing:

```text
I built a local-first research copilot that combines citation-grounded RAG,
bounded tool-using agents, and eval/cost observability. It can read papers,
search a local library, compare works, and generate evidence-backed research
hypotheses such as baseline-module combinations, with risks and ablation plans.
```

Avoid:

```text
It helps users quickly stitch papers together and write a new paper.
```

The competitive edge is the harness:

- deterministic tools instead of prompt-only demos
- grounded citations instead of unsupported summaries
- eval trends instead of one-off screenshots
- cost/latency/cache tracking
- graceful handling of missing PDFs and paywalls
- local-first reproducibility

## Non-goals For Now

- multi-tenant SaaS
- ACL/security trimming
- dedicated vector database
- automatic paywall bypassing
- writing full papers for users
- hiding sources or polishing stitched ideas as original contributions
- LLM-as-judge as the primary eval mechanism
- large frontend before terminal chat and evidence are solid
