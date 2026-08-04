# Optional local formula OCR

## Decision

Paper Copilot does not bundle PaddlePaddle, PaddleOCR, PaddleX, OpenCV, or
`PP-FormulaNet_plus-S` in the main macOS application. The complete formula OCR
helper is a separately built, signed, versioned download. Merely starting the
app, selecting a model, or hovering over a text-only model performs no network
request.

The user starts the first network request by clicking the download button in
Settings. The client downloads a fixed HTTPS manifest and archive, validates
the declared byte length and SHA-256, verifies the helper code signature,
extracts into a staging directory, and atomically writes `active.json` only
after all checks succeed.

## Runtime boundary

The main Runtime discovers only an executable selected by `active.json` under:

```text
~/Library/Application Support/Paper Copilot/optional-components/formula-ocr/
```

An explicit `PAPER_COPILOT_FORMULA_OCR_HELPER` override exists for source-tree
development. The model-visible `recognize_formula` tool is exposed only when:

- the selected LLM is text-only;
- the PDF library is available; and
- the optional helper is installed and executable.

Image-capable models continue to receive `inspect_page` instead, keeping the
maximum model-visible research tool count unchanged.

## Tool contract

`recognize_formula` accepts an authorized PDF ID, a one-based physical page,
an optional `cache_slot` shown beside garbled content in `layout.txt`, and
exactly one of:

- a printed equation label such as `3`; or
- a normalized page region.

For a printed label, the main Runtime uses the PDF text geometry to construct a
bounded crop. It renders that crop with Poppler and gives only the temporary PNG
path to the helper. The helper performs CPU inference with the packaged
`PP-FormulaNet_plus-S` weights and writes one bounded JSON response to stdout.

The `recognize` result contains candidate LaTeX, a `candidate_id`, page, region,
PDF and render hashes, model identity,
and explicit unverified warnings. It never presents OCR output as mathematical
ground truth or invents confidence. Recognition never changes the cache. After the
model inspects the candidate, it may call `accept` with the frozen `candidate_id`.
Only when the current task needs that specific formula should the model request OCR;
unrelated garbled text or formula slots do not trigger recognition. After the model
accepts a candidate, Runtime replaces that bounded placeholder with LaTeX in a new
`layout.txt` revision, atomically publishes it for later reads, and deletes superseded
revisions for the same cache key. Accepted repairs therefore accumulate in the single
model-visible current TXT.
Candidates are held only in the current Runtime process. If that process exits before
`accept`, the model must run `recognize` again; an unaccepted candidate is never written
to the persistent cache.
Unnumbered inline formulas without a known region remain unsupported rather than
sending a whole page to a formula-only recognizer.

## Distribution prerequisite

`scripts/build_formula_ocr_component.sh` builds the optional macOS ARM64 helper,
adds a supplied local model directory, signs the executable, creates a ZIP, and
emits the release manifest. The archive and manifest must be published at the
pinned GitHub Release URL before the Settings download can succeed. Production
publication also requires Developer ID signing and notarization; an ad-hoc
signed local build is development-only.
