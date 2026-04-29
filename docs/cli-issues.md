# CLI open issues (2026-04-28)

Findings from a manual end-to-end test of all 8 subcommands. None block
functionality. This doc is the unfixed remainder; the fixed ones rode in
on the same session's commits. Removed on 2026-04-29: issue #4
(`--deep` dead flag), issue #3 (`search` undershoots `--k`), issue #1
(`doctor` blanks pre-telemetry sessions instead of reading 0), and the
real-data-loss half of issue #2 (Bag of Tricks `pc read --force`'d —
`meta.arxiv_id` now populated, no stray `meta.id`).

---

## 1. 1 paper has a harmless duplicate `meta.id` field

**Symptom.** `pc list --format json` for `510d98681e5e` (Hypergraph)
shows `arxiv_id="1809.09401"` AND `id="1809.09401"` — pure duplicate,
no data lost. (Bag of Tricks `b350b567b13a`, the formerly real-data-loss
case, was re-read 2026-04-29 and is now clean.)

**Root cause.** Historical residue from before
`PaperMeta.model_config = ConfigDict(extra="forbid")`
(`schemas/paper.py:31`). Current schema rejects extra fields; new
reads cannot reproduce.

**Fix.** `pc read --force` (≈ ¥0.05) the one remaining paper if
cleanliness matters. Otherwise leave it — `meta.id` is dead weight
on a single row; readers ignore it.

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
