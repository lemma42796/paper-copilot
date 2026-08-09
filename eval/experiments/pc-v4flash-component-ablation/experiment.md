# Paper Copilot component ablation: single-run T01 result

## Scope

- Frozen corpus: `multi-thesis-v1`
- Gold: revision 2, T01 only
- Model: `deepseek-v4-flash`, reasoning effort `max`, text input only
- Replicates: one per lane, as authorized
- Batch: `/Users/a123/paper-copilot-eval-private/multi-thesis-v1/runs/pc-component-ablation/20260802T170005Z-single`
- All four jobs completed with `end_turn`; no lane was rerun.

This is a diagnostic component ablation, not a significance test. The claim
adjudication below is a read-only working score against the frozen Gold. A
`partial` claim covers the paper and method direction but omits at least one
material qualifier from the canonical claim.

## Lane definitions

| Lane | In-memory change from Paper Copilot |
|---|---|
| P0 | None |
| P1 | Inject the same frozen Skill body into the system prompt and hide native `load_skill` |
| P2 | Suppress model-visible World State snapshots and patches |
| P3 | Replace only the Paper Copilot system prompt with the frozen Codex base instructions |

P1-P3 still run through Paper Copilot Runtime and Chat. P3 also retains Paper
Copilot's tools, native Skill lifecycle, and World State. Overrides exist only
inside each fresh runner process and do not change production defaults.

## T01 claim adjudication

| Lane | C / P / I / M | Correct | Partial | Missing | Strict | Weighted |
|---|---:|---|---|---|---:|---:|
| P0 | 10 / 2 / 0 / 2 | C002, C004, C007, C010, C014, C023, C032, C035, C038, C041 | C026, C029 | C017, C020 | 71.4% | 78.6% |
| P1 | 8 / 4 / 0 / 2 | C004, C007, C010, C014, C023, C032, C038, C041 | C002, C026, C029, C035 | C017, C020 | 57.1% | 71.4% |
| P2 | 8 / 4 / 0 / 2 | C004, C010, C014, C023, C032, C035, C038, C041 | C002, C007, C026, C029 | C017, C020 | 57.1% | 71.4% |
| P3 | 10 / 2 / 0 / 2 | C002, C004, C007, C010, C014, C023, C032, C035, C038, C041 | C026, C029 | C017, C020 | 71.4% | 78.6% |

Weighted score is `(correct + 0.5 * partial) / 14`. Every lane covered all 14
papers, assigned one primary category per paper, separated secondary themes,
and supplied a row-level PDF page link. No answer used network evidence.

The repeated misses are informative about the frozen T01 task rather than a
single lane: none of the answers states Peng Siyi's text-to-visible-image
bidirectional masking method (C017) or Zhang Jing's multi-scale prior attention
method (C020). C026 consistently omits the half-orthogonal matrix and the two
body-shape subspaces. C029 consistently omits the complete
SYSU-MM01/RegDB foreground-plus-original-image fusion statement.

## Authoritative run accounting

| Lane | LLM calls | Tool calls | `library_exec` | `load_skill` | Total tokens | Cost CNY | Elapsed |
|---|---:|---:|---:|---:|---:|---:|---:|
| P0 | 10 | 11 | 10 | 1 | 230,797 | 0.06059684 | 123.2 s |
| P1 | 13 | 12 | 12 | 0 | 409,174 | 0.10156420 | 159.7 s |
| P2 | 9 | 9 | 8 | 1 | 179,080 | 0.06285532 | 133.9 s |
| P3 | 16 | 15 | 14 | 1 | 552,345 | 0.09614092 | 194.9 s |

Total observed cost: **CNY 0.32115728**.

Relative to P0, static Skill injection used 77.3% more tokens and cost 67.6%
more. Suppressing World State used 22.4% fewer tokens with roughly flat cost.
Replacing the Paper Copilot prompt with Codex instructions used 139.3% more
tokens, six more model calls, and about 71.7 seconds more wall time while tying
P0's working quality score.

## What this run supports

1. The Paper Copilot system prompt is the strongest observed efficiency
   component in this T01 run. The Codex prompt did not lower the working claim
   score because the rest of the Paper Copilot stack remained intact, but it
   substantially increased search and synthesis work.
2. Native Skill loading and World State each have a small positive directional
   quality signal here: removing either reduced the weighted score by 7.1
   percentage points. With one replicate, the equal-sized difference is not
   separable from model variance and is not causal proof.
3. The high Paper Copilot score cannot be attributed to one component from this
   experiment. P3 shows that the prompt alone is not necessary for the observed
   T01 score; the retained Paper Copilot Runtime, research tool, cache, Skill,
   and context protocol remain a combined explanatory block.
4. A defensible interview statement is: this ablation isolated a strong prompt
   effect on efficiency, found directional quality contributions from native
   Skill delivery and World State, and narrowed the unresolved quality source
   to the shared Paper Copilot execution/retrieval stack. More tasks or repeated
   runs are required before assigning a quality cause.

## Validation and limits

- The harness performed offline identity checks for the frozen Skill and Codex
  prompt before execution.
- No extra paid smoke call was made; the four authorized formal calls were the
  only model executions.
- No test suite or build was run because it was not requested.
- This experiment does not test formula extraction, PDF vision, or OCR.

## Harness and raw evidence

The runner remains beside this record as `run_lane.py`. A lane is launched with:

```bash
.venv/bin/python eval/experiments/pc-v4flash-component-ablation/run_lane.py \
  --lane p0 \
  --batch-root /absolute/private/batch-directory
```

The private score and evidence-index entry is:

`/Users/a123/paper-copilot-eval-private/multi-thesis-v1/experiments/pc-v4flash-component-ablation/`
