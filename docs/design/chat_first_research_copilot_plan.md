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
+ text-embedding-v4/sqlite-vec dense retrieval
+ RRF rank fusion
+ per-paper multi-chunk aggregation
+ evidence snippets and citations
+ retrieval eval and observability
```

`text-embedding-v4` provider details are pinned in
`docs/design/dashscope_text_embedding.md`.

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
  year
  chunk_id
  paper_rank
  chunk_rank
  vector_rank
  bm25_rank
  page_start
  page_end
  section
  snippet
  score
  distance
  vector_distance
  bm25_score
  citation_ref
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
3. Use existing `sqlite-vec` + `text-embedding-v4` for semantic hits.
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

### 2026-05-22 Scope Decision

The product path should be local-first. Users may prepare PDFs in directories
such as:

```text
papers/
  ccf_a/
  ccf_b/
  other/
```

`ccf_a/` is the baseline pool and can also provide modules. `ccf_b/` and
`other/` are module-only pools. This keeps the core Research Idea Composer from
getting blocked by web page drift, paywalls, or failed downloads.

For resume/project competitiveness, keep a limited paper-intake workflow as a
separate capability, not as the required main path. The first useful intake
scope is DBLP + CVF + OpenReview + arXiv + GitHub verification. IEEE/ACM or
other restricted publisher pages should degrade to `needs_user_pdf` instead of
trying to bypass access controls.

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
-> use DBLP venue/year pages for proceedings metadata
-> open only official paper links exposed by DBLP or venue pages
-> inspect official page title/abstract/links before touching PDF
-> verify code links when exposed on the official page
-> if no code link is exposed but the paper is relevant, inspect PDF text links
-> download/index only papers that pass relevance + code + access checks
-> ask user for paywalled or missing PDFs
-> read accepted local PDFs deeply
-> compose grounded ideas
```

Online discovery should collect metadata and open-access links. It should not
try to bypass paywalls or rely on logged-in library access. When a PDF is not
available, the workflow stops cleanly and asks the user to place the PDF in a
directory.

Different venues have different official pages. The workflow should therefore
avoid hard-coding one visual page shape. Tools should enumerate links and
metadata first; the LLM should classify already-extracted candidates instead of
visually hunting for buttons.

Large DBLP pages should never be sent to the LLM as raw HTML. Cache the HTML,
parse it into structured paper entries, run title/metadata lexical or embedding
filtering, then ask the LLM to screen only the top candidate list.

```text
DBLP venue-year HTML
-> cached raw HTML
-> structured entries(title, authors, year, key, ee links, session)
-> title/metadata filter to top 50-100
-> LLM screen/rerank to top N
-> open official pages for only those N papers
```

Official page handling:

```text
official paper page
-> extract title, abstract, venue/year, all links, citation PDF metadata
-> classify links: pdf / arXiv / project / code / supplementary / dataset
-> verify code candidates
-> if verified code exists, continue candidate scoring
-> otherwise, if paper is still high-value, fetch PDF text and extract links
-> verify PDF-discovered code candidates
-> only then download/index the PDF
```

Paywall/access detection belongs in tools, not in LLM guesswork:

- direct PDF is usable when HTTP fetch succeeds, content type or body is a real
  PDF, and text extraction can recover the title/abstract region;
- publisher/login/purchase/subscription/institutional-access pages become
  `paywalled`, `login_required`, or `publisher_page_only`;
- before asking the user, try official open alternatives such as arXiv,
  OpenReview, CVF, author/project PDFs, or other links surfaced by the official
  page;
- if no open PDF is found, keep metadata and return `needs_user_pdf`.

### Tool and LLM Responsibilities

Deterministic tools own facts and IO:

- parse the CCF venue list into venue, level, area, and DBLP URL;
- fetch/cache DBLP venue-year pages;
- parse DBLP entries and official external links;
- fetch official paper pages and extract title, abstract, metadata, and links;
- extract URLs from HTML, PDF text, footnotes, and appendix text;
- verify code links by checking that a public repository exists and contains
  credible implementation files, setup instructions, or training/test scripts;
- check PDF accessibility and paywall/login states;
- download accepted PDFs into the configured local library;
- maintain per-paper status such as `accepted_candidate`, `no_code`,
  `not_relevant`, `paywalled_need_user_pdf`, `code_link_invalid`, and
  `only_dataset_or_demo`.

The LLM owns bounded semantic judgment:

- map a user research direction to likely CCF areas and venue families;
- judge topic relevance from title/abstract and compact metadata;
- classify a candidate as baseline, module, related work, or abandon;
- decide whether a high-value candidate merits opening PDF text when the page
  has no code link;
- classify extracted URLs by meaning when the anchor text is ambiguous;
- judge whether a baseline has a clear story-worthy weakness;
- judge whether a module can address that weakness;
- synthesize and rank final framework candidates with evidence references.

Qwen3.6-flash is acceptable for these bounded classification and synthesis
steps if the tools provide clean inputs. It should not be treated as a search
engine or as the component responsible for proving that a page, PDF, or GitHub
repository exists.

### Function Calling Integration Note

The DashScope Function Calling guide is useful as a workflow reference, not as
copy-paste implementation code for the current stack.

Useful parts:

- the core loop is the same: send user/context plus tool definitions, let the
  model request a tool call, execute that tool in the app, append the tool
  result to the conversation, and call the model again for the next step or
  final answer;
- tool descriptions and parameter descriptions are prompt surface. Keep them
  concise, specific, and written to help the model choose the right tool;
- tool outputs should be explicit status/evidence strings or structured JSON so
  the next model call can reason over them without guessing;
- tool count matters because tool definitions consume input tokens. Composer
  should expose a small relevant tool set instead of dumping every possible
  operation into one call;
- production safety rules apply here: deterministic tools own facts and IO,
  mutating or irreversible actions need human confirmation, and tool failure /
  timeout states must be returned visibly instead of hidden by the LLM.

Do not directly copy the OpenAI-compatible examples from that guide into this
repo's current agent path. `LLMClient` talks to DashScope through the
Anthropic-compatible endpoint, so current tools use Anthropic-style definitions:
`name`, `description`, and `input_schema`. The OpenAI/DashScope
`type: function` / `function.parameters` shape is only relevant if a future
adapter switches `LLMClient` to the Chat Completions or Responses API. If that
happens, keep the provider-specific mapping inside `LLMClient` or a narrow
adapter; agents should continue to see one stable internal tool surface.

### Baseline Selection Criteria

A baseline is the final starting point for the new framework. It can be either
one CCF A paper's whole framework or that framework's backbone/baseline plus a
small set of its own modules. A baseline candidate should usually be:

- CCF A venue or journal;
- preferably recent, with newer papers favored when evidence quality is similar;
- highly aligned with the user's field
- a model/pipeline paper, not only dataset, survey, or pure theory
- clear architecture and training details
- public code and a reproducible setup
- strong performance or strong adoption, because a high starting point makes
  downstream improvement more credible
- explicit limitations or improvement opportunities that can support a good
  research story

Do not select only by recency. A slightly older but clean and reproducible
baseline can beat a newer ambiguous paper.

The final workflow chooses one baseline, not several. Baseline search should
stop as soon as the top candidate is stable enough: CCF A, relevant, strong,
code-available, evidence-backed, and with a clear weakness to improve.

### Module Compatibility Criteria

A module is a detachable method-section component from another paper. Each
module paper can contribute at most one module. Module papers are not limited to
CCF A, but code is still required. Each module candidate needs structured
extraction:

- module name
- paper source and venue
- module function
- expected input/output
- insertion point
- training loss or extra supervision
- claimed benefit
- ablation evidence
- compute/memory cost
- code availability

Compatibility analysis asks:

- Where does this attach to the baseline?
- Do tensor shapes, modality, task setup, and supervision match?
- Does it require a new loss, new data, or new labels?
- Does it duplicate something the baseline already does?
- Is there ablation evidence that the module is not cosmetic?
- Which baseline weakness does this module address?
- What minimal modification would make it a research hypothesis rather than a
  mechanical copy?

Story quality is a first-class score, not an afterthought. A good module is not
only technically attachable; it should make a persuasive claim about why the new
framework improves the baseline and why it is meaningfully different from other
papers. Modern coding tools can help with integration, but they cannot repair a
weak research story.

### Paper Budget and Stopping Rules

Do not measure discovery by a fixed number of titles skimmed. Count only deep
paper reads: method/experiment/limitations/code analysis that consumes LLM and
PDF-processing budget. Title/abstract filtering, official page metadata checks,
and code-link verification do not count as deep reads.

Default limits:

```text
fast mode: <= 20 deep-read papers
deep mode hard limit: <= 30 deep-read papers
```

Baseline and module reads share the same budget:

```text
total_deep_read_budget = 30
baseline_final = exactly 1 paper
baseline_search_cap = 5-8 deep reads, but stop earlier when stable
module_budget = total_deep_read_budget - actual_baseline_deep_reads
```

If the baseline is fixed after 2 deep reads, the module phase can use up to 28
deep reads. If baseline search takes 6 reads, the module phase gets 24. Do not
reserve a fixed 8/20/2 split.

Stopping criteria for baseline:

- top1 is CCF A, code-available, relevant, recent enough, and strong;
- top1 has a clear weakness that can be improved into a publishable story;
- top1 is separated from top2/top3 by score or the remaining candidates are
  near-duplicates;
- additional candidates are unlikely to change the chosen baseline.

Stopping criteria for modules:

- each selected baseline weakness has at least 2-5 credible module candidates,
  or the search budget is exhausted;
- new module candidates are repeating the same mechanism family;
- adding more modules no longer changes the top framework ranking;
- the 30-paper hard limit is reached.

At the hard limit, stop discovery and compose the best available top-K
frameworks with explicit gaps. Do not silently continue reading more papers.

### Combination and Context Control

The LLM should never receive dozens of whole papers in one context. Runtime
composition should operate over compact cards and cited evidence chunks:

```text
Baseline card: title, venue, code, performance, architecture, weaknesses
Gap card: weakness, evidence, why it matters
Module card: mechanism, attach point, code, ablation, expected benefit
Framework card: baseline + 2-3 modules + story + risks + ablations
```

Avoid a full Cartesian product. Use a staged search:

```text
baseline top 1
-> baseline weaknesses top 2-4
-> module candidates per weakness
-> deterministic/story/implementation scoring
-> beam top 10-20 framework combinations
-> LLM final ranking to topK
```

Expected latency depends on library state:

- indexed papers with existing cards: about 30 seconds to 2 minutes;
- local PDFs present but not yet read: about 3 to 10 minutes;
- online discovery plus code/PDF checks: about 5 to 20+ minutes and less stable;
- paywalled sources stop at `needs_user_pdf`.

The product should therefore expose a fast local-library mode by default and a
deeper mode only when the user explicitly wants more search.

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
- `search_library(query, filters, k) -> SearchResults` with `evidence[]`
  entries carrying `paper_id`, title, pages, snippet, score/distance, paper/chunk
  rank, and a stable `citation_ref` such as `[paper_id:chunks[chunk_id]]`.
  The result remains grouped by paper, while each paper can expose several chunk
  evidence entries.
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

### Intent Routing

The backend should own coarse intent routing instead of letting a single LLM
prompt freely decide the product mode. The frontend can show examples, but the
backend remains the contract.

There are two primary modes:

- **knowledge_qa**: explain a paper, compare multiple papers, summarize a topic
  from the local library, or answer research questions with evidence.
- **framework_composer**: given a research direction, first choose a strong
  reproducible baseline, then find 2-3 compatible modules or tricks from local
  papers, then propose a verifiable model framework with ablations.

Short term, a deterministic keyword router is enough. It should recognize
explain/compare/summarize/evidence questions as `knowledge_qa`, and recognize
baseline/module/framework/innovation/ablation requests as
`framework_composer`. After routing, the LLM can plan tool calls inside the
selected bounded harness, prompt, output profile, and termination rules.

`knowledge_qa` is still one product mode, but it carries a lightweight
`task_profile` for tool-use guidance:

- `single_paper_focus`: resolve one paper, inspect it, and avoid expansion unless
  the user asks for related work.
- `fixed_set_compare`: stay inside the named paper or method set, inspect each
  target, then compare.
- `topic_survey`: search or follow links to a small evidence set, inspect each
  selected paper, then synthesize.
- `evidence_lookup`: prioritize snippets and suggested citations, separating
  hits from missing evidence.
- `claim_check`: search for supporting and conflicting evidence, then label the
  claim supported, partially supported, or unsupported by the local library.
- `experiment_extraction`: focus on methods/experiments fields such as datasets,
  metrics, baselines, training details, and ablations.
- `timeline_synthesis`: use years and method evidence to order a development
  story without comparing every possible pair.
- `gap_analysis`: focus on limitations and experiment gaps without drifting into
  framework proposal mode.

Longer term, a small LLM classifier may replace keyword matching, but it should
only classify the mode. It should not be responsible for both deciding the mode
and executing an unconstrained workflow.

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
- vector + lexical RRF fusion (v1 implemented in `knowledge.hybrid_search.search`
  when `query_text` is supplied)
- multi-chunk per-paper search results (v1: grouped `SearchResult` with
  `chunks` and per-chunk score metadata)
- citation rendering and chunk evidence lookup (`GET /evidence?ref=...`, with
  frontend click-through panel v1)
- retrieval eval metrics (v1: `eval/retrieval/queries.yaml` paper-level labels
  and `paper-copilot eval retrieval ...` for `paper_recall@5/@10`)
- RAG observability in reports

M18 can be pulled before M17 if chat exposes too much retrieval weakness. The
dependency is evidence: do not build Research Idea Composer without grounded
evidence.

### M19: Research Idea Composer

Goal: a bounded workflow for baseline + module ideation.

Deliver:

- local-library-first Composer over user-provided `ccf_a/`, `ccf_b/`, and
  `other/` PDF directories
- optional limited paper-intake path: CCF venue map, DBLP metadata, official
  page metadata, CVF/OpenReview/arXiv open PDF discovery, GitHub code
  verification, and `needs_user_pdf` for restricted sources
- baseline selector that chooses exactly one CCF A baseline and stops when the
  top candidate is stable
- module selector that uses the remaining deep-read budget, extracts at most one
  module per paper, and requires public code
- compatibility analyzer
- beam-style framework composer that avoids full Cartesian product search
- idea composer with top-K ranked proposals, citations, risks, and ablation
  checklist
- hard budget enforcement: fast mode <= 20 deep-read papers, deep mode <= 30
  deep-read papers across baseline + modules
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
