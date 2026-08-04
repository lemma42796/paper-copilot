# Optional local formula OCR

## Decision

Paper Copilot does not bundle PaddlePaddle, PaddleOCR, PaddleX, OpenCV, or
`PP-FormulaNet_plus-S` in the main macOS application. The complete formula OCR
helper is a separately built, signed, versioned download. Merely starting the
app, selecting a model, or hovering over a text-only model performs no network
request.

The user starts the first network request by clicking the download button in
Settings. The client downloads a fixed HTTPS manifest. Schema v2 describes the
Helper Runtime and `PP-FormulaNet_plus-S` weights as separate content-addressed
archives, including archive byte length and SHA-256 plus a deterministic digest
of each installed directory tree. The client writes `active.json` atomically
only after all reused or downloaded artifacts pass validation.

## Reuse before download

After the user clicks download, the installer resolves each artifact in this
order:

1. an already assembled version whose Runtime tree, model tree, executable bit,
   and Helper code signature still match;
2. a matching Runtime or model from another installed version;
3. Paper Copilot's content-addressed extracted-artifact and archive caches;
4. for model weights only, the known PaddleX cache path
   `~/.paddlex/official_models/PP-FormulaNet_plus-S`, after its complete tree
   digest matches the manifest;
5. the artifact's fixed HTTPS archive.

The installer does not scan the whole disk. It never assembles a production
Helper from arbitrary Python environments because their Python ABI, native
libraries, architecture, and signature state are not a trusted release
boundary. A matching complete Runtime can be reused; loose Paddle packages
cannot. Reused sources are copied into a staging version, revalidated together,
and activated atomically. Cached archives remain keyed by archive SHA-256 so a
later reinstall does not download identical bytes again.

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
signs the executable, and emits separate Runtime and model ZIPs plus a schema-v2
release manifest. It also assembles a complete development Helper under `dist/`
using the supplied local model directory. Both archives and the manifest must be
published at the pinned GitHub Release URL before the Settings download can
succeed. Production publication also requires Developer ID signing and
notarization; an ad-hoc signed local build is development-only.

The ARM64 build requires LLVM `libomp`. The script locates Homebrew's `libomp`
or accepts an explicit `FORMULA_OCR_LIBOMP` path, copies it under the GOMP ABI
name required by Paddle, and signs that copy. Paddle's bundled
`libgcc_s.1.dylib` is exposed under its referenced `libgcc_s.1.1.dylib` name by
an internal relative symlink. The finished Runtime must contain both names;
PyInstaller's unresolved-library warning alone is not an acceptable release
artifact.
