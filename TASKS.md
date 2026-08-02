# TASKS

> 本文件只保留当前唯一任务。实验记录不得写入这里；历史实验入口统一见
> [实验索引](docs/design/experiment_index.md)。工程规则见 [AGENTS.md](AGENTS.md)，
> 当前接力状态见 [STATUS.md](STATUS.md)，当前架构见
> [ARCHITECTURE.md](ARCHITECTURE.md)。

更新于 2026-08-03。

## 当前唯一任务

- [ ] 找出 Paper Copilot + DeepSeek V4 Flash 在 Query 1 上高于原生 Codex +
  DeepSeek V4 Flash 的主要原因。

先建立可归因的桥接实验：固定模型、reasoning effort、Query、论文集合、输入模态、
conversation 状态和评分标准，逐项对齐或替换 Codex 与 Paper Copilot 之间的运行时差异。
至少区分并验证原生 Skill 交付、World State、系统/开发者指令、工具协议与返回内容、论文
读取路径，以及 Agent 循环和上下文管理；不得把“静态注入 Skill”等同于 Paper Copilot
原生 Skill 机制，也不得用 Paper Copilot 自身消融直接代替 PC 对 Codex 的跨运行时归因。

完成标准：得到至少一个可复现的受控对照，使某个组件的切换能够稳定解释主要评分差距；
同时保存逐项配置、答案、工具调用 trace、评分和运行计量。若单次结果不能支持因果结论，
必须明确保留为候选机制，而不是宣称已经找到原因。
