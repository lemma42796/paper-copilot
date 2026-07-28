# Codex 多篇学位论文盲测与工具改造计划

状态：执行中；Codex CLI 四轮权威 trace 已完成，基线重新评分待执行
日期：2026-07-28

## 1. 目标

使用同一组 14 篇硕士学位论文，先观察原生 Codex 在多篇长论文、多轮对话中的真实
失败，再根据失败轨迹为 Paper Copilot 设计一个有界的通用工具改动，最后用相同任务
复测。

本实验回答两个问题：

1. 原生 Codex 的失败发生在论文发现、文内定位、证据绑定、综合推理、状态保持还是
   PDF 解析阶段？
2. Paper Copilot 的针对性工具改造，能否在不编码本组论文答案的前提下减少这些失败？

本实验是单语料案例研究。它可以为工具设计提供证据，但不能证明 Paper Copilot 在所有
论文任务上普遍优于 Codex。

## 2. 语料

论文目录：

```text
/Users/a123/paper-copilot-test-pdfs/硕士学位论文
```

目录当前包含 14 篇 PDF，共 1169 页。运行标注前生成并冻结：

- 相对文件名；
- 文件字节数；
- SHA-256；
- PDF 页数；
- 文本抽取状态；
- 实验语料版本号。

论文文件保持原始自然文件名。不要添加 `gold`、`relevant`、`distractor`、`test` 等会
泄露标签的前后缀。

## 3. 为什么不能只用三个会话完成全部目标

三个相互隔离的新会话可以完成第一阶段：

1. 标注会话；
2. 原生 Codex 盲测会话；
3. 基线评测与工具需求诊断会话。

这三个会话不能同时完成 Paper Copilot 的改造后证明。工具实现并冻结后，还需要：

4. Paper Copilot 盲测会话；
5. 最终对比评测会话。

不能复用第 2 个会话进行 Paper Copilot 复测。该会话已经看过论文、问题和自己的历史
答案，也可能通过对话知道用户在检查错误，复用会破坏盲测。

因此整个工作分为两个阶段、五个会话。当前先执行前三个会话；评测会话给出工具设计
要求后，再单独确定实现范围，不自动开始下一里程碑。

## 4. 隔离原则

### 4.1 标注和评分材料

建议保存到不挂载给盲测会话的私有目录：

```text
/Users/a123/paper-copilot-eval-private/multi-thesis-v1/
├── corpus_manifest.json
├── queries.md
├── gold/
│   ├── papers.yaml
│   ├── claims.yaml
│   ├── turns.yaml
│   └── evidence.yaml
├── runs/
│   ├── codex-cli-jsonl-v2/
│   └── paper-copilot/
└── reports/
```

私有目录不提交到 Paper Copilot 仓库，也不作为盲测会话的 workspace root。若 Codex
运行环境仍可读取该目录，必须通过沙箱或独立容器取消挂载；提示模型“不要读取”不能
代替访问隔离。

### 4.2 盲测会话可见内容

原生 Codex 盲测会话只能看到：

- 14 篇原始 PDF；
- 正常的文献整理请求；
- 原生 Codex 自带的文件和命令工具。

Paper Copilot 盲测会话只能看到：

- 同样的 14 篇原始 PDF；
- 完全相同的文献整理请求；
- 冻结后的 Paper Copilot 产品工具。

盲测会话不能看到：

- 本计划；
- gold 标签；
- 评分规则；
- 基线或 Paper Copilot 的另一份回答；
- 工具设计讨论；
- `baseline`、`experiment`、`benchmark` 等条件名称。

### 4.3 固定条件

两次盲测固定：

- PDF 文件与哈希；
- 4 条用户消息及顺序；
- 模型版本和 reasoning effort；
- 上下文、时间和 token 预算；
- 网络权限；
- 初始空会话；
- 用户不提供答案性纠正。

若两个系统使用相同底层模型，可以把差异主要归因于工具和工作流。若底层模型不同，
只能比较两个端到端产品在本案例上的结果。

## 5. 会话 1：私有标签制作

### 5.1 会话职责

标注会话读取 14 篇 PDF 和本计划中的 4 条 query，创建结构化 gold。它不运行被测系统，
也不设计 Paper Copilot 工具。

### 5.2 产物

#### `corpus_manifest.json`

每篇论文记录：

```json
{
  "paper_id": "P01",
  "filename": "...pdf",
  "title": "...",
  "author": "...",
  "year": 2024,
  "sha256": "...",
  "pdf_pages": 82,
  "text_extraction": "good"
}
```

`text_extraction` 取值：

- `good`：正文和页码可稳定提取；
- `noisy`：存在字体编码、断字或顺序问题；
- `image_only`：主要需要 OCR 或视觉读取。

#### `gold/papers.yaml`

每篇论文的稳定属性：

- `main_task`；
- `main_category`；
- `supervision`；
- `modalities`；
- `problem_tags`；
- `secondary_tags`。

#### `gold/claims.yaml`

约 40 条关键原子事实。每条包含：

```yaml
claim_id: C001
paper_id: P01
claim_type: method
canonical_claim: ...
evidence_ids: [E001]
confusable_papers: [P03, P07]
severity_if_wrong: critical
```

#### `gold/evidence.yaml`

```yaml
evidence_id: E001
paper_id: P01
pdf_page: 35
printed_page: 24
section: "3.2"
anchor: ...
```

`anchor` 只保存用于人工定位的短片段，不保存整页正文。

#### `gold/turns.yaml`

每轮记录：

```yaml
turn_id: T03
paper_relevance:
  required: [...]
  optional: [...]
  forbidden: [...]
expected_claims: [...]
active_constraints: [...]
allowed_abstention: true
```

### 5.3 最小标签要求

时间有限时只要求：

- 每轮 `required / optional / forbidden` 论文集合；
- 约 40 条原子事实；
- 每条事实的论文、章节、PDF 页码和证据；
- 第 2、3、4 轮的活动约束；
- 项莘泽论文各组成部分的 `include / conditional / exclude` 标签。

不编写完整参考答案，不追求穷尽每篇论文的全部贡献。

### 5.4 完成条件

- 所有 PDF 均有稳定 `paper_id` 和哈希；
- 4 轮均有 turn-level gold；
- 每条关键 claim 能定位到原文；
- 标签内部没有同一论文同时 `required` 和 `forbidden` 的冲突；
- 私有产物未进入盲测 workspace。

## 6. 会话 2：原生 Codex CLI 盲测

### 6.1 会话设置

任务显示名称使用自然名称，例如：

```text
多模态行人重识别文献整理
```

工作区只包含论文目录。不要在提示中提到实验、评分、标签或后续工具设计。

当前权威运行使用 `codex-cli 0.145.0`、`gpt-5.6-sol` 和 `low` reasoning。首轮通过
`codex exec --json` 开始，后三轮通过同一 session ID 的 `codex exec resume --json`
继续；web search、命令网络、Apps、Plugins 和 multi-agent 均关闭。逐轮 JSONL 和原生
session rollout 是工具行为真源。旧 ChatGPT 桌面端导出只有模型自报，已删除，不再
作为基线或评分输入。

### 6.2 逐轮 query

一次只发送一条，收到完整回答后再发送下一条。

每条 query 末尾统一附加以下记录要求。两次盲测必须使用完全相同的文字：

> 在回答末尾另设“本轮工具使用记录”小节，按实际调用顺序列出本轮使用的工具。每次
> 调用说明：工具名称、目的、涉及的论文或文件、搜索关键词或页码、成功或失败状态，
> 以及是否出现空结果、截断、分页未完成或重复调用。无法从当前记录确认的字段填写
> “未确认”，不要根据记忆补全。

该小节是模型自报摘要，不视为权威 trace，也不参与回答质量指标。用户侧仍需保存可见
工具调用记录，并在两者冲突时以实际记录为准。

#### Query 1

> 请只依据当前目录中的14篇硕士学位论文进行整理，不要使用网络资料。先按“主要研究问题”对论文分类。每篇论文只能确定一个主要类别，但可以补充次要主题。请用紧凑表格列出论文题目、作者、主要类别、监督设定、所涉及的模态和判断页码；每篇只占一行，不要仅根据文件名分类。

#### Query 2

> 从这些论文中找出所有以无监督学习为主要设定的行人重识别研究，简要区分完全无监督、无监督域适应和仅局部使用伪标签。从现在开始，后续讨论排除所有以无监督学习为主要设定的论文。在剩余论文中，找出明确研究模态缺失、不完整多模态或行人遮挡的论文，说明每篇实际解决的问题、方法名称、作者和证据页码。不要因为出现“无监督”一词就纳入，也不要把一般数据增强自动视为遮挡研究。

#### Query 3

> 请回到论文原文，逐项复核上一轮纳入的结论。每项给出论文题目、作者、PDF页码、章节和一段直接支持结论的简短原文；只能部分支持或无法确认时明确标注，不要根据常识补全。然后单独检查项莘泽的《基于多模态信息融合的行人轨迹追踪方法研究》，分别判断其行人重识别、轨迹补全和可视化系统部分在多模态行人重识别综述中应纳入、条件纳入还是排除，并提供章节和页码证据。

#### Query 4

> 请生成最终紧凑比较表，继续排除所有以无监督学习为主要设定的论文，并再排除以遮挡行人重识别为主要研究问题的论文。表格每篇只占一行，包含论文、作者、研究问题、监督设定、输入模态、核心方法、注意力或融合位置、数据集、评价指标、局限性和证据页码；重点区分红外—可见光研究，不因协议不同而强行排序。项莘泽论文只纳入与行人重识别直接相关的内容。每个关键单元格必须可追溯，没有可靠证据时填写“未确认”。表后列出复核中修正过的结论。

### 6.3 Pilot 范围与扩展门

本轮 4 条 query 只验证全库发现、论文归属、证据定位、跨轮约束保持、多论文综合和工具
行为。它不要求穷尽：

- 无监督方法的全部训练数据组织细节；
- 所有红外—可见光实验的数值结果和协议；
- 每个注意力机制参与训练的完整路径。

只有当 4 轮结果不足以定位主要失败阶段，或 Codex 与 Paper Copilot 的差异无法判定时，
才另行设计并冻结扩展 query；不得在当前盲测中临时追加。

### 6.4 轨迹保存

用户侧保存完整任务轨迹。除 6.2 中固定的自报要求外，不额外告诉被测 Codex 评分方式
或失败诊断目标。轨迹至少包括：

- 每轮输入和完整回答；
- 工具名称和调用顺序；
- 工具参数；
- 搜索关键词；
- 涉及的文件、论文和页码；
- 工具返回状态、结果数量和截断状态；
- 分页是否完成；
- 错误、超时和空结果；
- 重复或近似重复调用；
- token、耗时和可获得的成本数据。

原始轨迹只追加，不人工清理错误调用。导出后写入：

```text
runs/codex-cli-jsonl-v2/
```

### 6.5 完成条件

- 4 条 query 全部按顺序完成；
- 中途未给予答案性提示；
- 完整答案和工具轨迹已导出；
- 运行期间 Codex 未获得 gold 或实验计划。

## 7. 会话 3：基线评测与工具需求诊断

### 7.1 会话输入

评测会话可以看到：

- 私有 gold；
- 原生 Codex 的 4 轮回答；
- 完整工具轨迹；
- 固定评分规则。

它不修改 Paper Copilot 代码。

### 7.2 回答标签

将回答拆成原子事实并标：

```yaml
matched_gold_claim: C001
correctness: correct | partial | incorrect | unverifiable | missing
paper_attribution: correct | wrong | missing
citation_support: full | partial | none
locator_correct: true | false
severity: critical | major | minor
```

### 7.3 工具与失败标签

每个错误分配一个主要阶段：

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
```

无法仅凭轨迹确定根因时标记 `undetermined`，不要强行归因。

### 7.4 指标

只保留以下主要指标：

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

### 7.5 会话输出

评测报告写入：

```text
reports/codex-cli-jsonl-v2-report.md
```

报告必须包含：

- 每轮指标；
- 严重错误清单；
- 工具调用时间线；
- 按失败阶段汇总的数量；
- 能由现有工具解决的问题；
- 需要新增或修改工具能力的问题；
- 一个且仅一个优先工具改造建议；
- 不应通过 prompt 或论文特例解决的问题。

### 7.6 完成条件

- 所有关键结论能追溯到 gold 或工具轨迹；
- “没找到”和“论文不存在”被分别评分；
- PDF 解析失败没有被错误归因于模型推理；
- 给出一个有界、通用、无论文特例的工具改造建议；
- 尚未开始实现下一阶段。

## 8. 工具改造决策门

会话 3 完成后，由用户确认是否实施建议。实现必须成为独立 bounded slice，并在开始前
明确：

- 唯一目标失败类型；
- 修改的公开工具及契约；
- 明确不做的相邻改动；
- 预期新增 LLM 调用、token 和成本；
- 验收方式。

禁止：

- 把本组论文的作者、标题、方法或标准答案写入工具；
- 为 4 条 query 写关键词规则；
- 同时修改底层模型和工具；
- 为追求总分同时重写多个工具；
- 在实现过程中查看或调整 gold。

## 9. 会话 4：Paper Copilot 盲测

工具实现和产品配置冻结后，开启全新会话，从 Query 1 开始运行相同的 4 轮。

该会话不能看到：

- 原生 Codex 回答；
- 基线评测报告；
- 工具改造原因；
- gold 和评分规则。

保存与原生 Codex 同等粒度的回答、内部模型工具调用和产品 trace，写入：

```text
runs/paper-copilot/
```

## 10. 会话 5：最终对比评测

使用同一 gold 和评分规则重新独立评分 Paper Copilot，然后并列比较：

| 指标 | Codex | Paper Copilot | 差值 |
|---|---:|---:|---:|
| 事实准确率 |  |  |  |
| 作者—方法归属准确率 |  |  |  |
| 引用支持率 |  |  |  |
| 相关论文集合 F1 |  |  |  |
| 约束保持率 |  |  |  |
| 严重错误数 |  |  |  |
| 工具结果利用率 |  |  |  |
| 重复调用率 |  |  |  |
| 遍历完成率 |  |  |  |
| Token |  |  |  |
| 耗时 |  |  |  |
| 成本 |  |  |  |

最终允许的结论形式：

> 在本组 14 篇硕士学位论文和固定 4 轮对话中，采用某项工具改造的 Paper Copilot
> 相比原生 Codex，在指定指标上提升或未提升。

不允许把单次案例扩大为“Paper Copilot 普遍优于 Codex”。

## 11. 总体验收

实验完成需要同时满足：

- 标注、盲测和评测会话相互隔离；
- 两次盲测使用相同语料和 query；
- 两次盲测均保存完整工具轨迹；
- 工具改造来自基线失败证据；
- 工具不包含论文或 query 特例；
- Paper Copilot 在全新会话中复测；
- 最终报告同时呈现质量、工具行为和成本；
- 对实验局限作明确说明。
