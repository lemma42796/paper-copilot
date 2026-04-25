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

---

## Cost discipline

The default model is defined in `ARCHITECTURE.md` → "模型分配". That
section is the single source of truth; do not restate it here.

- Every LLM call goes through `agents/llm_client.py`. Do not construct
  `anthropic.Anthropic()` clients anywhere else in the codebase.
- Before changing the default model (switching to a different qwen tier
  or to another provider), run the eval suite on ≥ 5 real papers and
  confirm no regression. If the eval suite doesn't exist yet (pre-M14),
  stop and ask the human.
- When you add a new LLM call site, note in your reply the expected
  per-call token usage and cost estimate.

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