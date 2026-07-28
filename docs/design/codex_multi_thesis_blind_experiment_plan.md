# Codex 与 Paper Copilot 多论文盲测协议

状态：Codex CLI 四轮已完成；Paper Copilot Query 1 未通过，后续轮次暂停
日期：2026-07-28
文档职责：只定义可复现的实验输入、隔离、运行、评分和验收规则。产品状态、工具设计和
单次运行明细分别保存在 `TASKS.md`、工具设计文档和私有实验产物中。

## 1. 研究问题

使用同一组 14 篇硕士学位论文和四轮对话，回答：

1. 原生 Codex 的失败主要发生在哪个研究阶段？
2. Paper Copilot 的通用工具改造能否在不编码测试答案的前提下减少失败？

本实验是单语料案例研究，只能支持以下形式的结论：

> 在冻结的 14 篇论文和四轮任务中，指定版本的 Paper Copilot 相比指定版本的 Codex，
> 在所报告指标上提升、持平或下降。

不得外推为对所有论文、模型或任务的普遍优势。

## 2. 冻结输入

论文目录：

```text
/Users/a123/paper-copilot-test-pdfs/硕士学位论文
```

语料包含 14 篇 PDF，共 1169 页。运行前冻结：

- 相对文件名、文件大小、完整 SHA-256 和 PDF 页数；
- 文本抽取状态：`good | noisy | image_only`；
- 语料版本；
- 四条用户消息及顺序；
- 模型、reasoning effort、上下文、token、时间和费用预算；
- 网络、Apps、Plugins 和 multi-agent 权限；
- 被测工具和 Skill 版本。

论文保留自然文件名，不添加 `gold`、`relevant`、`distractor`、`test` 等标签。

## 3. 隔离

私有实验目录：

```text
/Users/a123/paper-copilot-eval-private/multi-thesis-v1/
├── corpus_manifest.json
├── queries.md
├── gold/
│   ├── papers.yaml
│   ├── claims.yaml
│   ├── evidence.yaml
│   └── turns.yaml
├── runs/
│   ├── codex-cli-jsonl-v2/
│   └── paper-copilot/
└── reports/
```

私有目录不提交到仓库，也不挂载给盲测会话。提示模型“不要读取”不能代替访问隔离。

盲测会话只能看到：

- 冻结的 14 篇原始 PDF；
- 对应轮次的自然语言请求；
- 被测系统原生提供的工具。

盲测会话不能看到：

- 本协议、Gold、评分规则或实验名称；
- 另一个系统的回答、trace 或评分；
- 工具设计讨论和预期失败类型。

标注、两次盲测和两次评分使用相互隔离的新会话。用户不在运行中提供答案性纠正。

## 4. 固定四轮 Query

一次只发送一条，收到完整回答后再发送下一条。两套系统使用完全相同的文字。

### Query 1

> 请只依据当前目录中的14篇硕士学位论文进行整理，不要使用网络资料。先按“主要研究问题”对论文分类。每篇论文只能确定一个主要类别，但可以补充次要主题。请用紧凑表格列出论文题目、作者、主要类别、监督设定、所涉及的模态和判断页码；每篇只占一行，不要仅根据文件名分类。

### Query 2

> 从这些论文中找出所有以无监督学习为主要设定的行人重识别研究，简要区分完全无监督、无监督域适应和仅局部使用伪标签。从现在开始，后续讨论排除所有以无监督学习为主要设定的论文。在剩余论文中，找出明确研究模态缺失、不完整多模态或行人遮挡的论文，说明每篇实际解决的问题、方法名称、作者和证据页码。不要因为出现“无监督”一词就纳入，也不要把一般数据增强自动视为遮挡研究。

### Query 3

> 请回到论文原文，逐项复核上一轮纳入的结论。每项给出论文题目、作者、PDF页码、章节和一段直接支持结论的简短原文；只能部分支持或无法确认时明确标注，不要根据常识补全。然后单独检查项莘泽的《基于多模态信息融合的行人轨迹追踪方法研究》，分别判断其行人重识别、轨迹补全和可视化系统部分在多模态行人重识别综述中应纳入、条件纳入还是排除，并提供章节和页码证据。

### Query 4

> 请生成最终紧凑比较表，继续排除所有以无监督学习为主要设定的论文，并再排除以遮挡行人重识别为主要研究问题的论文。表格每篇只占一行，包含论文、作者、研究问题、监督设定、输入模态、核心方法、注意力或融合位置、数据集、评价指标、局限性和证据页码；重点区分红外—可见光研究，不因协议不同而强行排序。项莘泽论文只纳入与行人重识别直接相关的内容。每个关键单元格必须可追溯，没有可靠证据时填写“未确认”。表后列出复核中修正过的结论。

四条 Query 不附加模型工具自报要求。工具名称、调用顺序、参数、终态、截断、重试和
成本只从 Runtime、CLI 或 session 的权威 trace 统计，避免不可靠自报增加输出长度或
干扰任务答案。

## 5. 五个隔离角色

### 5.1 私有标注

读取全部 PDF 和四条 Query，生成：

| 文件 | 最小内容 |
|---|---|
| `corpus_manifest.json` | paper ID、文件名、题名、作者、年份、SHA-256、页数、抽取状态 |
| `gold/papers.yaml` | main task/category、supervision、modalities、problem/secondary tags |
| `gold/claims.yaml` | claim ID、paper ID、原子事实、evidence IDs、混淆论文、错误严重度 |
| `gold/evidence.yaml` | evidence ID、paper ID、PDF/印刷页码、章节、短定位 anchor |
| `gold/turns.yaml` | 每轮 required/optional/forbidden 集合、expected claims、active constraints |

最小要求：

- 每篇论文有稳定 ID 和完整 SHA-256；
- 四轮都有 turn-level Gold；
- 约 40 条关键原子事实均能定位到原文；
- 项莘泽论文各组成部分有 `include | conditional | exclude` 标签；
- 同一轮不存在 required/forbidden 冲突。

Gold 不需要写成完整参考答案，也不追求穷尽每篇论文全部贡献。

### 5.2 Codex 盲测

当前冻结配置为 `codex-cli 0.145.0`、`gpt-5.6-sol`、`low` reasoning。Query 1 使用
`codex exec --json`，Query 2–4 通过同一 session ID 的 `codex exec resume --json`
继续。网络、Apps、Plugins 和 multi-agent 关闭。

逐轮 JSONL 和原生 rollout 是工具行为真源，写入：

```text
runs/codex-cli-jsonl-v2/
```

### 5.3 Codex 评分

评分会话只读取 Codex 回答、权威 trace、Gold 和本协议的评分规则，不修改产品代码。
输出：

```text
reports/codex-cli-jsonl-v2-report.md
```

基线报告冻结后，才允许据此选择一个有界、通用、无论文特例的工具改造目标。

### 5.4 Paper Copilot 盲测

工具与产品配置冻结后，从全新会话运行完全相同的四轮 Query。该会话不能看到 Codex
回答、基线报告、Gold 或工具改造原因。产物写入：

```text
runs/paper-copilot/
```

若某轮未达到该 bounded slice 的完成条件，立即暂停后续轮次，先修复确定性缺口；正常
`end_turn` 本身不代表验收通过。

### 5.5 最终评分

使用同一 Gold 和评分规则独立评分 Paper Copilot，再与 Codex 基线并列比较。评分会话
不参与工具设计或代码修改。

## 6. Trace 与原始产物

两次盲测逐轮保存：

- 用户输入和完整回答；
- 模型、参数、工具与 Skill 版本；
- 原始 tool request/result、call ID、顺序和终态；
- 命令、搜索词、论文、页码和 artifact refs；
- 空结果、截断、分页、重试、错误和超时；
- token、cached token、LLM 次数、耗时和成本；
- session、job、trace 和最终报告路径。

原始记录只追加，不清理失败或重复调用。不要求或使用模型自报工具清单；不可从权威
trace 获得的字段标为 `unverifiable`，不得推测。

## 7. 评分

回答事实标注：

```yaml
correctness: correct | partial | incorrect | unverifiable | missing
paper_attribution: correct | wrong | missing
citation_support: full | partial | none
locator_correct: true | false
severity: critical | major | minor
```

工具失败只分配一个主要阶段：

```text
paper_discovery_failure
wrong_tool_selection
bad_query_formulation
pagination_incomplete
section_localization_failure
pdf_parsing_failure
evidence_ignored
evidence_claim_mismatch
paper_identity_confusion
synthesis_error
constraint_memory_failure
unsupported_negative_claim
undetermined
```

主要指标：

1. 事实准确率；
2. 作者—方法归属准确率；
3. 引用支持率；
4. 相关论文集合 F1；
5. 约束保持率；
6. 严重错误数；
7. 工具结果利用率；
8. 无新增证据的重复调用率；
9. 需要遍历时的完成率；
10. token、耗时和成本。

主要质量指标为：

```text
论文归属正确且有原文支持的事实数 / 全部可核查回答事实数
```

“没找到”和“论文不存在”必须分别评分；无法从 trace 确认根因时使用 `undetermined`。

## 8. 决策与验收门

工具改造必须：

- 只针对基线证明的一个主要失败类型；
- 成为独立 bounded slice；
- 写明公开接口、非目标、LLM/token/成本影响和验收方法；
- 不包含测试论文的作者、标题、方法、答案或 Query 关键词；
- 不同时修改底层模型和工具；
- 实施期间不查看或调整 Gold。

完整实验验收要求：

- 标注、两次盲测和两次评分相互隔离；
- 两次盲测使用完全相同的语料、Query 和固定条件；
- 两次盲测均保存完整权威 trace；
- Paper Copilot 在全新会话复测；
- 最终报告并列呈现质量、工具行为、token、费用和耗时；
- 报告所有 failure、partial 和 unverifiable 字段；
- 明确说明单语料、模型差异和外推限制。

## 9. 当前执行状态

Codex CLI 四轮 trace 已完成，基线仍需按同一 Gold 形成正式报告。Paper Copilot 的冻结
Query 1 已运行，但因页级证据和最终引用合同缺口未通过，Query 2–4 与最终比较暂停。

本轮具体指标和产物路径见：

- `TASKS.md`
- `docs/design/tool_system_v2_plan.md`
- `docs/design/runtime_research_evidence_codex_source_mapping.md`

修复范围、实现状态和下一动作不再复制到本实验协议。
