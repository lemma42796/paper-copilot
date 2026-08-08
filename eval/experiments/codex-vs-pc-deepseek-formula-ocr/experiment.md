# Codex CLI + DeepSeek vs Paper Copilot + DeepSeek：公式 OCR 与跨会话缓存

状态：`scored_diagnostic_cache_not_established`  
日期：2026-08-08  
执行者：用户手动运行  
语料：单篇论文、两个 query；Query 2 必须在全新会话中运行

## 目的

比较同一纯文本模型 `deepseek-v4-flash` 在两个系统中的公式证据能力：

- Codex CLI + DeepSeek：通用命令工具与原始 PDF；
- Paper Copilot + DeepSeek：按需 PDF 文本缓存、可选本地 Formula OCR、accept 后的跨会话
  公式缓存。

实验只检验以下两个产品级问题：

1. 文本层严重损坏时，系统能否忠实恢复论文特有公式，而不是凭常识补写；
2. 首轮已经核实并发布的公式，能否在全新会话中直接复用，而不再次执行 OCR。

这不是 OCR 单组件因果消融。两个系统的 Runtime、工具、缓存和指令不同，结论只能归因于
完整系统组合。

## 冻结论文与目标页

- 论文：`多模态无监督行人重识别算法研究_张耀斌_2024.pdf`
- SHA-256：`c5866675d2319815b6462b929d9c5ead27e8abed733aee50665ab9f5e1a3b58b`
- 目标：PDF 物理第 34 页（正文第 26 页），公式（3-10）和（3-11）
- 选择理由：两式包含分段函数、条件下标、邻域集合、摄像头约束、条件概率和归一化求和；
  Poppler 文本层丢失了关键符号与二维结构，且不是可安全依赖模型记忆的教科书公式。

原 PDF 是答案真源。历史视觉核验只用于冻结私有 Gold，不作为运行时输入。

## 冻结输入

逐字使用 [queries.md](queries.md)。两个系统均使用：

- `deepseek-v4-flash`；
- reasoning effort `max`；
- text-only；
- 禁止网络；
- 只允许访问目标论文及各自正常运行所需的本地工具/缓存；
- 不向模型提供 Gold、历史答案、历史评分或另一系统输出。

Codex CLI 使用只包含同一 PDF（可命名为 `paper.pdf`）的独立工作目录、fresh thread，且不
注入本仓库 `AGENTS.md`。允许 Codex 使用其正常可见的本地命令；不得人为添加 Paper
Copilot OCR 工具。

Paper Copilot 使用正常产品入口，Formula OCR 组件必须已安装。Query 1 前检查目标公式没有
accepted OCR record；若已有，不删除用户缓存，记录 cold 条件失败并停止正式比较。

## 两阶段协议

### Query 1：cold OCR fidelity

分别在两个系统的新会话中发送 Query 1。保存完整 answer、session/rollout、工具调用、终态、
token、耗时和错误。Paper Copilot 若确认 OCR 候选可靠，应按产品正常机制 accept；不由实验
脚本强制调用或修改缓存。

### Query 2：fresh-conversation reuse

Query 1 完成后保留各系统自然产生的持久状态，但启动全新会话：

- 不把 Query 1 的 prompt、回答或工具输出放入 Query 2 上下文；
- Paper Copilot 保留其论文缓存；
- Codex 保留同一工作目录中由自身正常产生的文件，但不额外复制 Query 1 回答；
- 发送 Query 2，保存相同类型的权威产物。

Query 2 的 answer quality 与 Query 1 分开评分。跨会话复用只从 trace 判定，不依据模型自报。

## 评分

公开评分规则见 [rubric.md](rubric.md)。私有答案标签位于：

`/Users/a123/paper-copilot-eval-private/multi-thesis-v1/experiments/codex-vs-pc-deepseek-formula-ocr/labels.yaml`

每个 query 12 个等权内容项，`correct=1`、`partial=0.5`、`incorrect=0`、`missing=0`；
分别报告 strict、weighted、completion，不把 Query 1/2 合成一个正式总分。

机制指标单独报告：

- Query 1 是否发生有效 formula recognize / accept；
- Query 2 是否零 OCR 调用复用 accepted cache；
- 工具调用、模型调用、token、耗时、失败、恢复与终态；
- 是否对无法核验的符号诚实降级，是否声称“已核验”却给出错误公式。

## 停止与失效条件

- 任一系统不是冻结模型或不是 text-only；
- 任一系统获得网络、视觉模型或另一系统的 OCR/答案；
- Paper Copilot Query 1 前目标公式已有 accepted OCR record；
- PDF SHA-256 不一致；
- Query 2 不是全新会话，或显式携带 Query 1 回答；
- 运行产物缺少权威 trace，无法区分真实工具调用与模型自报。

发生以上情况时保留产物作为诊断，不进入正式 answer-quality 对比。

## 2026-08-08 手动运行状态

两个系统的 Query 1/2 均已由用户手动运行并完成私有评分。答案质量可比较，但 Paper Copilot
Query 1 没有 accept 公式，Query 2 因而再次 OCR；本轮未建立 accepted cache reuse 条件，缓存
结论为空，只保留为诊断。

私有审计入口：

`/Users/a123/paper-copilot-eval-private/multi-thesis-v1/experiments/codex-vs-pc-deepseek-formula-ocr/_audit/manual-runs-20260808-v1/experiment.md`
