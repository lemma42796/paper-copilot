# Paper Copilot

Paper Copilot is a local research agent for macOS. It is designed to restore
the evidence chain that general-purpose PDF chat tools often lose in
mathematical papers: a PDF may look correct in a reader while its text layer is
damaged, leaving the prose searchable but losing formula characters or
two-dimensional structure. The system first performs deterministic repairs for
embedded-font mappings it can prove. When the text is still insufficient, the
Agent locates the relevant page and region in the original PDF for the current
question and invokes local formula OCR only for the formulas that are actually
needed, instead of OCRing the entire paper in advance.

Recognition results are bound to the PDF SHA-256, physical page, explicit
region, and rendered-evidence hash. They are stored in an invalidatable,
versioned cache and can be reused across later conversations. Formula results
remain marked `verified=false`, and the original PDF is always authoritative.
This gives low-cost text-only models access to local formula evidence that
would otherwise usually require a vision model or full-document OCR.

### How It Differs from Common Approaches

This table compares design priorities; it is not an absolute claim about every
product in each category.

| Common approach | Typical focus | What Paper Copilot additionally addresses |
| --- | --- | --- |
| PDF chat and multi-document Q&A | Retrieve extracted text, answer questions, and cite sources | Repair provable font mappings when the page renders correctly but text extraction is damaged, then decide which formulas require returning to the original PDF |
| Local retrieval-augmented generation (RAG) and research agents | Build indexes, retrieve passages, and compose answers | Bind derived evidence to the PDF hash, extractor version, and cache revision, automatically invalidating old results when the PDF changes or the extractor is upgraded |
| Full-document OCR or high-fidelity parsing | Preprocess the entire document to preserve more structure | Explore with a fast text cache first, run local OCR only on formula regions required by the current task, and reuse accepted results across conversations |

The macOS client manages paper-directory authorization, model and optional OCR
component settings, task interruption and recovery, execution traces, and
jumps from reports to source pages. The product's main distinction is the
shared PDF evidence pipeline and Agent runtime underneath the interface, not
the chat UI alone.

In a frozen, full-system experiment using the same model,
`deepseek-v4-flash` scored **100%** for answer correctness in Paper Copilot and
**88.89%** in Codex CLI, while also using less time, fewer tokens, and lower
model cost. These results apply only to the papers, tasks, and configuration in
that experiment and cannot be attributed to any one component in isolation.

![Python](https://img.shields.io/badge/Python-3.12+-blue)
![macOS](https://img.shields.io/badge/macOS-Apple%20Silicon-black)
![License](https://img.shields.io/badge/License-Apache--2.0-green)

[简体中文](README.md) | English

![Paper Copilot main window](screenshot/readme_en/截屏2026-08-16%2015.08.13.png)

## Technical Highlights

### Agent Harness for Long-Running Tasks

The model decides what to do next and uses tools to search papers, read pages,
query coordinates, and recognize formulas. Before every tool call, the runtime
validates arguments and file permissions and limits execution time and output
size. A Skill defines the research workflow, including evidence-citation rules
and the conditions for calling tools.

The system blocks repeated or highly similar tool calls. Context engineering
controls what enters the model: paper text is loaded on demand, and tool output
is capped. When history grows too long, it is compacted into a structured
summary that preserves paper IDs, page evidence, and key decisions. Compacted
details no longer occupy the model context, while paper content can be read
again when needed. Complete sessions and call records remain available for
recovery and audit. Higher-risk operations are evaluated before execution by
an independent approval model based on risk and authorization.

Conversations, jobs, attempts, sessions, and traces are stored separately to
support recovery, retries, and call tracing. The macOS client and MCP Server
share the same Python Core, so paper-processing logic is maintained in one
place.

### On-Demand Caching with Automatic Invalidation

Researching a paper repeatedly requires the same searches, page reads, and
lookbacks. Reparsing the PDF every time is slow and makes the model reread large
amounts of text. Paper Copilot therefore caches only papers used by the current
task; it does not scan the entire library at startup.

The cache is more than a performance optimization: it is also the persistence
layer for repaired text. Characters restored from font mappings are written to
the cache without modifying the original PDF, and later tasks can read the same
repaired revision directly.

Each cache is bound to the PDF SHA-256 and an extractor fingerprint. Replacing
the paper or upgrading extraction logic creates a new cache revision and
invalidates the old result. A new cache becomes current only after it has been
written completely and validated; file locking prevents concurrent writes from
corrupting it.

### Repairing Corrupted Mathematical Text in PDFs

Some papers render correctly in a reader but produce corrupted mathematical
symbols during text extraction, or lose radicals, vectors, subscripts,
superscripts, summation bounds, and piecewise braces. Even when the prose
remains readable, the formula semantics may already be damaged.

A PDF reader can draw a page directly with embedded font glyphs, while a text
extractor depends on ToUnicode mappings to convert PDF character codes into
Unicode. Formulas with missing mappings can therefore render correctly yet be
extracted as private-use characters, control characters, or replacement
characters.

Paper Copilot repairs only mappings it can prove. It validates the relationship
between PDF character codes, character identifiers (CIDs), and embedded glyph
identifiers (GIDs), then uses the font's cmap, MATH table, or Adobe Symbol
encoding to recover Unicode and temporarily complete ToUnicode for provable
mappings. Control characters are removed only when they are confirmed to map
to empty glyphs; ambiguous characters are never guessed. The original PDF is
not modified, and repaired text is stored in the versioned cache.

Across seven representative theses, the explicit corruption rate fell from
about **0.4124%** to **0.0069%**:

| Metric | Before repair | After repair | Change |
| --- | ---: | ---: | ---: |
| Explicitly corrupted characters | 12,035 | 202 | 11,833 fewer |
| Text characters | 2,918,226 | 2,908,673 | — |
| Explicit corruption rate | 0.4124% | 0.0069% | **98.32% relative reduction** |

“Explicit corruption” includes private-use characters, replacement characters,
and abnormal control characters. This metric measures visible damage in the
text layer, not formula accuracy; a formula can lose two-dimensional structure
without containing an obviously corrupted character.

[Read the font-repair validation](docs/design/pdf_font_unicode_repair_validation.md)

### Agent-Located, Region-Level Formula OCR

Paper Copilot does not depend on a separately trained formula detector or text
localization model, nor does it precompute complete formula boxes. Font-mapping
repair first restores searchable equation numbers and surrounding context where
possible. For non-prose lines that still contain damaged characters, the cache
records only the coordinates of the first and last damaged characters as weak
hints. The Formula OCR Skill then guides the general research model to combine
text anchors with per-character geometry from the original PDF and select the
crop itself. Only that region is rendered and sent to local Formula OCR; the
whole paper is never scanned in advance.

The following results come from two real runs. The first formula had lost its
vector, radical, and summation structure; the second had lost its piecewise
brace and two-dimensional layout. The Agent's first selected region fully
covered each target formula, and local OCR took about **8.7 seconds** and
**3.1 seconds**, respectively. This demonstrates that the path worked for these
two cases, but the sample is too small to establish equivalent localization
performance for arbitrary papers and layouts.

| Corrupted text in cache | Region selected by the Agent | Formula OCR result |
| --- | --- | --- |
| ![Corrupted formula in the text cache](docs/assets/formula-ocr-active-localization/equation-2-9-text-cache.png) | ![Original PDF region with lost vector, radical, and summation structure](docs/assets/formula-ocr-active-localization/equation-2-9-model-crop.png) | ![Recovered formula](docs/assets/formula-ocr-active-localization/equation-2-9-ocr-result.png) |
| ![Corrupted piecewise formula in the text cache](docs/assets/formula-ocr-active-localization/equation-4-10-text-cache.png) | ![Original PDF region with lost piecewise structure](docs/assets/formula-ocr-active-localization/equation-4-10-model-crop.png) | ![Recovered piecewise formula](docs/assets/formula-ocr-active-localization/equation-4-10-ocr-result.png) |

Recognition results are written to the cache only after the Agent reviews them.
If a crop is incomplete or the result is unreliable, the Agent can adjust the
region and retry; when it cannot confirm a formula, the report says so
explicitly. Accepted formulas can be reused in later conversations.

[Learn about the Formula OCR component](docs/design/formula_ocr_optional_component.md)

## Same-Model Experiment Against Codex CLI

This is not a comparison between models. Paper Copilot and Codex CLI used the
same `deepseek-v4-flash` model (DS V4 Flash), read the same PDF, and answered
the same questions under the same network restrictions and execution budget.
Each task began in a fresh conversation; reference answers, scoring rules, and
atomic fact labels were frozen before any answer was inspected.

Correctness was scored by atomic fact: `1` for correct, `0.5` for partially
correct, and `0` for incorrect or missing. Time, tokens, and cost were collected
from run records and did not affect correctness scoring.

| Metric | Unit | Paper Copilot | Codex CLI | Compared with Codex CLI |
| --- | --- | ---: | ---: | ---: |
| Answer correctness (partial credit = 0.5) | % | **100.00** | 88.89 | **+11.11 percentage points** |
| Total formal-task duration | seconds | **388** | 1,947 | **80.1% lower** |
| Total tokens | tokens | **736,319** | 19,271,592 | **18,535,273 fewer (96.2%)** |
| Attributable model cost | CNY | **0.170** | 1.044 | **83.8% lower** |

The results represent only this paper, model, and complete Agent configuration.
They cannot be generalized directly to other settings or attributed to one
component in isolation.

[See the experiment setup and scoring rules](eval/experiments/codex-vs-pc-deepseek-font-repair-ocr-v2/experiment.md)

## macOS Client

The SwiftUI client provides paper-directory authorization, model settings, a
task timeline, interruption and recovery, diagnostics, and research-report
rendering. The app calls the shared Python Core through its bundled Python
Runtime.

![Research report alongside the original PDF](screenshot/readme_en/截屏2026-08-16%2015.08.57.png)

| Model and language settings | Local Formula OCR component |
| --- | --- |
| ![Model and language settings](screenshot/readme_en/截屏2026-08-16%2015.09.08.png) | ![Local Formula OCR component](screenshot/readme_en/截屏2026-08-16%2015.09.47.png) |

## Installation

[Paper Copilot v0.1.0 Preview 1](https://github.com/lemma42796/paper-copilot/releases/tag/v0.1.0-preview.1)
is available for Apple Silicon. Download `PaperCopilot-arm64.dmg`, open it, and
drag Paper Copilot into Applications. This preview is ad-hoc signed and not
notarized by Apple. If macOS blocks the first launch, try opening the app once,
then choose **System Settings → Privacy & Security → Open Anyway**.

[Formula OCR v1.1.0](https://github.com/lemma42796/paper-copilot/releases/tag/formula-ocr-v1)
is published as a separate optional component and can be installed on demand
from Settings. The public assets, manifest, and checksums for both releases have
been verified; a fresh app installation and Formula OCR download from GitHub
Releases have not yet been validated.

## Run from Source

```bash
git clone https://github.com/lemma42796/paper-copilot.git
cd paper-copilot
uv sync --dev
open apps/macos/PaperCopilot.xcodeproj
```

PDFs, caches, task records, and reports remain local by default. When a cloud
model is used, paper text and tool results selected for the current task enter
the model context.

## Technology Stack

SwiftUI · Python 3.12 · Pydantic · asyncio · Poppler · PyMuPDF · fontTools · SwiftMath ·
PaddleX · PP-FormulaNet_plus-M

## Documentation

[Architecture](ARCHITECTURE.md) · [Experiments](docs/design/experiment_index.md) ·
[Formula OCR](docs/design/formula_ocr_optional_component.md) · [Current Tasks](TASKS.md)

## License

Original Paper Copilot code in this version is licensed under the
[Apache License 2.0](LICENSE); see [NOTICE](NOTICE) for attribution. Third-party
components remain subject to their respective licenses. Versions previously
released under MIT remain available under the MIT license that accompanied
them.
