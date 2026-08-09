# Paper Copilot V4 Flash current-max single-system experiment

状态：`single_system_non_blind_diagnostic`

本实验记录 Paper Copilot 使用 `deepseek-v4-flash`、`max` reasoning effort 在冻结
Query 1–4 上的最新单系统重跑。四轮位于同一连续会话，全部以 `end_turn` 完成，未发生
工具失败。

私有实验目录：

`/Users/a123/paper-copilot-eval-private/multi-thesis-v1/experiments/pc-v4flash-current-max/`

其中 `scores.yaml` 同时保存汇总与逐项评分；`evidence.yaml` 指向原始 conversation。
该结果是非盲诊断，不能替代 Codex 与 Paper Copilot 的正式匿名对照实验。
