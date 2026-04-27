# CLAUDE.md

Engineering conventions for paper-copilot. This file is loaded into every
Claude Code session. Keep it tight. Detailed design docs live in
`ARCHITECTURE.md` and `docs/design/`.

---

## Top priority: what NOT to do

These are the most frequent failure modes. Read them every session.

1. **Do not add features, refactor, or make "improvements" beyond what was
   asked.** A bug fix doesn't need surrounding code cleaned up. If you
   notice adjacent code that "should" be improved, mention it in your
   reply, don't silently change it.

2. **Do not add try/except unless explicitly asked.** Python's default
   is: let exceptions propagate. Caller decides how to handle. Adding
   `try/except Exception: logger.error(...); return None` is a silent
   bug multiplier.
   - Exception: at top-level entry points (CLI commands, agent loop
     boundaries), convert to user-facing error messages. That's it.

3. **Do not introduce new dependencies without asking.** If a task seems
   to need a new library, stop and ask first. Reply with "I could do
   this with `<lib>`, or hand-roll it in ~20 lines. Which do you prefer?"

4. **Do not write docstrings that restate the function signature.**
```python
   # BAD: adds nothing
   def load_paper(paper_id: str) -> Paper:
       """Load a paper by its id."""

   # GOOD: omit it, or write only the WHY
   def load_paper(paper_id: str) -> Paper:
       """Raises SessionError if the paper's session.jsonl is corrupt."""
```
   Default to no docstring. Add one only when the behavior is
   non-obvious from the signature.

5. **Do not write comments that restate the code.**
```python
   # BAD
   x += 1  # increment x

   # GOOD: only comment the WHY
   x += 1  # compensate for 0-indexed page numbering in PyMuPDF
```

6. **Do not silently modify files outside the current task's scope.** If
   a task says "implement `DeepAgent`", do not also edit `SkimAgent` or
   `schemas/`. If something outside scope needs to change, stop and ask.

7. **Do not write tests before the implementation is stable.** For a
   brand-new module, first get the public interface right with one manual
   run, then add tests. Writing tests against an unstable interface is
   wasted work. (Exception: pure schema / pure function modules — tests
   can come first.)

8. **Do not start the next milestone automatically.** When a milestone's
   DoD is met, stop and summarize what you did. Wait for the human to
   say "proceed to Mn+1".

---

## What TO do

### Code style

- **Python 3.12+**, full type hints required on every function and method
  (including `-> None`).
- **Ruff** is the formatter and linter. Rules in `pyproject.toml` are the
  source of truth; do not argue with them.
- **No star imports.** Use explicit `from foo import bar`.
- **Prefer `pathlib.Path` over `os.path`**. Prefer `match/case` over
  nested `if/elif` when discriminating on type/shape.
- **Use `@dataclass(frozen=True, slots=True)` for value types**, Pydantic
  `BaseModel` for anything that crosses an LLM or file boundary.
- **Async by default** for anything doing I/O. Never mix `requests` and
  `httpx`; use `httpx` only.

### Error handling

- Define errors in `shared/errors.py`. New error types should inherit
  from `PaperCopilotError` or one of its subclasses.
- **Raise early, catch late.** Validation at the boundary (CLI arg
  parsing, LLM output parsing), not sprinkled through business logic.
- **Never use bare `except:` or `except Exception:` without re-raising**
  (except at top-level entry points — see rule #2 above).

### Logging

- Use `shared/logging.py`'s structured logger, never `print`.
- Log levels:
  - `debug`: tool calls, token counts, cache boundaries
  - `info`: milestone events (session start, agent spawn, session close)
  - `warning`: recoverable degradation (schema retry, cache miss unexpected)
  - `error`: user-visible failures
- **Do not log full PDF content or full LLM prompts.** Log the first 200
  chars + length. Full content goes to session.jsonl only.

### Testing

- **pytest**, tests live in `tests/` mirroring `src/paper_copilot/`
  structure.
- Test filename: `test_<module>.py`. Test function: `test_<behavior>`.
- **Use real data when possible.** For PDF parsing, keep 2-3 small real
  PDFs in `tests/fixtures/` (not in git if they're large; use DVC or a
  simple download script).
- **Do not mock what you own.** Mock LLM responses (external), mock the
  filesystem (external), don't mock `SessionStore` (ours).

### Naming

- **Modules** and **files**: `snake_case`
- **Classes**: `PascalCase`
- **Functions / variables**: `snake_case`
- **Constants**: `SCREAMING_SNAKE_CASE`, module-level
- **Private**: `_leading_underscore`
- **Protocols / ABCs**: suffix `Protocol` or `Base`, e.g. `LLMClientProtocol`
- **Exceptions**: suffix `Error`, e.g. `SchemaValidationError`

Avoid generic names: `data`, `info`, `result`, `manager`, `handler`,
`util` (as class/function names — `utils.py` as a module is fine when
genuinely miscellaneous).

---

## Module boundaries (hard rules from ARCHITECTURE.md)

These are enforced. Violations fail code review:

- `schemas/` imports **nothing** from other `paper_copilot/*` modules.
- `session/`, `retrieval/`, `knowledge/`, `shared/` never import from
  `agents/` or `cli/`.
- `retrieval/` and `knowledge/` never import each other.
- `eval/` may import `agents/`'s public `run` entrypoint (so suites
  dogfood the real pipeline), but never reaches into `agents/` internals.
  Otherwise imports from `session/`, `schemas/`, `knowledge/`, `shared/`
  only — never from `retrieval/` or `cli/`.

If a task tempts you to cross a boundary, stop and ask. The right answer
is usually "add it to `shared/`" or "expose a narrower interface from
the owning module".

---

## Working with this repo

### When starting a task

1. Read the relevant section of `TASKS.md` for the milestone.
2. Read `ARCHITECTURE.md` sections that touch the modules you'll change.
3. `view` existing files in the affected modules before editing. Do not
   guess at interfaces.
4. Propose the plan in plain text **before** writing code. Wait for
   confirmation on non-trivial milestones.

### When finishing a task

Reply with a **short** summary:
- What files changed (list)
- What the new capability is (1-2 sentences)
- Any DoD items from TASKS.md that are now satisfied
- Any DoD items still missing
- Anything you noticed but did not change (per rule #1)

**Do not write a marketing pitch.** Do not explain obvious things. The
human will read the diff.

### Commit messages

Format: `<type>: <subject>`, lower case, no period.

Types: `feat` / `fix` / `refactor` / `docs` / `test` / `chore` / `perf`

Example:
feat: implement SkimAgent with real Anthropic API
fix: handle PyMuPDF off-by-one page numbering
refactor: extract retrieval interface from single-paper embedding logic

One logical change per commit. If you're about to write `feat: X and
also fix Y`, split into two commits.

---

## Thinking carefully about prompt engineering

The `description` field on every Pydantic `Field(...)` in `schemas/`
is injected directly into the LLM's view. Treat them as production
prompt strings:

- Write to the model, not to the developer.
- Prefer positive instructions ("Extract the core novel contribution")
  over negative ("Don't extract unrelated claims").
- When a field has a failure mode observed in practice, add one line
  noting the common mistake.

Example:
```python
novelty_vs_prior: str = Field(
    description=(
        "How this method differs from prior work. Write 1-2 sentences. "
        "Focus on the mechanism, not the metric improvement. "
        "Bad: 'achieves 2% higher F1'. "
        "Good: 'replaces softmax attention with sparse top-k selection'."
    )
)
```

Two M8 lessons worth keeping in mind (2026-04-24):

- Description wording kills **literal-match** hallucinations: adding
  "don't prefix with 'Not stated but likely:'" made that exact phrase
  disappear across the regression set. It does **not** kill semantic
  variants: telling the model not to mention "low-resource languages"
  in a vision paper just makes it rephrase to "English-language visual
  data". For semantic variants, prompt-layer work is a dead end — use
  validators, retries, or output filters instead.

- For graded fields ("how confident are you", "how novel is this"),
  prefer a small `Literal[...]` enum with sharp anchors over a float
  with description-anchored scales. Float scales collapse to the top
  of the range (M7 `Contribution.confidence`: 79% of values at 1.0
  across 13 papers). Enums force a discrete bucket pick and keep
  downstream code honest.

One M12 lesson worth keeping (2026-04-25):

- **Directional enums need a deterministic post-validator, not a prompt
  anchor.** `CrossPaperLink.relation_type` has three directional values
  (`builds_on` / `compares_against` / `applies_in_different_domain`)
  and two symmetric (`shares_method` / `contrasts_with`). On the M12
  shake-out run, qwen3.6-flash had Bahdanau (2015) emit
  `builds_on→Transformer (2017)` despite the candidate's `year=2017`
  being right there in the prompt. This is the same M8-class semantic
  variant that prompt anchors don't fix — the model picks the closest
  enum even when temporally impossible. Solution:
  `agents.related._validate_links` enforces `candidate.year ≤
  new_paper.year` for the three directional types after the LLM
  returns. Pattern generalizes: when an enum has structure the LLM
  must respect (temporal, causal, hierarchical), enforce it
  deterministically after the call, don't try to talk the model into
  it.

One M14 lesson worth keeping (2026-04-25):

- **The LLM noise floor on structured enums is higher than the
  schema would suggest. Eval assertions must measure to that floor,
  not below it.** First-pass M14 assertions enforced strict
  name-keyed alignment on `methods` and equality on
  `is_novel_to_this_paper`; on a no-op rerun (same prompt, same
  model, same PDFs) all 5 of 5 papers failed. Two reasons:
  (1) the LLM rephrases method names across runs ('Residual
  Learning Framework' ↔ 'Residual Block'), and
  (2) `is_novel_to_this_paper` flips True↔False on borderline cases
  (Identity Shortcut Connections, Dropout) under literally identical
  inputs — same M8-class semantic-variant problem, just on a bool
  enum instead of free text. The fix wasn't to tighten the prompt
  (we know that doesn't work); it was to *drop those assertions*
  from v1 and document the noise floor in the module docstring.
  Generalizable rule: before adding an eval assertion, run the
  pipeline on the same input ≥ 2 times and confirm the field is
  stable. If it isn't, the assertion will be a flake source — design
  around it (multi-run majority-vote goldens, confidence fields,
  catastrophic-only thresholds) instead of pretending stochasticity
  isn't there.

One M15 Session A lesson worth keeping (2026-04-27):

- **For stochastic signals, trend over N runs beats majority-vote
  goldens — cheaper and visually equivalent.** M14 left three options
  open for handling LLM noise (majority-vote, confidence field,
  accept-as-is). M15 Session A added a fourth that obsoletes the
  first: persist every `eval run` as a `RunRow` flat record, then
  render a static SVG line chart of PASS rate per field over time.
  Run 5 (no-op rerun) hit a natural noise event — AlexNet methods
  7→3 trips `len_short` — and showed up as a single sawtooth on the
  chart. Run 6 (deliberate prompt degrade) showed up as the line
  cliffing to 0%. **Sawtooth vs cliff is eyeball-distinguishable in
  one second; the binary PASS/FAIL of a single run is not.** Cost-wise:
  trend over 5 papers × 1 run ≡ 1 paper × 5 runs in signal terms,
  but the former is the path you're already running, while the
  latter requires re-marking goldens. Generalize: when you have a
  noisy boolean assertion, before reaching for majority-vote
  infrastructure, ask "can I just run this N times and look at the
  shape of the line?" Often yes. Hand-rolled SVG (polyline + circles,
  zero JS) is enough — don't pull in plotly/matplotlib for a CLI
  tool's diagnostic page.

One M15 Session B lesson worth keeping (2026-04-27):

- **"0 regressions" passes the eval gate but does not equal "approve
  the upgrade" — you need a positive ROI signal too.** Session B ran
  qwen3.6-plus against the smoke suite as a real upgrade candidate.
  All 5 papers PASSed; 0 field regression. The M9 cost-discipline
  rule "before changing default model, run eval and confirm 0
  regressions" was satisfied. But the data also showed plus was
  **2.03x cost / 2.22x latency** for **0 measurable quality gain**
  (the M14 catastrophic-class assertions pass for both flash and
  plus — eval can't tell which is better, only that both are above
  the floor). Decision: stay on flash. Generalizable rule: a "no
  regression" pass on a coarse eval is a *necessary* condition for
  upgrade, not *sufficient*. Without a metric that distinguishes
  candidate from baseline on the upside, an upgrade with cost
  increase fails on cost discipline alone. This also means: the
  highest-leverage future eval work is finer-grained quality
  assertions (method name stability, subtle hallucination rates),
  not more catastrophic-class coverage. Worth more than another
  smoke variant.

- **"Plus uses more output tokens" is a hidden multiplier on tier
  upgrades.** Pricing page said 1.67x flash; actual cost ratio came
  out 2.03x. Latency ratio came out 2.22x — even larger than cost,
  which means plus is also slower per token. Two amplifiers stack
  in the same direction. Anytime you're costing-out a tier upgrade,
  use the *measured* ratio from a real run, never the price-page
  ratio — the latter is a lower bound only.

- **Cross-run cache comparison needs a same-model cold-start
  baseline, or it lies.** Session A baseline runs 2-5 were back-to-back
  flash, so each one's first paper benefited from the previous run's
  still-warm system+tools cache (5-min TTL). Plus run 7 was the first
  plus call — cold relative to flash baselines. A naive average over
  baselines (0.246) vs candidate (0.092) reads "plus halved cache hit"
  — but candidate run 7's per-paper numbers (0/0.140/0.080/0.105/0.136)
  match flash run 1's per-paper numbers (0/0.122/0.076/0.119/0.128)
  almost exactly. Same architecture, just no warm predecessor. Always
  compare candidate run-1 vs baseline run-1 when switching models, not
  candidate vs N-run baseline mean.

---

## Cost discipline

The default model is defined in `ARCHITECTURE.md` → "模型分配". That
section is the single source of truth; do not restate it here.

- Every LLM call goes through `agents/llm_client.py`. Do not construct
  `anthropic.Anthropic()` clients anywhere else in the codebase.
- Before changing the default model (switching to a different qwen tier
  or to another provider), run `paper-copilot eval run
  eval/suites/smoke.yaml` and confirm 0 regressions. The current v1
  suite catches catastrophic-class regressions (meta drift, > 50%
  field-length drop, missing dataset/metric); subtler regressions
  need the M15 trend report. **0 regressions is necessary but not
  sufficient** — also need a positive ROI signal (measurable quality
  gain large enough to justify the cost / latency delta). M15 Session
  B (2026-04-27) demonstrated this: qwen3.6-plus passed 5/5 with 0
  regression but cost 2.03x / latency 2.22x with no measurable quality
  upside, and was rejected. Multi-tier pricing (`QwenPlusPricing`,
  `pricing_for_model()`) is in place so the *next* upgrade trial is
  zero-friction.
- When you add a new LLM call site, note in your reply the expected
  per-call token usage and cost estimate. New call sites also need
  eval coverage before they land — if no suite exists for the new
  flow, write one (or extend `smoke.yaml`) before merging.

---

## When in doubt

Ask. The cost of one clarification question is much lower than the cost
of implementing the wrong thing. Specifically ask when:

- A task could be interpreted two different ways
- You're about to introduce an abstraction (Protocol, ABC, factory)
- You're about to add a dependency
- A test is hard to write — that's usually a signal the design is wrong
- You disagree with something in this file — I'd rather revise the file
  than have you silently violate it