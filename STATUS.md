# STATUS

> 当前任务的跨会话接力快照。每次更新覆盖旧内容，不追加历史流水；详细实验记录和结果只
> 保存在实验文档与产物目录中。

更新于 2026-08-03。

## 当前目标

通过可归因的桥接实验，找出 Paper Copilot + DeepSeek V4 Flash 在 Query 1 上高于原生
Codex + DeepSeek V4 Flash 的主要原因。

## 已知结果

- B、C 都只运行了一次 Query 1；二者是单轮诊断，不是四轮正式实验或重复实验。
- B（Codex + `library_exec`，无 Skill）：6 C / 8 P，strict 42.9%，weighted 71.4%。
- C（B + Skill v16 静态开发者指令）：8 C / 6 P，strict 57.1%，weighted 78.6%。
- Paper Copilot T01 复跑（原生 Skill v16）：11 C / 3 P，strict 78.6%，weighted
  89.3%。
- 旧原生 Codex 四轮运行的 T01 当前人工拆分为 8 C / 4 P / 0 I / 2 M，strict
  57.1%，weighted 71.4%，coverage 85.7%；该拆分不是当时单独持久化的正式评分。
- 因而静态注入 Skill 虽改善了 B，但没有复现 Paper Copilot 的 T01 分数；C 的 strict
  与上述原生 Codex T01 人工拆分相同。当前尚未找到 PC 高分的可归因原因。
- 已有 PC 内部单次消融显示，静态 Skill 和隐藏 World State 均伴随降分，但这只能产生
  候选机制，不能单独解释 PC 相对 Codex 的跨运行时差距。

## 当前状态

- 原“干净重跑 Codex T01–T04”任务已取消。
- 新的归因实验尚未设计定稿，也未启动新的模型调用或产生费用。
- 当前证据只支持描述性结论，不支持统计显著性或稳定因果结论。
- 历史实验已按清晰实验名称统一为 `eval/experiments/<name>/experiment.md`；私有评测区
  使用同名目录和 `raw/` 入口组织原始产物，旧 `runs/` 路径保持不变。

## 下一步

1. 以 PC T01 复跑和 Codex T01 为两端，列出所有未对齐变量及其权威 trace 证据。
2. 设计最小桥接矩阵，优先测试能同时覆盖原生 Skill 交付、World State、系统提示、工具
   协议/结果和上下文管理的对照；每组先跑一次 Query 1。
3. 在执行前明确每一组唯一变化、预计调用量、时间和费用，并获得用户付费执行授权。
4. 对答案使用同一 Gold revision 2 只读评分，对 trace 单独统计调用、token、费用、耗时和
   失败/恢复。
5. 若某组件在单次桥接中解释主要差距，再对该组件做重复运行，验证结果是否稳定。

## 固定约束

- 模型、reasoning effort、Query、论文集合、输入模态和评分口径必须保持一致。
- 明确区分静态 Skill 文本与 Paper Copilot 原生 `load_skill` 交付机制。
- 不把 PC 自身消融直接表述为 PC 高于 Codex 的原因。
- Gold 只读；不打印、记录或复制 API key。
- 未获得明确执行授权前，不发起付费模型请求。

## 证据入口

- [当前任务](TASKS.md)
- [实验索引](docs/design/experiment_index.md)
- [V4 Flash 跨系统实验](eval/experiments/codex-vs-pc-v4flash/experiment.md)
- [PC 组件消融结果](eval/experiments/pc-v4flash-component-ablation/experiment.md)
- 私有语料与 Gold：
  `/Users/a123/paper-copilot-eval-private/multi-thesis-v1/`
