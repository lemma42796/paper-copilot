# Experiment index

本文件只提供实验入口，不复制状态、分数或结论。每个实验目录使用一个
`experiment.md` 记录配置、评分、结论、限制和私有 raw 入口；模型最终回答不在仓库中
重复保存。

## Experiments

- [Codex vs Paper Copilot with DeepSeek V4 Pro](../../eval/experiments/codex-vs-pc-v4pro/experiment.md)
- [Codex vs Paper Copilot with DeepSeek V4 Flash](../../eval/experiments/codex-vs-pc-v4flash/experiment.md)
- [Paper Copilot V4 Flash component ablation](../../eval/experiments/pc-v4flash-component-ablation/experiment.md)
- [Codex PDF formula-reading diagnostic](../../eval/experiments/codex-pdf-formula-reading/experiment.md)

## Shared plans and source mappings

- [Multi-thesis blind experiment plan](codex_multi_thesis_blind_experiment_plan.md)
- [Codex and Paper Copilot Agent gap investigation](codex_paper_copilot_agent_gap_investigation.md)
- [Runtime research evidence source mapping](runtime_research_evidence_codex_source_mapping.md)

## Raw artifact root

`/Users/a123/paper-copilot-eval-private/multi-thesis-v1/experiments/`

这里的每个实验与仓库目录同名，包含 `experiment.md` 快照和 `raw/`。为避免破坏历史证据
引用，`raw/` 当前通过符号链接指向原有 `runs/` 产物；原始目录未移动或删除。

## Latest run audits (private)

- Codex vs Paper Copilot with DeepSeek V4 Flash — 2026-08-06 PC 当前 Query 1–4 非盲
  单系统运行审计入口：
  `/Users/a123/paper-copilot-eval-private/multi-thesis-v1/experiments/codex-vs-pc-v4flash/_audit/query1-4-pc-v4flash-current-max-v1/experiment.md`
