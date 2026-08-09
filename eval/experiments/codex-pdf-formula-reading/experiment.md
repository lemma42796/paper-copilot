# Codex CLI PDF formula trace

Status: completed single-paper diagnostic  
UTC start: 2026-08-02T05:08:26Z  
Session: `019fc0df-966c-7b73-8c70-ab1f78060865`  
CLI: `codex-cli 0.146.0`  
Model: `gpt-5.6-sol`, reasoning effort `medium`  
Provider: `openai`

## Input isolation

- Source: `多模态无监督行人重识别算法研究_张耀斌_2024.pdf`
- Experiment filename: `paper.pdf`
- SHA-256: `c5866675d2319815b6462b929d9c5ead27e8abed733aee50665ab9f5e1a3b58b`
- Cwd: `/private/tmp/codex-pdf-formula-trace-20260802T050736Z`
- The cwd contained only the copied PDF and the final answer file.
- `project_doc_max_bytes=0` disabled project `AGENTS.md` discovery.
- The session was fresh, but it was launched from the parent Codex task and inherited host-level developer context. It is not an independent-Terminal clean-context baseline.

## Prompt

> 只分析当前目录中的 paper.pdf，不访问网络，也不要读取其他论文。请选择一页包含多个数学公式且公式在文本提取中可能失真的页面，忠实转写其中一条完整公式，并说明它在该页的作用。必须基于 PDF 本身核验，不要根据常识补写；如果无法可靠识别就明确说明。不要修改源 PDF。

## Authoritative tool sequence

1. Read the installed PDF Skill.
2. Run `pdfinfo`, `pdftotext -layout`, and `rg` to locate formula-heavy corrupted text.
3. Use `awk` to map the candidate text to physical PDF pages.
4. Render physical PDF page 34 at 300 DPI with `pdftoppm` to `page-34.png`.
5. Call `tools.view_image` with `detail="original"`; the native tool output contains an `input_image` item.
6. Transcribe formula (3-11) from the rendered page and explain its role.

The JSON CLI stream exposes the first four operations as command executions. In the native rollout, code mode wraps the visual call as `custom_tool_call(name="exec")`; its input calls `tools.view_image`, and the corresponding output contains the base64 PNG as `input_image`.

## Result

The `pdftotext -layout` output replaced many variables and mathematical symbols with replacement or private-use glyphs. Codex used the text only for navigation. The faithful formula transcription depended on rendering the PDF page to PNG and sending that image to the model.

This demonstrates the current Codex high-fidelity formula path for this paper:

```text
PDF -> pdftotext for navigation -> pdftoppm page render -> view_image -> multimodal model
```

It does not demonstrate a text-only formula recovery path. A text-only model such as the current V4 Flash configuration cannot use the decisive `view_image` step.

## Usage and reliability

- Tool calls: 5 code-mode tool calls
- Commands: 4, including reading the PDF Skill
- Visual calls: 1 `view_image`
- Final cumulative usage: 159,370 total tokens
  - 157,468 input
  - 117,248 cached input
  - 1,902 output
  - 835 reasoning output
- Terminal state: completed
- Model tool failures: none
- Source PDF modified: no
- Research web calls: none
- The CLI attempted background plugin-catalog and analytics requests; both failed and did not affect the PDF result.

## Artifacts

The private `evidence.yaml` index points to the native rollout, rendered page,
and final answer under the private runs root:

`/Users/a123/paper-copilot-eval-private/multi-thesis-v1/experiments/codex-pdf-formula-reading/`

- `native-rollout.jsonl`: complete persisted Codex rollout, including the image payload
- `page-34.png`: the exact page sent to the model
- `final.md`: historical convenience copy of the final Codex answer; the authoritative
  answer also remains in the rollout
