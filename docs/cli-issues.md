# CLI open issues (2026-04-28)

Findings from a manual end-to-end test of all 8 subcommands. None block
functionality. This doc is the unfixed remainder; the fixed ones rode in
on the same session's commits. Removed on 2026-04-29: issue #4
(`--deep` dead flag), issue #3 (`search` undershoots `--k`), and issue
#1 (`doctor` blanks pre-telemetry sessions instead of reading 0).

---

## 1. 2 papers have a stray `meta.id` field; 1 has real data loss

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

## 2. arxiv_id `cs/1207.0580` warning is expected LLM noise

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
