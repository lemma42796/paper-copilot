# Chat-first Research Copilot Plan

> Created: 2026-05-18
> Updated: 2026-07-20
> Status: stable product direction. Current implementation status and open DoD
> live in `TASKS.md`.

## North Star

Paper Copilot is a local-first research assistant with one natural-language
input. It should help a researcher form **verifiable research hypotheses** by
finding evidence, selecting a strong baseline, identifying compatible modules,
and producing a bounded experiment plan.

It must not invent results, hide sources, bypass access controls, or present a
mechanical combination of papers as established novelty.

## First Principle: Harness Engineering

Build the scaffold that makes model behavior observable, bounded, recoverable,
and testable before relying on prompt cleverness.

- Every action goes through a bounded tool with explicit input, output, cost,
  latency, failure semantics, and trace entries.
- Important claims carry evidence references: paper, field or chunk, page or
  section when available, and a short snippet.
- Long workflows have max turns, papers, cost, and a visible termination reason.
- Deterministic code owns parsing, filters, retrieval, rank fusion, schema
  validation, state transitions, proposal checks, and report assembly.
- The LLM owns tool choice, bounded semantic judgment, synthesis, and hypothesis
  writing.
- Eval measures trends above the model noise floor; one stochastic run is not
  treated as immutable truth.

## Product Vocabulary

- **Paper Copilot**: the only autonomous Agent and user-facing chat entry point.
- **Research Idea Composer**: the baseline + module composition workflow.
- **Evidence-grounded RAG**: retrieval that returns stable citations and snippets.
- **Research Loop**: Paper Copilot's bounded tool loop.

Avoid product language that suggests paper laundering or automatic paper
writing. The product is for evidence-backed ideation and feasibility analysis.

## Current Runtime Shape

The user prompt goes directly to Paper Copilot. There is no keyword router,
`route`, or `task_profile`; the model decides whether to answer directly or call
tools inside one bounded loop.

Core tools are:

- `list_pdfs`
- `read_paper`
- `search_library`
- `inspect_paper`
- `compare_papers`
- `find_related_papers`
- `list_composer_library`
- `search_composer_candidates`
- `update_composer_plan`

`ReadPaperTool`, `SkimPaperTool`, `ExtractPaperTool`, and
`LinkRelatedPapersTool` are structured workers, not autonomous subagents. Their
forced tool calls are schema-constrained output channels.

The same runtime is used by the Next.js Web UI and local HTTP API. Business
logic must not be duplicated at transport boundaries.

## Evidence-grounded RAG

### Pipeline

```text
metadata and paper-id filters
+ SQLite FTS5/BM25 lexical retrieval
+ text-embedding-v4/sqlite-vec dense retrieval
-> reciprocal rank fusion
-> paper aggregation
-> per-paper evidence candidate pool
-> deterministic non-duplicate chunk selection
-> citations, snippets, and retrieval trace
```

The embedding contract is pinned in `dashscope_text_embedding.md`.

Keep SQLite at the target scale of roughly 50-100 papers. Reconsider a dedicated
vector database only when measured requirements change, such as about 10k
papers/1M chunks, concurrent multi-user access, ACLs, or server deployment.

Do not add a cross-encoder or LLM reranker until retrieval eval shows a repeatable
failure that deterministic features cannot fix.

### Evidence Contract

An evidence item should preserve enough provenance to render and inspect it:

```text
paper_id
title
year
chunk_id or structured field path
paper_rank
chunk_rank
vector_rank
bm25_rank
page_start/page_end
section
snippet
score/distance when meaningful
citation_ref
source_kind
```

Stable references include chunk refs such as `[paper_id:chunks[12]]` and field
refs such as `[paper_id:methods[0]]`. The Web UI resolves both through the same
evidence panel.

Attach evidence to contributions, methods, experiments, limitations when
available, cross-paper links, and generated research ideas.

### Retrieval Eval

Track at least:

- paper recall and precision at 5/10
- evidence recall and anchor precision at 5/10
- citation coverage and unsupported claim rate
- query latency and no-result rate

The current seed gate is recorded in `TASKS.md`. Do not repeatedly tune the same
seed set after the paper-level gate has passed. Add or audit labels when a real
miss appears.

## Research Idea Composer

### Goal

Given a user research direction and local paper library, produce:

- exactly one strong baseline with evidence for performance and a clear
  improvement opening;
- three compatible modules from three different papers;
- attachment points, required changes, compatibility analysis, risks, and
  ablations;
- citations for factual baseline/module claims;
- explicit hypotheses for unsupported implementation choices;
- a Chinese structured report by default.

The output is a testable proposal, not a full paper and not a claim that the
combination is already novel or effective.

### Local Library Contract

The primary workflow uses user-provided PDFs:

```text
papers/
  ccf_a/
  ccf_b/
  other/
```

- The baseline comes from `ccf_a`.
- Modules search `ccf_a` first, then `ccf_b`, then `other`.
- A lower-priority pool is unavailable until the previous pool is explicitly
  closed with recorded rejected candidates and reasons.
- Each module paper contributes at most one module.
- Missing or restricted papers are reported as `needs_user_pdf`; the workflow
  does not attempt to bypass paywalls.

A flat directory can act as the CCF A pool for the current local demo library.

### Baseline Selection

A baseline candidate should be:

- from a CCF A venue or journal;
- aligned with the requested field;
- a model or pipeline rather than only a dataset, survey, or pure theory;
- reproducible enough to inspect and implement;
- high-performing, because the proposal should start from a strong point;
- not “already solved”: it needs an evidence-backed weakness or story-worthy
  opening.

Recency helps only when evidence and suitability are comparable. Stop baseline
search once the top candidate is stable and additional candidates are unlikely
to change the decision.

### Module Compatibility

For every candidate record:

- module name and source paper;
- function, input/output, and insertion point;
- loss, supervision, data, or label requirements;
- claimed benefit and ablation evidence;
- compute/memory implications when stated;
- code or reproducibility status.

Compatibility asks whether shapes, modality, task setup, supervision and losses
fit; whether the module duplicates the baseline; which weakness it addresses;
and what minimal modification turns it into a falsifiable hypothesis rather than
a mechanical copy.

### Deterministic Plan and Quality Gate

`composer_plan` owns the workflow state:

```text
list library
-> search/inspect/select baseline
-> search/inspect modules in allowed pool
-> accept or reject candidates
-> close pool before fallback
-> write structured proposal when report_ready
```

Tool results expose `allowed_next_tools`, `report_ready`, and the final report
contract. The LLM may not skip deterministic pool or module-count constraints.

At the final-output boundary, the proposal checker verifies:

- Chinese report structure;
- evidence for baseline strength and improvement opening;
- exactly three accepted modules from three distinct papers;
- citation plus attachment/compatibility explanation for each module;
- valid fallback-pool closure;
- no unsupported implementation specifics presented as facts.

Metric gains, new loss combinations, complexity claims, framework names,
optimizer settings, learning rate, batch size, epochs, and similar specifics
must be directly cited or moved to `风险与缺口` as `待验证假设` / expected
observation.

### Context and Search Budget

Never put dozens of full papers into one model context. Compose over compact,
cited cards:

```text
Baseline card: performance, architecture, evidence, weaknesses
Gap card: weakness, evidence, why it matters
Module card: mechanism, attach point, evidence, cost, claimed benefit
Framework card: baseline + 3 modules + story + risks + ablations
```

Avoid a full Cartesian product. Search baseline weaknesses, collect a small set
of module candidates per weakness, score deterministically where possible, and
ask the LLM to rank only the compact shortlist.

Historical discovery budgets used up to 20 deep reads in fast mode and 30 in
deep mode. Runtime limits remain explicit and shared across baseline and module
search. At the hard limit, compose the best supported proposal with visible gaps
instead of silently reading more papers.

### Output Shape

```text
问题定义
强基线：paper, venue/year, performance evidence, improvement opening
候选模块：three modules with source and evidence
兼容性：attach point, required changes, conflicts
组合方案：bounded hypothesis, not an asserted result
实验方案：ablations and success/failure observations
风险与缺口：unsupported choices and missing evidence
证据：stable field/chunk references
```

## Optional Paper Intake

Online discovery is optional and must not block the local-first Composer. A
future bounded intake path may use:

```text
user field
-> CCF category/venue map
-> DBLP metadata
-> official CVF/OpenReview/arXiv/project pages
-> public code verification
-> open PDF validation
-> local indexing
```

Tools own HTTP status, link extraction, PDF validity, paywall/login detection,
and repository existence. The LLM only judges bounded relevance and role from
compact structured candidates. Large pages must be parsed and filtered before
anything reaches the model.

Restricted sources stop at metadata plus `needs_user_pdf`. Do not rely on a
signed-in browser session or attempt access-control bypasses.

## Web Product

The Next.js app in `apps/web/` is the primary interface. The visual direction is
macOS-style: quiet, native-feeling, restrained color, clear focus states, a
sidebar for reports, one central input, and a high-readability Markdown/evidence
view. Avoid a marketing page, dashboard-heavy layout, decorative gradients, and
nested card piles.

The local Python backend owns long-running work, cancellation boundaries,
session trace, reports, PDFs, and indexes. The frontend owns input, progress,
history, report rendering, and citation inspection.

Current baseline endpoints include health, chat, reports, evidence lookup, and
Composer library preview. Add framework dependencies only when streaming,
upload, or job management makes the stdlib HTTP boundary measurably inadequate.

## Milestone Map

| Milestone | Current meaning |
|---|---|
| M16 | Harness hardening; core gates/retry done, reproducible public eval remains |
| M17 | Bounded tool loop; useful parts absorbed into the current single Agent runtime |
| M18 | Evidence-grounded RAG; seed gate and final selector v1 complete |
| M19 | Composer; deterministic plan/checker and one clean demo complete, cross-task validation open |
| M20 | Local Web UI; shell/report/evidence experience delivered, richer jobs/upload optional |

Do not start a later slice automatically when the current DoD is met. Active
checkboxes and the next authorized slice live in `TASKS.md`.

## Interview Framing

Good framing:

> I built a local-first research copilot that combines citation-grounded RAG,
> a bounded tool-using Agent, and eval/cost observability. It reads and compares
> papers and produces evidence-backed research hypotheses with risks and
> ablation plans.

The competitive edge is the harness: deterministic tools, stable citations,
traceable state, quality gates, trend-based eval, and measured cost/latency.

## Non-goals

- multi-tenant SaaS, auth, ACLs, or cloud sync
- multi-agent negotiation or orchestration
- a dedicated vector database at personal-library scale
- automatic paywall bypassing
- writing full papers or hiding sources
- LLM-as-judge as the primary eval mechanism
- PDF chart understanding with a CV pipeline
- supporting multiple embedding models in one index
