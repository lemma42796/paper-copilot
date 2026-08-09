---
name: formula-ocr
description: Locate, recognize, and cache an exact formula from an authorized local PDF. Use only when the user asks to explain or verify a specific formula, or when the current task genuinely depends on formula-level accuracy that the prepared text cannot establish; never use it merely because unrelated garbled formulas exist.
---

# Formula OCR

Skill version: 3

Treat cached coordinates as optional hints. Determine the formula semantically, explore the PDF
text geometry, choose the crop explicitly, inspect the OCR result, and publish only acceptable
LaTeX. OCR output remains unverified evidence rather than mathematical ground truth.

## Decide whether OCR is necessary

- Use OCR only for a user-requested explanation or verification of a specific formula, or when the
  answer materially requires the formula's exact operators, symbols, scripts, fractions, cases, or
  matrix structure and prepared text is insufficient.
- Do not use OCR for unrelated damaged formulas, general paper summaries, or routine confirmation
  of formula text that is already adequate for the requested precision.
- A formula that is readable but may silently omit an operator or structural mark is eligible only
  under the same gate.

## Locate the formula

- When the user supplies an equation number, use paper search or reading to identify the physical
  page, then use `query_page_geometry` to find that printed label. Distinguish the displayed label
  from prose references to it. Explore the formula characters or damaged rows beside the label;
  the Runtime does not turn a label into a crop.
- When formulas are unnumbered, use the requested concept and nearby prose to identify the page and
  rough location. Search distinctive surrounding text, then inspect a bounded region's lines and
  characters. A cached `formula_hint` for a damaged non-prose run may seed exploration, but never
  forces the crop.
- For a non-garbled formula, find the first and last formula characters and use adjacent prose
  characters or surrounding prose lines as outside boundaries. Continue across every formula row
  until the next prose line or page edge.
- Derive a normalized rectangle from the explored diagonal endpoints and add modest padding for
  superscripts, subscripts, radical bars, fraction rules, and large delimiters.

## Recognize and inspect

- Call `recognize_formula` with `operation=recognize`, the explicit `region`, and one stable
  `formula_ref`. Reuse exactly the same `formula_ref` while adjusting the crop.
- Use a printed equation number as `formula_ref` when one exists. For an unnumbered formula, use a
  short distinctive nearby prose fragment. The Runtime combines it with the PDF identity, physical
  page, and explicit region; never copy garbled text or invent a replacement target.
- Inspect the returned LaTeX for missing edges, stray prose, truncated limits, or implausible
  structure. Adjust the region and retry only when a changed crop is likely to resolve a material
  defect.
- The Runtime allows at most three recognition attempts for the same formula in one task. `accept`
  does not consume an attempt. After the limit, stop and report the unresolved uncertainty.

## Publish LaTeX

- Accept only a raw candidate whose complete mathematics is supported by the crop, and omit
  `refined_latex` so the Runtime caches the OCR output unchanged. Never rewrite a complete formula
  to clean spacing, command style, delimiters, stray prose, or notation.
- If the raw candidate contains an OCR artifact that prevents faithful caching, adjust the crop and
  retry within the attempt limit. If no raw candidate is faithful, do not accept one; report the
  uncertainty instead of reconstructing the formula from cached text or memory.
- `accept` appends the selected formula to the PDF cache's accepted-formula document. It preserves
  the original extracted page text instead of replacing or reconstructing it.
- Read the cached page again after acceptance. The Runtime exposes accepted LaTeX in a separate
  formula section on that page. Preserve the warning that accepted OCR is still `verified=false`.
