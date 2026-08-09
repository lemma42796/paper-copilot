# Experiment index

本文件只提供实验入口，不复制状态、分数或结论。每个实验目录使用一个
`experiment.md` 记录配置、结论和限制；私有目录中的 `scores.yaml` 保存最新汇总与逐项
评分，`evidence.yaml` 索引模型回答和 Agent 日志，实验目录不重复保存原始运行产物。

## Experiments

- [Codex vs Paper Copilot with DeepSeek V4 Pro](../../eval/experiments/codex-vs-pc-v4pro/experiment.md)
- [Codex vs Paper Copilot with DeepSeek V4 Flash](../../eval/experiments/codex-vs-pc-v4flash/experiment.md)
- [Paper Copilot V4 Flash current max single-system run](../../eval/experiments/pc-v4flash-current-max/experiment.md)
- [Paper Copilot V4 Flash component ablation](../../eval/experiments/pc-v4flash-component-ablation/experiment.md)
- [Codex PDF formula-reading diagnostic](../../eval/experiments/codex-pdf-formula-reading/experiment.md)
- [Codex CLI + DeepSeek vs Paper Copilot + DeepSeek formula OCR](../../eval/experiments/codex-vs-pc-deepseek-formula-ocr/experiment.md)
- [Codex CLI + DeepSeek vs Paper Copilot + DeepSeek font repair and formula OCR](../../eval/experiments/codex-vs-pc-deepseek-font-repair-ocr-v2/experiment.md)

## Shared plans and source mappings

- [Multi-thesis blind experiment plan](codex_multi_thesis_blind_experiment_plan.md)
- [Codex and Paper Copilot Agent gap investigation](codex_paper_copilot_agent_gap_investigation.md)
- [Runtime research evidence source mapping](runtime_research_evidence_codex_source_mapping.md)

## Private experiment root

`/Users/a123/paper-copilot-eval-private/multi-thesis-v1/experiments/`

这里的每个实验与仓库目录同名，只保存当前实验定义、最新评分和证据索引。模型回答、
session、job 与完整 trace 保留在各自原生目录，由 `evidence.yaml` 指向。相同实验重跑时
覆盖当前评分与索引；协议或配置发生实质变化时建立新的实验目录。
