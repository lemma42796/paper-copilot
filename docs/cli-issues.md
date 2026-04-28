# CLI open issues (2026-04-28)

Findings from a manual end-to-end test of all 8 subcommands. None block
functionality. This doc is the unfixed remainder; the fixed ones rode in
on the same session's commits.

---

## 1. 6 papers in pre-M14 session format show 0 calls in `doctor`

**Symptom.** `pc doctor --n 50` lists 6 of 13 papers with
`calls=0, cost=0, latency=0` while their reports are otherwise
healthy (readable, searchable, comparable).

**Root cause.** Sessions written 2026-04-24 use the old event format
(`final_output`, `message`, `tool_use`, ...) with **no `llm_call`
events**. M14 (2026-04-25) introduced `llm_call` as the source for
token / cache / latency telemetry; doctor reads only that event type.

**Affected paper_ids.** `510d98681e5e` (Hypergraph NN) ·
`9f53740cc80e` (Learning with Hypergraphs, Zhou 2006) ·
`c2c0252624f0` (Triplet Loss ReID) ·
`d3f587797f95` (LeNet) · `8533b7bdd635` (FaceNet) ·
`b350b567b13a` (Bag of Tricks ReID).

**Fix options.**
- A. `pc read --force <pdf>` × 6 (≈ ¥0.30 total) — fresh new-format
  sessions, full telemetry restored.
- B. Make doctor filter sessions with no `llm_call` events (purely
  cosmetic; the reports are not broken, only the observability gap).

**Recommendation.** B. The reports work; only telemetry is missing.
Cosmetic filter is cheaper than re-running.

---

## 2. 2 papers have a stray `meta.id` field; 1 has real data loss

**Symptom.** `pc list --format json` shows:
- `510d98681e5e` Hypergraph: `arxiv_id="1809.09401"` AND `id="1809.09401"` — pure duplicate, harmless.
- `b350b567b13a` Bag of Tricks: `arxiv_id=null` AND `id="arXiv:1903.07071v3"` — **real data loss**. The LLM put the arxiv id under `id` (not in schema) and left `arxiv_id` null.

**Root cause.** Historical residue from before
`PaperMeta.model_config = ConfigDict(extra="forbid")`
(`schemas/paper.py:31`). Current schema rejects extra fields; new
reads cannot reproduce.

**Fix.** Either `pc read --force` the two papers, or write a one-shot
migration that folds `meta.id` into `meta.arxiv_id` when the latter
is null then drops `meta.id`. Two rows make migration low-leverage —
`--force` is simpler.

---

## 3. `search` returns fewer results than `--k` when chunk pool is too small

**Symptom.**
- `pc search "residual connection" --k 5` → 2 papers.
- `pc search "attention without softmax"` (`k=10` default) → 4 papers.

**Root cause.** `knowledge/hybrid_search.py` pulls `k × overfetch`
chunks (default `overfetch=5`) and groups by paper. If the top
`k × overfetch` chunks all come from a few papers (e.g., ResNet
dominates the top 25 chunks for "residual connection"), the grouped
result has fewer than `k` unique papers. ARCHITECTURE.md 135 defers
the reranker that would fix this properly.

**Fix.** Grow `overfetch` adaptively until unique-paper count ≥ k,
capped at some ceiling (total indexed chunks, or 10×k). Five lines
in `hybrid_search.search`.

---

## 4. `compare --deep` flag is dead but still surfaces in help

**Symptom.** `pc compare A B --deep` exits 2 with a deferral message.
Help text: "LLM-backed synthesis. Currently disabled (cost
discipline); exits 2."

**Root cause.** `--deep` was reserved for LLM-backed synthesis at
M14, then indefinitely deferred. Adds noise to `pc compare --help`
and an out-of-scope branch in `compare.py`.

**Fix options.**
- A. Delete the flag and the deferral branch.
- B. Keep it; reword help to "indefinitely deferred — file an issue
  if you want this".

**Recommendation.** A. If/when LLM-backed synthesis ships, that's a
fresh design discussion anyway.

---

## 5. arxiv_id `cs/1207.0580` warning is expected LLM noise

**Symptom.** During `pc eval run smoke.yaml`, one paper logs:

```
[warning] arxiv_id.unparseable [paper_copilot.agents.skim] raw=cs/1207.0580
```

**Root cause.** LLM emitted a malformed arxiv id mixing the pre-2007
prefix `cs/` with the new-style number `1207.0580`. Validator
rejected it correctly (warn-only, non-fatal). Likely an LLM
hallucination on a citation in the paper's bibliography.

**Fix.** None needed. Documented here so future readers know this
warning is expected LLM noise, not a parser bug. If frequency rises,
M8 lesson applies: prompt anchors won't kill semantic variants;
keep the deterministic post-validator that's already there.
