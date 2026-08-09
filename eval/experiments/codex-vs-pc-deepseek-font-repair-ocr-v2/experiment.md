# DeepSeek：Codex CLI vs Paper Copilot 字体乱码恢复与公式 OCR

状态：`complete_scored`
日期：2026-08-09
语料：单篇论文、三个独立 query

## 目的

比较同一纯文本模型 `deepseek-v4-flash` 在两个 Agent 系统中读取同一篇 PDF 时的完整任务
能力：

- Codex CLI + DeepSeek：使用通用文件与命令工具读取原 PDF；
- Paper Copilot + DeepSeek：使用产品正常提供的 PDF 字体乱码恢复缓存、页面证据和按需公式
  OCR。

实验重点是完整 Agent 系统能否从损坏文本层中恢复可核验的论文内容，而不是单独评测 OCR
模型。两个系统的 Runtime、工具、缓存和指令不同，结论只能归因于各自完整系统组合。

## 冻结论文

- 论文：《多模态无监督行人重识别算法研究》（张耀斌，2024）
- PDF SHA-256：`c5866675d2319815b6462b929d9c5ead27e8abed733aee50665ab9f5e1a3b58b`
- 目标页：PDF 物理第 33–34 页（正文第 25–26 页）
- 原 PDF 视觉页面是唯一答案真源；文本提取、修复缓存、OCR 输出和历史回答都不能反向
  定义正确答案。

## 公开文件

- [queries.md](queries.md)：逐字发送给被测 Agent 的三个问题；
- [rubric.md](rubric.md)：回答质量、Agent 行为和失效条件；
- [metrics.yaml](metrics.yaml)：运行时、Token、成本和经营指标字段。

正确答案和原子标签只位于私有目录：

`/Users/a123/paper-copilot-eval-private/multi-thesis-v1/experiments/codex-vs-pc-deepseek-font-repair-ocr-v2/labels.yaml`

## 运行协议

两个系统均使用同一模型、reasoning effort、PDF、query 正文、网络限制和运行预算。每次
query 使用全新会话，不向被测 Agent 提供 Gold、评分准则、实验目的、历史答案或另一系统
输出。

1. Query 1 检查字体乱码恢复后能否重建公式（3-4）至（3-9）的方法链路；
2. Query 2 在目标公式没有 accepted OCR record 的条件下检查公式（3-10）、（3-11）的
   首次恢复；
3. Query 3 保留 Query 2 正常产生的持久缓存，但使用全新会话发送相同正文，检查能否复用
   已核验内容。相同正文是控制变量，不是重复实验记录。

Paper Copilot 运行 Query 2 前必须使目标论文的内容缓存失效，并确认目标公式没有 accepted
OCR record。只清理该论文的派生缓存，不删除原 PDF、组件权重、运行历史或其他论文缓存。
Query 3 前不得再次清理缓存。

Codex CLI 使用只包含目标 PDF 的隔离工作目录，不注入本仓库指令，也不人为添加 Paper
Copilot 的字体修复或 OCR 工具。

## 评分与报告

三个 query 分别报告回答质量，不合并成一个掩盖阶段差异的总分。回答质量、Agent 行为、
可靠性和经营成本分栏展示：

- 回答质量：strict、weighted、completion；
- Agent 行为：任务完成、证据路径、有效工具调用、失败、恢复、人工介入和终态；
- 经营指标：总耗时、首个有效答案时间、模型/OCR 调用、输入/输出/推理/缓存 Token、模型
  成本、本地 OCR 耗时，以及每个成功任务和每个质量分的成本。

工具调用和缓存命中只从权威 trace、session 或 job 产物判定，不依据模型自报。缺失字段写
`null` 并说明原因，不估算成实测值。

## 失效条件

- 模型、reasoning effort、输入 PDF 或 query 正文不一致；
- 任一系统获得 Gold、评分准则、历史回答、网络或未批准的视觉模型；
- Query 2 开始前 Paper Copilot 已存在目标公式的 accepted OCR record；
- Query 3 不是全新会话，显式携带 Query 2 对话，或运行前再次清理缓存；
- 缺少可核验的最终回答或权威运行 trace；
- 正式评分前 rubric、metrics 或私有 labels 仍被修改。

失效运行保留用于可靠性与成本审计，但不进入正式回答质量比较。

## 当前运行状态

2026-08-09 已完成 Paper Copilot Q1–Q3 手动运行与私有评分。Q1 沿用首轮结果，Q2/Q3
已由 Skill v3 重跑替换；三个 query 的回答质量均为 100%。Q2 冷启动完成两次原样 accept，
Q3 在全新 conversation 中零 OCR 复用 accepted overlay，跨会话缓存复用有效。两条缓存
LaTeX 仍含 `m a x` / `e x p`，因此 accepted formula 精确匹配 Gold 失败；回答质量与缓存
精确性分开报告。

Codex CLI 的 Q1–Q3 已完成正式评分：Q1 为 6 correct、4 partial、2 incorrect，weighted
66.67%；Q2、Q3 均为 12/12，三个 query 的 macro weighted 为 88.89%。Q2 前的误发 Q1 在
工具调用或可用答案产生前即终止，没有向 Q2 提供论文证据；该段只计入排除运行的运营
损耗，不进入 Q2 回答质量与正式任务用量。正式跨系统比较已经完成。

| 指标 | Paper Copilot | Codex CLI | 对比 |
|---|---:|---:|---:|
| 三题 macro weighted | 100.00% | 88.89% | Paper Copilot +11.11 个百分点 |
| 墙钟耗时 | 387.708 s | 1,947.231 s | Codex CLI 为 5.02 倍 |
| total tokens | 736,319 | 19,271,592 | Codex CLI 为 26.17 倍 |
| 模型调用 | 36 | 216 | Codex CLI 为 6.00 倍 |
| 工具调用尝试 | 55 | 227 | Codex CLI 为 4.13 倍 |
| 失败工具调用 | 0 | 27 | Codex CLI 均在任务内恢复 |
| 可归属成本 | ¥0.16953724 | ¥1.04421308 | Codex CLI 为 6.16 倍 |

在本次单论文、单模型、单配置实验中，Paper Copilot 相对 Codex CLI 减少约 80.1% 墙钟
耗时、96.2% Token 和 83.8% 可归属成本。该结果比较的是完整 Agent 系统组合，不能拆解成
单独 OCR 模型的因果效果，也不能外推到所有 PDF。Paper Copilot 的最终答案虽然三题全对，
但 accepted OCR 缓存仍有 `m a x` / `e x p` 间距错误，不能据此宣称缓存 LaTeX 已精确匹配
原页。

私有评分与证据索引入口：

`/Users/a123/paper-copilot-eval-private/multi-thesis-v1/experiments/codex-vs-pc-deepseek-font-repair-ocr-v2/`
