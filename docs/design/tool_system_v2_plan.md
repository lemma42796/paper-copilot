# Paper Copilot 工具系统 v2 计划

状态：Planned，尚未实现  
日期：2026-07-27  
取代范围：`docs/design/command_first_tool_redesign_handoff.md` 中关于下一代工具实现的建议  
历史文档：旧交接保留为决策背景，不再作为 v2 实施依据

## 1. 决策

Paper Copilot 将重做模型可见工具和 PDF 证据链，借鉴 Codex 的少量通用工具、确定性命令
执行、沙箱、审批和有界输出设计，但不机械复制 Codex 的工具清单。

v2 的核心变化：

1. `read_paper` 不再把全文一次性发送给模型并要求单次结构化压缩。
2. PDF 入库先建立确定性的逐页证据层，再建立章节和 chunk 索引。
3. 异常文字层通过定向渲染和本地恢复处理；纯文本模型不依赖 `view_image`。
4. 多轮检索使用稳定 `result_set_id`，确定性报告预期、完成和遗漏论文。
5. 每条返回给模型的论文事实必须带来源类型、页码和稳定 evidence ref。
6. 工具安全沿用最小权限：授权论文库、应用数据目录、无网络、写操作审批、资源上限和
   append-only 事件。
7. 旧工具在 v2 通过冻结评测前不作为新设计依赖；通过后删除，而不是永久双轨维护。

本计划不以运行旧 `read_paper` 四轮基线为前置条件。旧实现的问题已由代码检查确认，Git
历史足以恢复。主要质量对照是冻结的 Codex 四轮基线。

## 2. 已知问题与目标失败

### 2.1 当前 `read_paper`

当前实现：

```text
PDF text layer
→ 前 3/8 页生成 PaperMeta + PaperSkeleton
→ 按 skeleton 拼接近似全文
→ 一次 LLM 调用生成 contributions/methods/experiments/limitations
→ 写入字段和 embedding 索引
```

该设计存在以下结构性问题：

- 没有根据实际 token、页数和章节数选择读取策略；
- 章节骨架错误会级联为正文遗漏；
- 单次全文结构化输出没有遍历覆盖状态；
- 3000-token 输出上限无法保证长论文的字段完整性；
- contribution、method 和 limitation 没有稳定的页级原文引用；
- PDF 文字层异常时没有 OCR、页面恢复或明确的 unresolved 状态；
- Prompt 与 schema 对推断局限性的规则不一致；
- 成功形状的结构化输出可能掩盖 silent incompleteness。

### 2.2 Codex 基线

冻结基线的主要结果：

- required claim 严格正确：`60/68`；
- required claim 加权准确：`61/68`；
- required claim 完整：`62/68`；
- 全部 required claim 引用支持：`60/68`；
- 相关论文集合 Macro-F1：`95%`；
- 约束保持：`29/30`；
- 遍历完成：`3/4`；
- major error：`1`；
- 作者—方法归属：`100%`。

Codex 的读取、定向搜索和视觉核验已经较强，主要失败是 T03 没有续用上一轮完整论文
集合。v2 必须同时解决：

- PDF 文字与视觉证据恢复；
- 多轮结果集合连续性；
- 全库/集合遍历完整性；
- 可审计的工具 trace、成本和延迟。

## 3. 设计原则

### 3.1 模型负责推理，工具负责事实边界

工具确定性地负责：

- PDF 身份、页数和内容哈希；
- 页面文字来源和质量；
- 页码、区域坐标和 evidence ref；
- 章节/chunk 遍历；
- cursor 和结果集合覆盖；
- 授权、资源限制和副作用状态。

模型负责：

- 解释证据；
- 综合多篇论文；
- 按用户约束组织答案；
- 对 unresolved 证据进行保守表述。

模型不得自行声称工具未报告的“全文已检查”“所有论文已覆盖”或“该页没有相关内容”。

### 3.2 原始记录与派生记录分离

- 原始 PDF 不修改；
- 原生文字层、重排文字、OCR 文字和模型解释分别保存；
- 恢复结果追加而不覆盖；
- 任意 evidence 都能追溯到 PDF hash、页码、区域和提取器版本；
- 重新提取生成新 revision，不重写既有 session/event。

### 3.3 能力自适应但语义一致

Runtime 显式记录当前模型是否支持图像输入。

- 多模态模型可以获得页面图像和同页文字证据；
- 纯文本模型获得本地恢复后的文字、区域、置信度和 unresolved 列表；
- 两种路径使用相同 `paper_id`、页码和 evidence ref；
- 不支持图像时不得静默丢弃图像工具结果。

### 3.4 一个 bounded slice 一次只解决一个失败

实现严格按第 11 节顺序推进。每个 slice 在定义完成并验收后才进入下一项，不把 PDF
底座、OCR、公开工具重写、安全重写和旧代码删除塞进同一个变更。

## 4. 模型可见工具表面

v2 计划公开五个工具。

### 4.1 `library_exec`

用途：在授权论文库内完成确定性的只读文件和 PDF 操作。

计划输入：

```yaml
command: string
timeout_ms: integer?
max_output_chars: integer?
```

安全约束：

- 工作目录固定为授权论文库；
- 禁止网络；
- 禁止论文库和应用数据写入；
- 禁止库外读取；
- 清理继承环境变量和凭据；
- 对命令、子进程、CPU、内存、临时空间、时间和输出设上限；
- PDF 内容和命令输出始终视为不可信数据；
- 超时、截断、空结果和非零退出必须显式返回。

`library_exec` 借鉴 Codex `exec_command`，但权限更窄。它不是任意本机 Shell，也不承担
索引、OCR、知识检索或写操作。

计划输出：

```yaml
status: completed | failed | timed_out
exit_code: integer?
stdout: string
stderr: string
truncated: boolean
elapsed_ms: integer
```

### 4.2 `library_edit`

用途：承担授权论文库内所有用户可见写操作。

计划操作：

- `mkdir`
- `copy`
- `move`
- `trash`
- `restore`
- `write_document`

安全约束：

- 所有路径先 canonicalize 并验证仍位于授权根目录；
- 不允许静默覆盖；
- 删除进入系统废纸篓；
- 文档写入展示完整 diff；
- 批准绑定已校验参数、目标 hash、目标快照和预览；
- 批准后执行前重新检查 precondition；
- 失败、中断和 resume 不自动重放缺少结果的副作用。

该工具不负责写入内部索引。应用数据由确定性 pipeline 在既有 job/session 事务边界内
更新。

### 4.3 `read_paper`

用途：将一个未入库 PDF 转换为逐页证据、章节/chunk 索引和可检索状态。

计划输入：

```yaml
paper:
  paper_id: string?
  title: string?
  pdf_path: string?
language: en | zh
```

三个 locator 字段必须且只能提供一个。模型不能指定 OCR 引擎、提取器路径、输出目录或
任意命令；这些由应用策略决定。

计划状态：

- `already_indexed`
- `indexed`
- `partial`
- `needs_user_action`
- `failed`

计划输出：

```yaml
status: indexed | partial
paper_id: string
title: string?
pdf_sha256: string
ingest_revision: string
coverage:
  pages_total: integer
  pages_processed: integer
  native_text_pages: integer
  recovered_pages: integer
  unresolved_pages: [integer]
  cursor_complete: boolean
artifacts:
  page_manifest_ref: string
  section_index_ref: string
  report_ref: string?
can_search: boolean
```

关键约束：

- `indexed` 只在 `pages_processed == pages_total` 且所有必需索引写入完成时返回；
- `partial` 不伪装成成功，必须列出 unresolved pages 和可用范围；
- 入库不要求 LLM 生成完整论文摘要；
- 结构化摘要如仍保留，只能作为带 evidence ref 的派生视图，不能成为原文真源；
- 已入库论文不为普通问答重复执行完整读取。

### 4.4 `paper_search`

用途：统一全库发现、单篇取证、多篇取证、结果集合续用和遍历复核。

计划输入：

```yaml
operation: discover | retrieve | verify
query: string?
papers:
  - paper_id: string?
    title: string?
result_set_id: string?
cursor: string?
page_size: integer?
evidence_limit: integer?
```

约束：

- `discover` 创建稳定 `result_set_id`；
- `retrieve` 可对显式 papers 或既有 `result_set_id` 获取证据；
- `verify` 必须遍历结果集合中的每篇论文并报告覆盖；
- result set 内容由 Runtime 保存，模型不能伪造或覆盖；
- cursor 与 query/result-set fingerprint 绑定，不可跨查询复用；
- 用户要求“全部”时，只有 `next_cursor = null` 才表示完成。

计划输出：

```yaml
status: ok | partial | no_matches | needs_read
result_set_id: string?
paper_ids: [string]
coverage:
  expected_papers: integer
  completed_papers: integer
  missing_paper_ids: [string]
  cursor_complete: boolean
evidence:
  - ref: string
    paper_id: string
    page: integer
    section: string?
    text: string
    source_kind: pdf_text | reordered_text | ocr | table | model_derived
    confidence: number?
    ingest_revision: string
next_cursor: string?
gaps: [string]
```

`model_derived` 不能单独支撑事实性引用，必须同时返回其原始 evidence refs。

### 4.5 `inspect_page`

用途：Codex `view_image` 的论文专用、能力自适应替代，用于检查明确的 PDF 页或局部区域。

计划输入：

```yaml
paper_id: string
page: integer
region:
  x1: number
  y1: number
  x2: number
  y2: number
purpose: string
```

`region` 可省略。坐标使用页面归一化坐标，Runtime 校验范围。

多模态模型输出：

- 页面或局部区域图像；
- 同页文字证据；
- page/evidence metadata。

纯文本模型输出：

- 原生或恢复文字；
- reading order；
- bounding boxes；
- OCR confidence；
- 不能可靠恢复的图、表、公式或空间关系。

计划输出的公共字段：

```yaml
status: ok | partial | unresolved
paper_id: string
page: integer
evidence: [...]
visual:
  delivered_to_model: boolean
  render_hash: string
unresolved:
  - kind: figure_relationship | table_structure | formula | handwriting | other
    region: [...]
```

安全约束：

- 不接受任意文件路径；
- 只能读取已经解析到授权论文库内的 `paper_id`；
- 单次页数固定为一页，批量检查由有界多次调用完成；
- 渲染尺寸和字节数有上限；
- 不保存无界截图历史；
- 纯文本模型不会收到不可消费的 image content。

## 5. PDF 页面证据层

### 5.1 Stage A：确定性检查

对每个 PDF 记录：

- SHA-256；
- 页数、页面尺寸、加密/损坏状态；
- embedded outline；
- 每页原生字符数；
- 图片覆盖、乱码、替换字符和异常空格等质量信号；
- 提取器和版本。

Poppler 是首选候选底座：

- `pdfinfo`
- `pdftotext -layout`
- `pdftotext -raw`
- `pdftoppm -png`

在实施前必须完成：

- 自包含 App 的二进制打包方案；
- Apple Silicon、签名和 sandbox 验证；
- GPL 及传递依赖分发审查；
- 固定版本和升级策略。

不得依赖终端用户安装 Homebrew。

### 5.2 Stage B：文字层质量判定

页面质量判定是确定性触发器，不是论文语义判断。候选信号包括：

- 页面有明显内容但提取字符数过低；
- 大量 replacement characters；
- 中文被拆成高比例单字符和空格；
- 文本块重叠或阅读顺序异常；
- 标题/摘要候选页没有可用文字；
- 表格或多栏布局无法稳定线性化。

阈值必须通过独立页面样本校准，不能为四轮 query 或特定论文硬编码。

### 5.3 Stage C：恢复阶梯

```text
native layout text
→ raw/coordinate extraction
→ reading-order reconstruction
→ render suspicious page/region
→ local OCR
→ region-specific retry
→ unresolved or human verification
```

OCR 引擎不在本计划中预选。进入实现前对以下候选做独立决策：

- Apple Vision：macOS 原生、设备侧，但需要定义 Swift/Runtime 边界；
- Tesseract：可自包含、通用，但需评估中文论文和版面质量；
- PaddleOCR：中文和文档能力候选，但依赖、体积和打包成本更高。

任何新增依赖必须单独批准。恢复结果必须记录引擎、模型/语言包版本、置信度和区域。

### 5.4 Stage D：证据规范化

每页生成 append-only `PageEvidenceRevision`：

```yaml
paper_id: string
pdf_sha256: string
page: integer
revision: string
extractor:
  name: string
  version: string
source_kind: pdf_text | reordered_text | ocr | table
text: string
regions:
  - bbox: [number, number, number, number]
    text: string
    confidence: number?
quality:
  usable: boolean
  score: number?
  reasons: [string]
unresolved: [...]
```

`quality.score` 只能用于排序和触发恢复，不能被回答呈现为事实正确概率。

### 5.5 Stage E：章节和 chunk

- 优先使用 embedded outline；
- 没有 outline 时使用确定性 heading/版面候选；
- 无法可靠建立章节时仍按页生成 chunks，不阻塞全部入库；
- chunk 保留 page start/end、字符范围和 page evidence refs；
- embedding 只索引规范化文字，不成为原文真源；
- 任何 LLM 生成的章节摘要必须引用输入 evidence refs。

## 6. 纯文本模型的视觉缺失恢复

v2 不声称 OCR 可以理解所有视觉内容。

能够恢复：

- 扫描文字；
- 题名、作者、摘要和章节标题；
- 普通段落；
- 一部分带坐标的表格文字；
- 图中标签和图注。

不能仅靠 OCR 保证：

- 曲线高低和趋势；
- 架构图中的箭头与依赖关系；
- 跨单元格表头关系；
- 复杂公式结构；
- 颜色、纹理和视觉对比。

当用户问题依赖这些内容时：

1. 多模态模型通过 `inspect_page` 获取定向图像；
2. 纯文本模型获得 `unresolved`，不得猜测；
3. 客户端展示目标页面/区域，请用户核验；
4. 未来可设计可选视觉 sidecar，但不属于本计划。

当前“一次任务使用同一模型”的架构保持不变。本计划不引入第二个云端模型调用。

## 7. 结果集合与多轮覆盖

`result_set_id` 是 Runtime 拥有的不可变选择记录，不是模型生成的标签。

计划属性：

- 创建时保存 query fingerprint、paper IDs、排序、创建 turn 和 ingest revisions；
- 后续可派生新集合，但不修改旧集合；
- session 只追加 create/derive/use/complete 事件；
- resume 能从 session 重建；
- PDF 更新导致 ingest revision 变化时，verify 返回 stale，而非静默使用新内容；
- 设置 TTL 只影响缓存回收，不删除 append-only 事件；
- 最大集合大小和单轮遍历预算由 Runtime 策略控制。

覆盖完成条件：

```text
completed_papers == expected_papers
AND missing_paper_ids == []
AND next_cursor == null
AND cursor_complete == true
```

模型回答中出现“全部、逐篇、逐项复核”时，Runtime context 应把未完成 coverage 作为显式
约束返回。工具不能阻止模型提前回答，但 trace 和评分可以确定性识别未完成状态。

## 8. 安全机制

### 8.1 权限

- 论文库读取授权由 macOS security-scoped bookmark 提供；
- 应用数据目录单独授权给 Runtime；
- 模型不能提供任意应用数据路径；
- PDF、文件名、OCR 文字和工具输出全部是不可信输入；
- 本地工具不获得网络权限；
- 不通过 Prompt 代替 sandbox 或 schema 校验。

### 8.2 资源限制

每次调用记录并限制：

- wall-clock deadline；
- CPU 和内存；
- 最大进程数；
- 最大临时空间；
- 最大页面数；
- 最大渲染像素和图片字节；
- stdout/stderr 和 evidence 数量；
- cursor 深度和结果集合大小；
- attempt 总预算。

### 8.3 副作用

- `library_exec`、`paper_search`、`inspect_page` 对用户论文库只读；
- `read_paper` 只写应用派生数据，不修改原 PDF；
- `library_edit` 是唯一用户论文库写入口；
- side-effect call 的批准、执行和结果具有同一 call ID；
- interrupted/failed call 不自动重放；
- partial index 不发布为 current revision。

### 8.4 审计

权威 trace 至少保存：

- 工具名和 schema version；
- 完整校验后参数或安全摘要；
- capability decision；
- sandbox profile/hash；
- executable/version；
- 输入/输出 artifact refs；
- truncation、timeout、cursor 和 coverage；
- token、成本和耗时；
- approval decision；
- terminal status。

模型自报的工具使用记录不作为权威 trace。

## 9. 存储计划

具体路径在实现 slice 中确认，逻辑记录至少包括：

```text
paper identity
  → PDF hash and authorized locator

ingest revision
  → extractor versions
  → page manifest
  → page evidence revisions
  → section/chunk index
  → embedding revision

result set
  → immutable paper IDs
  → query fingerprint
  → ingest revision snapshot
  → coverage events
```

不得把完整 PDF、无界 OCR 文本或完整模型 Prompt写入普通日志。完整派生内容只进入其设计
的本地 artifact；日志保存长度、hash、有界 preview 和 artifact ref。

## 10. 评测与超过 Codex 的门槛

### 10.1 冻结条件

- 使用现有 14 篇论文、四轮 query 和私有 Gold；
- 不根据 v2 答案修改 Gold；
- 记录精确模型、endpoint、参数、工具版本和 capability；
- 网络关闭；
- 记录权威工具 trace、token、耗时和成本；
- 同一实验配置至少重复三次，报告中位数和最差结果。

旧 Paper Copilot v1 完整四轮不是前置条件。必要时只做局部回归检查。

### 10.2 最低数值门槛

v2 必须满足：

| 指标 | Codex | v2 最低门槛 |
|---|---:|---:|
| Required claim 严格正确 | 60/68 | ≥61/68 |
| Required claim 加权准确 | 61/68 | >61/68 |
| Required claim 完整 | 62/68 | ≥63/68 |
| 全部 claim 引用支持 | 60/68 | ≥61/68 |
| 相关论文集合 Macro-F1 | 95% | >95% |
| 约束保持 | 29/30 | 30/30 |
| 遍历完成 | 3/4 | 4/4 |
| major error | 1 | 0 |
| 作者—方法归属 | 100% | 100% |

最低门槛只证明在当前冻结 benchmark 上数值超过。产品目标是修复两个 T02 partial 和全部
T03 missing，争取 `68/68`，但不能为达成该结果硬编码论文、query 或 Gold。

重复运行要求：

- 三次中位数高于 Codex；
- 最差一次没有 major error；
- 每次约束保持和遍历完成均为 100%；
- 作者—方法归属每次为 100%；
- 正常文字层论文不因恢复链产生质量回归。

### 10.3 消融

至少比较：

1. native text；
2. native text + coordinate reorder；
3. native text + OCR recovery；
4. recovery + result set coverage；
5. 多模态 `inspect_page`；
6. 纯文本 `inspect_page`。

消融回答能力提升来自 PDF 恢复、集合状态还是模型视觉能力，不能只报告最终总分。

### 10.4 外推边界

单一领域 14 篇论文只能证明当前 benchmark。对外声称一般化优势前，还需要未参与设计的
跨领域论文集合，至少覆盖：

- 正常文字层；
- 扫描件；
- 双栏；
- 表格；
- 公式；
- 图表依赖问题；
- 中英文混排。

## 11. 实施 slices

### Slice 0：计划冻结

交付：

- 本文档；
- `TASKS.md` 指向本文档；
- 不修改产品代码或公开工具。

完成条件：

- 用户确认计划；
- 计划已提交并 push。

### Slice 1：PDF substrate

目标：建立不依赖 LLM 的 page manifest 和 native text evidence。

范围：

- Poppler packaging/licensing 决策；
- PDF inspect/extract adapter；
- extractor version/hash；
- page manifest 和 ingest revision；
- partial/failed 状态。

非目标：

- OCR；
- `paper_search`；
- 公共工具切换；
- 删除旧代码。

### Slice 2：异常页恢复

目标：在纯文本模型路径恢复 noisy PDF 的可引用文字。

范围：

- 页面质量检测；
- raw/coordinate reorder；
- OCR 引擎决策和适配；
- region retry；
- confidence、source kind 和 unresolved。

非目标：

- 理解任意图表；
- 第二云端模型；
- 全库问答。

### Slice 3：章节/chunk 索引

目标：从 page evidence 建立可追溯的检索索引。

范围：

- outline/heading；
- page fallback chunks；
- evidence refs；
- embedding revision；
- 原子发布 current ingest revision。

### Slice 4：`read_paper` v2 与 `inspect_page`

目标：接通模型可见读取和页面核验工具。

范围：

- capability negotiation；
- 两个工具 schema/dispatch；
- image/text adaptive output；
- job/session/recovery；
- 工具 trace。

### Slice 5：`paper_search` result sets

目标：解决跨轮集合遗漏和遍历完成性。

范围：

- immutable result set；
- discover/retrieve/verify；
- cursor binding；
- coverage；
- stale ingest revision。

### Slice 6：安全收敛

目标：使所有 v2 工具达到 Codex-inspired 最小权限边界。

范围：

- executable/argument policy；
- sandbox；
- approval binding；
- resource caps；
- adversarial PDF/file names/tool output。

只有仓库规则或用户明确要求时才增加或运行自动验证；真实安全验收范围需单独确认。

### Slice 7：冻结评测

目标：完成三次可审计四轮评测及消融。

完成条件：

- 达到第 10 节门槛；
- 报告所有失败和 unverifiable 字段；
- 不使用模型自报替代 trace；
- 用户决定是否进入旧实现删除。

### Slice 8：删除旧实现

目标：只保留 v2 和仍被复用的稳定基础设施。

删除候选：

- 单次全文 `ExtractPaperTool`；
- 旧 skim/deep 字段抽取链；
- 未公开的专用 query/compare 工具；
- 只服务旧工具的 schemas、dispatch 和测试；
- 双轨兼容代码。

保留候选：

- append-only session；
- job/attempt/recovery；
- macOS authorization 和审批 UI；
- knowledge stores 中仍符合 v2 provenance 的部分；
- MCP/客户端协议边界；
- observability 基础设施。

删除前必须有：

- 数据迁移或明确的重建策略；
- v2 eval 通过；
- App/MCP 对旧工具零调用证明；
- 用户明确确认删除 slice。

## 12. 非目标

- 不建设托管 OCR、托管视觉模型或云端论文库；
- 不新增账号、支付、同步或多租户；
- 不为 benchmark 论文、作者、方法或 query 写特例；
- 不让 SwiftUI 重写 Python Core 论文逻辑；
- 不在一个 slice 中同时替换全部工具；
- 不把 OCR confidence 当作事实正确概率；
- 不宣称纯文本模型可以理解所有图、表和公式；
- 不在 v2 验收前删除可恢复旧系统的 Git 历史。

## 13. 下一步决策门

Slice 0 完成后停止。开始 Slice 1 前，用户需要单独确认：

1. 接受 Poppler 作为首选 PDF substrate 候选；
2. 允许进行 GPL/打包方案评估，但尚不添加依赖；
3. 接受 `read_paper` 入库不再依赖全文 LLM 摘要；
4. 接受新增模型可见 `inspect_page`；
5. 接受 v2 通过冻结评测后再删除旧实现。

