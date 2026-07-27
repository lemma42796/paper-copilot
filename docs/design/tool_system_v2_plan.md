# Paper Copilot 工具系统 v2 计划

状态：方向已确认，Slice 1–6 已完成，Slice 7 尚未开始
日期：2026-07-27  
取代范围：`docs/design/command_first_tool_redesign_handoff.md` 及本文档旧版中的下一代工具建议  
历史文档：旧文档和 Git 历史只作为决策背景，不再作为 v2 实施依据

## 1. 最终决策

Paper Copilot 的模型可见工具采用 Codex 风格的少量通用原语。论文研究步骤不再固化在
一个大型模型工具中，而由 Skill 指导 Agent 显式组合；Runtime 只负责安全、缓存、状态
不变量和有界执行。

v2 模型只看到四个工具：

1. `library_exec`：在授权论文库和只读派生缓存中执行受限命令。
2. `inspect_page`：检查一张明确的 PDF 页面或局部区域。
3. `paper_set`：保存不可变论文集合及其跨轮覆盖状态。
4. `library_edit`：执行授权论文库中的用户可见写操作。

以下名称不属于 v2 模型工具表面：

- `read_paper`
- `paper_search`
- `search_papers`
- `query_paper`
- `query_papers`
- `compare_papers`
- `find_related_papers`
- Composer 专用工具
- 旧 `library_files`
- 旧 `notes_patch`

核心变化：

1. 论文研究工作流写入 Skill，不写入大型工具实现。
2. 模型通过 `library_exec` 明确选择 `pdfinfo`、`pdftotext`、`rg`、`awk` 等命令，并从
   每次有界输出决定下一步。
3. 正常文字层 PDF 优先使用 Poppler 一次性提取全文 TXT，不要求逐页调用模型，不要求
   LLM 生成结构化字段。
4. 提取结果按 PDF hash、提取器版本和提取参数跨会话缓存；匹配缓存必须复用。
5. TXT、page manifest 和原始 PDF 是论文证据基础；数据库、chunk、embedding 和向量
   RAG 不作为 v2 入库或问答前置条件。
6. `inspect_page` 只在文字层、版面、图表、公式或页码证据需要核验时使用。
7. `paper_set` 只解决 Codex 基线暴露的跨轮集合遗忘和遍历完成性，不承担搜索或 RAG。
8. `library_edit` 仍是唯一用户论文库写入口。
9. 对 Codex 的借鉴以可审查源码和权威工具 trace 为依据，不以工具名称、界面行为或
   模型自述作为架构事实。
10. 旧实现只保留到 v2 通过冻结评测；通过后按单独确认的删除 slice 移除。

本计划不修改当前 `ARCHITECTURE.md` 对已实现系统的描述。公开工具实际切换时，再把已
落地且验收过的 v2 契约写入架构文档。

### 1.1 Codex-first 参考原则

Agent 工具、命令执行、sandbox、审批、进程生命周期、Skill 和 trace 的设计遵循以下
优先级：

1. 开始设计或编码前，先在固定 Codex source ref 中查找对应实现；
2. Codex 已有对应机制时，参照其结构、数据流、状态语义和失败行为实现，不另行发明
   平行机制；
3. 只有产品授权边界或论文领域对象不同的部分，才允许做必要的窄化适配；
4. Codex 没有对应机制时，才允许增加 Paper Copilot 专用设计，并记录已检索的源码位置、
   缺失点和最小补充范围；
5. 如果计划偏离 Codex 已有设计，必须先写明差异和理由，并取得用户明确确认。

每个实施 slice 在写代码前必须形成一份源码映射，至少包括：

```text
需求 → Codex source ref → Codex 现有机制 → 直接采用/必要适配/确实缺失
```

未完成源码映射，不得以“Codex-style”或“Codex-inspired”为由自行补充设计。

## 2. 决策依据

### 2.1 当前实现的问题

当前 `read_paper` 是一个模型可见的复合工具：

```text
read_paper
→ SkimPaperTool
→ ExtractPaperTool
→ LinkRelatedPapersTool
→ report
→ fields store
→ section chunks
→ embedding store
→ graph links
```

该设计把多个 LLM 调用、论文结构推断、字段抽取、检索索引和持久化步骤隐藏在一次工具
调用中，存在以下问题：

- Agent 不能按任务跳过不需要的步骤；
- 正常文字提取、语义解释和索引发布没有清晰边界；
- 章节骨架错误会级联为正文遗漏；
- 单次结构化压缩无法证明全文覆盖；
- 长流程失败时模型难以判断具体失败阶段；
- 用户只需一次局部问答时仍可能承担完整入库成本；
- embedding 和结构化字段被错误地当成问答前置条件；
- 工具逐渐成为隐藏的第二套 Agent。

当前 `paper_search` 同时包装论文发现、单篇查询、多篇查询、分页和旧知识索引，也把本可
由命令组合完成的搜索决策隐藏在内部。

### 2.2 Codex 源码依据

Slice 2 的源码映射固定到本机 Codex commit
`61a44880a85d2fd0d8770908dea5733495e571c8`，借鉴以下 Codex Core 机制：

逐项审计见 `docs/design/library_exec_codex_source_mapping.md`。该映射是 Slice 2 的实现
门槛；映射与本文冲突时先修订计划，不得静默选择其中一份。

- `codex-rs/core/src/tools/handlers/unified_exec.rs`
  - 通用 `exec_command` 参数；
  - shell 选择；
  - PTY、yield 和输出预算。
- `codex-rs/core/src/tools/handlers/unified_exec/exec_command.rs`
  - environment/cwd 解析；
  - sandbox 与权限审批；
  - process manager；
  - `apply_patch` 特殊拦截；
  - hook、trace 和输出截断。
- `codex-rs/core/src/tools/handlers/unified_exec/write_stdin.rs`
  - 长进程输入和增量输出协议。
- `codex-rs/core/src/tools/runtimes/shell.rs`
  - 命令 canonicalization；
  - approval key；
  - sandbox attempt；
  - 网络和环境策略。

Paper Copilot 不复制 Codex 的全部 Rust、远程环境、代码仓库权限或通用本机能力，只实现
论文库需要的窄化子集。与 Codex 一致，安全边界以规范化命令、固定 cwd/environment、
OS sandbox、timeout、输出预算和权威 trace 为核心；不另造一套容易与 sandbox 漂移的
危险命令黑名单。

### 2.3 Codex 四轮实验依据

冻结的 14 篇硕士学位论文实验中，Codex 的实际首轮策略是：

```text
列出 14 篇 PDF
→ pdfinfo 获取页数
→ pdftotext -layout 把全部 PDF 提取到临时 TXT
→ awk/rg 定向搜索
→ pdftotext -f/-l 精读命中页
→ pdftoppm 渲染少数页面
→ view_image 核验
```

权威 session trace 显示：

- 14 篇论文合计 1169 页；
- 首次完整 TXT 提取耗时 4.2 秒；
- 前四轮共 48 次命令执行和 14 次页面图像检查；
- 没有 OCR；
- 没有 embedding；
- 没有向量数据库；
- 没有先运行全文 LLM 结构化摘要；
- 后续轮次复用了同一临时 TXT 目录；
- 临时目录不具备跨会话缓存契约。

该实验说明正常文字层 PDF 的全文 TXT 提取可以是快速本地原语，复杂研究任务可以由模型
组合命令完成。它没有证明所有 PDF、扫描件或更大论文库都具有相同耗时。

### 2.4 基线失败

冻结 Codex 基线：

- required claim 严格正确：`60/68`
- required claim 加权准确：`61/68`
- required claim 完整：`62/68`
- 全部 required claim 引用支持：`60/68`
- 相关论文集合 Macro-F1：`95%`
- 约束保持：`29/30`
- 遍历完成：`3/4`
- major error：`1`
- 作者—方法归属：`100%`

主要失败不是缺少向量 RAG，而是 T03 没有续用上一轮完整论文集合。因此 v2 在复现 Codex
命令能力之外，只增加确定性的跨轮 `paper_set`。

## 3. 设计原则

### 3.1 Agent 编排，工具执行

Agent 负责：

- 理解用户问题；
- 决定是否需要全文提取；
- 选择关键词、同义表达和命令组合；
- 选择要精读或视觉核验的页面；
- 创建和派生论文集合；
- 综合证据并按用户约束回答。

模型工具负责一次明确动作：

- 执行一条受限命令；
- 检查一页；
- 更新一次论文集合状态；
- 执行一次明确文件修改。

不得在一个模型工具内部隐藏完整的“提取 → OCR → 分章 → embedding → 字段抽取 → 搜索
→ 总结”研究流水线。

### 3.2 Skill 不是安全边界

Skill 负责指导正确工作流，但不能授权命令、路径、网络或副作用。

真正的边界位于：

- Pydantic tool schema；
- executable/argument policy；
- canonical path validation；
- macOS sandbox；
- resource caps；
- approval binding；
- append-only session/job/trace。

PDF 文本、文件名、TXT 缓存、命令输出和 Skill 引用的论文内容均视为不可信输入。

### 3.3 事实真源与派生缓存分离

- 原始 PDF 不修改；
- TXT 是从明确 PDF hash 和提取器版本生成的派生证据；
- page manifest 保存页数、换页边界、提取状态和版本；
- 页面渲染、OCR 和模型解释分别记录来源；
- 搜索结果、结构化摘要、embedding 和模型回答不是原文真源；
- 任意缓存都可由原 PDF 重建；
- 重建生成新 revision，不覆盖 append-only 历史。

### 3.4 默认不使用向量 RAG

v2 默认检索顺序：

```text
全文 TXT
→ rg/awk
→ 明确 PDF 页
→ 有界页级原文
→ 必要时 inspect_page
```

SQLite FTS、BM25、embedding 或向量索引只能作为后续独立实验候选。没有冻结消融证明前：

- 不作为入库条件；
- 不作为问答条件；
- 不作为 `paper_set` 依赖；
- 不新增 embedding 调用；
- 不新增向量数据库依赖。

### 3.5 一次只推进一个 bounded slice

每个 slice 单独确认、实现和验收。不得在同一变更中同时完成命令执行器、缓存、页面核验、
论文集合、公开工具切换和旧代码删除。

## 4. 模型可见工具

### 4.1 `library_exec`

用途：在授权论文库和只读派生缓存范围内执行一条受限命令。

计划输入：

```yaml
cmd: string
timeout_ms: integer?
max_output_tokens: integer?
```

v2 初版不提供交互式 PTY 或任意长进程。命令必须在有界 deadline 内完成；超时后终止并
在输出中标记 `timed_out`。如果真实论文任务证明需要持续进程，再单独评估 Codex `write_stdin`
模式，不在本计划中预先增加第五个工具。

计划输出：

```yaml
output: string
exit_code: integer?
wall_time_seconds: number
timed_out: boolean?
original_token_count: integer?
output_omitted_bytes: integer?
```

该结构参照 Codex `ExecCommandToolOutput::code_mode_result`。完整命令、resolved argv、
`command_ref`、sandbox policy/profile hash 和 artifact refs 只进入权威 trace，不作为
模型输出协议。

允许能力的目标范围：

- 列举和统计授权论文库文件；
- 计算文件 hash；
- `pdfinfo`；
- `pdftotext -layout`；
- `pdftotext -raw`；
- `pdftotext -f/-l`；
- `rg`；
- `awk`、`sed`、`sort`、`wc` 等有界文本处理；
- 调用 Runtime 提供的确定性 `paper-cache` 命令。

具体执行边界依据固定 Codex 源码版本的 command resolution 和 sandbox attempt 结构实现。
Paper Copilot 固定系统 PATH、逻辑 cwd 和过滤后的环境，不提供模型可选 shell、登录
shell、远程 environment、额外权限或失败后升级。模型不能：

- 访问网络；
- 读取论文库、受控缓存和允许临时目录之外的路径；
- 写入用户论文库；
- 直接写入应用数据目录；
- 读取凭据或继承无关环境变量；
- 选择任意 OCR 引擎或可执行路径；
- 绕过审批调用其他副作用工具。

命令中显式出现的 `pdftotext`、`rg` 等程序必须保留在 trace。Runtime 不把一组研究步骤
静默改写成大型内部 pipeline。

### 4.2 `inspect_page`

用途：检查一个明确的 PDF 页面或局部区域。

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

`region` 可省略；坐标使用归一化页面坐标。

Runtime 确定性执行：

```text
paper_id
→ 授权 locator
→ PDF hash/revision 校验
→ pdftoppm 定向渲染
→ 有界页面结果
```

多模态模型获得：

- 页面或区域图像；
- PDF 页码、render hash 和 evidence metadata。

纯文本模型沿用固定 Codex `view_image` 的能力检查语义：Runtime 在解析 PDF 和渲染前
明确拒绝调用，不执行文本回退，也不发送模型无法消费的 image content。

计划输出：

```yaml
status: ok | partial | unresolved
paper_id: string
page: integer
evidence: [...]
visual:
  delivered_to_model: boolean
  render_hash: string
unresolved: [...]
```

约束：

- 不接受任意文件路径；
- 单次只处理一页；
- 渲染尺寸和字节数有上限；
- 不静默声称 OCR 能理解图表、箭头、公式或复杂表头；
- 不支持图像的模型不会收到不可消费的 image content；
- `inspect_page` 不触发整篇入库、embedding 或结构化摘要。

OCR 不在 v2 初版中预选。扫描件恢复需要单独的依赖、打包、质量和评测决策。

### 4.3 `paper_set`

用途：保存和复用不可变论文集合，确定性报告跨轮约束与遍历覆盖。

计划操作：

- `create`
- `derive`
- `record_evidence`
- `status`

计划输入：

```yaml
operation: create | derive | record_evidence | status
result_set_id: string?
parent_result_set_id: string?
query: string?
paper_ids: [string]?
included_paper_ids: [string]?
excluded_paper_ids: [string]?
paper_id: string?
evidence_refs: [string]?
reason: string?
```

语义：

- `create` 保存 Agent 通过显式命令发现的论文 ID 和 query fingerprint；
- `derive` 从父集合产生新集合，不修改父集合；
- `record_evidence` 为集合中一篇论文追加已核验 evidence refs；
- `status` 返回 expected、completed、missing、stale 和 coverage。

计划输出：

```yaml
status: ok | incomplete | stale
result_set_id: string
parent_result_set_id: string?
paper_ids: [string]
coverage:
  expected_papers: integer
  completed_papers: integer
  missing_paper_ids: [string]
  complete: boolean
stale_paper_ids: [string]
```

约束：

- 论文 ID 必须解析到授权论文库；
- 集合创建后不可修改；
- 派生集合必须保存父集合和排除原因；
- evidence ref 必须存在且与目标 paper/revision 匹配；
- PDF hash 变化时返回 stale；
- session 只追加 create/derive/evidence/complete 事件；
- resume 能从 append-only 事件重建；
- TTL 只能回收派生缓存，不能删除历史事件。

完成条件：

```text
completed_papers == expected_papers
AND missing_paper_ids == []
AND stale_paper_ids == []
AND complete == true
```

`paper_set` 不执行全文搜索、不调用 `library_exec`、不调用 `inspect_page`，也不生成答案。

### 4.4 `library_edit`

用途：承担授权论文库内所有用户可见写操作。

计划操作：

- `mkdir`
- `copy`
- `move`
- `trash`
- `restore`
- `write_document`

约束：

- 所有路径 canonicalize 后仍须位于授权论文库；
- 不允许静默覆盖；
- 删除进入系统废纸篓；
- Markdown 写入展示完整 diff；
- 批准绑定 tool call、已校验参数、目标 hash、目标快照和预览；
- 执行前重新检查 precondition；
- 中断、失败和 resume 不自动重放缺少结果的副作用；
- 不负责 PDF 缓存、索引或应用内部状态写入。

`library_edit` 不调用其他模型可见工具。它可以复用底层文件、Trash、diff 和审批组件。

## 5. 论文研究 Skill

v2 提供一个论文研究 Skill，指导 Agent 组合四个工具。Skill 是可审查的提示和工作流，
不包含论文答案、benchmark 特例或隐藏程序执行。

### 5.1 标准工作流

```text
1. library_exec 列出 PDF 并确认任务范围
2. 检查 paper-cache 状态
3. 缓存缺失时执行确定性全文 TXT 提取
4. 使用 rg/awk 和同义表达搜索
5. 根据换页边界定位 PDF 页
6. 用 pdftotext -f/-l 读取有界原文
7. 文字或版面可疑时调用 inspect_page
8. 全库或多轮任务创建 paper_set
9. 为逐篇证据记录 coverage
10. 基于 evidence refs 回答
11. 需要保存结果时调用 library_edit
```

### 5.2 Skill 约束

- 不仅根据文件名分类；
- 不把单次 `rg` 空结果解释为论文没有相关内容；
- 对关键概念使用用户原词、同义表达、方法名和英文术语组合搜索；
- 引用必须来自明确 PDF 页；
- “全部、逐篇、逐项复核”必须使用 `paper_set`；
- coverage 未完成时不得声称完整；
- 页面视觉关系未核验时标记 `unresolved`；
- 不要求先生成 contributions/methods/experiments/limitations；
- 不自动执行 embedding 或向量检索；
- 检测到用户环境缺少 Poppler 时，先询问用户是否同意执行
  `brew install poppler`；只有获得明确同意后才自动安装，拒绝或 Homebrew 缺失时停止
  并说明原因；
- 工具使用记录以 Runtime trace 为准，不以模型自报为准。

### 5.3 Skill 与源码依据

Skill 中每个 Codex-inspired 行为都必须能追溯到：

- Codex 源码路径和固定 commit/ref；
- 冻结基线的权威 tool trace；
- Paper Copilot 自身安全或产品边界。

不得仅因 Codex 当前界面出现某工具名称就复制行为。

## 6. 跨会话 PDF 缓存

### 6.1 缓存身份

缓存键至少包含：

```text
PDF SHA-256
+ extractor name
+ extractor version
+ extraction mode
+ normalized extraction parameters
```

文件名、移动时间和模型会话 ID 不属于内容缓存身份。

### 6.2 逻辑布局

具体物理路径在 Slice 1 冻结。逻辑结构：

```text
paper cache
└── <pdf_sha256>/
    └── <extractor_fingerprint>/
        ├── manifest.json
        ├── layout.txt
        ├── raw.txt
        └── recovered/
            └── <page>.txt
```

`raw.txt` 和 `recovered/` 按需生成，不要求每篇论文同时存在。

manifest 至少记录：

- PDF hash；
- 授权 locator 的安全引用；
- 页数；
- 提取器和版本；
- 提取参数；
- 每页文字字符数；
- 换页边界；
- 创建时间；
-完成/部分/失败状态；
- unresolved pages；
- artifact hash。

### 6.3 缓存命令

Runtime 在 `library_exec` 的受限 PATH 中提供确定性 `paper-cache` 命令：

```text
paper-cache status <relative-pdf>
paper-cache ensure <relative-pdf>
paper-cache page <paper-id> <page>
```

这些是命令行原语，不是模型工具。`ensure` 只负责 hash、缓存命中判断、确定性文字提取和
原子发布，不执行 OCR、LLM、切片、embedding、结构化字段或论文搜索。

`library_exec` 对缓存只有读取能力；缓存写入由 `paper-cache` 的窄化 broker 完成，模型
不能指定应用数据输出路径。

### 6.4 命中与失效

必须复用缓存：

- PDF hash 相同；
- extractor fingerprint 相同；
- manifest 和 artifact hash 完整；
- 状态满足调用需求。

只有以下情况重新提取：

- PDF 内容变化；
- 提取器或参数变化；
- 缓存损坏或缺失；
- 旧缓存为 partial 且目标页不可用；
- 用户明确要求重建。

重新提取写入新 revision，完成前不替换 current。并发请求对同一 cache key 合并为一个
有界任务，不重复执行。

## 7. 文本搜索与证据定位

### 7.1 默认搜索

Agent 通过 `library_exec` 对缓存 TXT 执行命令：

```text
rg --follow -l <query> cache/
rg -n -C <context> <query> <text>
awk with RS="\f" to compute PDF page
paper-cache page <paper-id> <page>
```

全文 TXT 保留 `\f` 页面分隔符；`awk` 的 record number 可用于确定 PDF 页码。最终引用
前应使用 `paper-cache page` 或等价的有界页读取获得稳定 evidence ref。

### 7.2 Evidence ref

稳定 evidence ref 至少绑定：

```text
paper_id
pdf_sha256
extractor_fingerprint
page
source_kind
artifact_hash
optional region
```

`rg` 的行号不是 PDF 页码，不能直接作为用户引用。命令输出 artifact ref 也不能单独
替代页级 evidence ref。

### 7.3 可选检索增强

如果冻结评测显示 TXT 命令搜索存在稳定漏召回，可单独比较：

1. `rg`；
2. SQLite FTS5；
3. BM25；
4. 仅在前三者不足时评估 embedding/vector。

任何增强必须：

- 不改变页级原文真源；
- 不成为 PDF 缓存前置条件；
- 有独立质量、延迟、成本和隐私评测；
- 作为新的 bounded slice 单独批准。

## 8. 安全边界

### 8.1 权限

- 论文库读取来自 macOS security-scoped bookmark；
- 派生缓存目录由 Runtime 单独管理；
- 模型不能提供任意缓存路径；
- `library_exec` 无网络；
- `inspect_page` 只能使用已授权 `paper_id`；
- `library_edit` 是唯一用户论文库写入口；
- Skill、PDF、TXT 和命令输出不能扩大权限。

### 8.2 资源限制

每次工具调用限制并记录：

- wall-clock deadline；
- CPU 和内存；
- 最大进程数；
- 最大临时空间；
- stdout/stderr；
- 最大页面数；
- 渲染像素和图片字节；
- 命令长度与管道复杂度；
- attempt 总预算。

### 8.3 命令策略

采用 Codex 的分层执行方式：

- 输入使用 `cmd`，实际命令、cwd 和 sandbox policy 共同生成稳定 `command_ref`；
- cwd 固定为逻辑 workspace，环境变量和 PATH 由 Runtime 完整构造；
- 授权论文库和派生缓存只读，只有调用级 `scratch/` 可写；
- OS sandbox 默认拒绝库外读取、授权根写入和网络访问；
- sandbox profile 计算 hash 并随执行结果进入 trace；
- 不提供模型可选 shell、登录 shell、远程环境、额外权限或 sandbox 失败后的升级路径；
- timeout、进程组终止、聚合 head-tail 输出捕获和 token 截断由 Runtime 确定性执行。

不得只用 Prompt 禁止危险命令。

### 8.4 副作用

- `library_exec` 对用户论文库只读；
- `paper-cache` 只写内容寻址的派生缓存；
- `inspect_page` 只生成有界临时渲染或派生 artifact；
- `paper_set` 只追加应用状态事件；
- `library_edit` 承担全部用户可见写操作；
- interrupted/failed side-effect call 不自动重放。

## 9. 状态、恢复和审计

三个状态真源保持独立：

- session：模型历史、工具调用和 `paper_set` 事件；
- job：attempt、审批、中断、恢复和最终结果；
- trace：命令、工具、成本和诊断。

权威 trace 至少保存：

- 工具名和 schema version；
- 完整校验参数或安全摘要；
- 实际命令；
- executable 和版本；
- cwd/environment；
- sandbox profile/hash；
- approval decision；
- 输入/输出 artifact refs；
- cache hit/miss/rebuild 原因；
- timeout、truncation 和 exit code；
- `paper_set` coverage；
- token、成本和耗时；
- terminal status。

模型自报的工具使用记录不作为权威 trace。

## 10. 评测与验收

### 10.1 冻结条件

- 使用现有 14 篇论文、四轮 query 和私有 Gold；
- 不根据 v2 答案修改 Gold；
- 记录精确模型、endpoint、参数、工具版本和 Skill version；
- 网络关闭；
- 保存完整工具 trace；
- 同一配置至少重复三次；
- 报告中位数和最差结果。

### 10.2 质量门槛

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

重复运行要求：

- 三次中位数高于 Codex；
- 最差一次没有 major error；
- 每次约束保持和遍历完成均为 100%；
- 作者—方法归属每次为 100%；
- 正常文字层论文不因缓存或页面核验产生质量回归。

### 10.3 工具行为门槛

- 首次缓存生成覆盖全部 14 篇 PDF；
- 第二个全新会话对相同 PDF 达到 100% cache hit；
- cache hit 不重复运行全文 `pdftotext`；
- 修改一篇 PDF 只使该内容 hash 的缓存失效；
- extractor fingerprint 变化生成新 revision；
- 命令输出截断、超时和非零退出明确可见；
- 14 篇任务不使用网络；
- `paper_set` 在 T02→T03→T04 保持正确派生关系；
- “全部”任务 coverage 未完成时不得报告 complete；
- 所有关键引用可解析到 PDF hash 和页码。

### 10.4 消融

至少比较：

1. Codex 原始命令策略；
2. `library_exec` + 临时 TXT；
3. `library_exec` + 跨会话缓存；
4. 缓存 + `inspect_page`；
5. 缓存 + `paper_set`；
6. 完整 v2 Skill。

v2 不以 embedding 消融为前置条件。只有文本命令检索未达到门槛时，才规划独立检索增强
实验。

### 10.5 外推边界

14 篇同领域学位论文只证明当前 benchmark。对外声称一般化优势前，还需未参与设计的：

- 正常文字层 PDF；
- 扫描件；
- 双栏；
- 中英文混排；
- 表格；
- 公式；
- 图表依赖问题；
- 大规模个人论文库。

## 11. 实施 slices

### Slice 0：计划冻结

交付：

- 本文档；
- `TASKS.md` 继续指向本文档；
- 用户确认最终工具方向；
- 不修改产品代码或公开工具。

当前状态：用户已确认方向。完成本文档重写后停止；进入 Slice 1 需要单独授权。

### Slice 1：内容寻址 TXT 缓存

目标：复现 Codex 的快速全文 TXT 提取，并提供跨会话复用。

当前状态：已完成。冻结 14 篇、1169 页论文首次缓存全部生成，耗时 4.211 秒；新缓存
实例二次检查 14/14 命中，耗时 83 毫秒；三个同 key 并发请求只生成一个 revision。

范围：

- Poppler packaging/licensing 评估；
- `pdfinfo`/`pdftotext` adapter；
- extractor fingerprint；
- manifest；
- `paper-cache status/ensure/page`；
- cache hit/miss/invalidation；
- 原子发布和并发去重。

非目标：

- 修改模型工具表面；
- OCR；
- `paper_set`；
- FTS/BM25；
- embedding；
- 删除旧代码。

### Slice 2：Codex-style `library_exec`

目标：让模型使用少量通用命令原语读取论文库和缓存。

当前状态：已按 1.1 节完成 schema、逻辑 workspace、sandbox、输出和 broker 的逐项
源码复核，映射见 `docs/design/library_exec_codex_source_mapping.md`。未在 Codex 中
找到对应机制的部分已标记为 Paper Copilot 专用适配，必要差异已获用户确认，现有实现
也已按映射回改。Runtime 手工验收已覆盖普通命令、`rg`、`pdfinfo`、`pdftotext`、
缓存搜索、权限拒绝、无网络、timeout、进程组终止、文件大小限制、head-tail 输出、
broker 和权威 trace。`.app` 使用 Codex package builder 同源的固定 ripgrep 15.2.0
官方发布包、archive size/SHA-256 校验和临时缓存，打包验收已通过签名、PCRE2 搜索、
Runtime 握手、真实 `library_exec rg`、broker 和权威 trace。Slice 2 已完成；Slice 3
需要单独确认后开始。

范围：

- v2 schema/dispatch；
- Codex-style command resolution 和 sandbox policy；
- 固定授权根和只读缓存；
- sandbox；
- timeout/output caps；
- authoritative command trace；
- `paper-cache` 命令接入。

非目标：

- 交互式 PTY；
- 任意本机 shell；
- 网络；
- 用户论文库写入；
- 其他三个 v2 工具。

### Slice 3：论文研究 Skill

状态：已完成。实现位于
`src/paper_copilot/agents/skills/research-papers/SKILL.md`，Codex 源码映射见
`docs/design/research_skill_codex_source_mapping.md`。Skill 在首次运行、恢复和
context compaction 后注入，版本与正文 SHA-256 进入权威 trace 和 final payload。
Slice 4 已按单独确认完成。

目标：用可审查 Skill 复现 Codex 命令搜索和证据定位工作流。

范围：

- 缓存检查；
- 全文提取；
- `rg`/`awk` 搜索；
- 页码定位；
- bounded evidence；
- incomplete/unresolved 表述；
- Skill version 和 source mapping。

非目标：

- 新 LLM worker；
- 结构化全文字段；
- 向量 RAG；
- 公开工具切换。

### Slice 4：`inspect_page`

状态：已完成。实现位于
`src/paper_copilot/agents/inspect_page_tool.py`，Codex 源码映射见
`docs/design/inspect_page_codex_source_mapping.md`。当前只完成内部工具、模型
modality、图像工具结果 transport 和权威 metadata；公开工具列表保持不变，留待
Slice 6 统一切换。真实 134 页论文的整页、归一化区域、纯文本能力拒绝和越界页手工
验收均已通过。

目标：提供论文专用的单页视觉核验。

范围：

- `paper_id + page + region`；
- `pdftoppm`；
- capability negotiation；
- image output 和 unsupported-model rejection；
- render/evidence metadata；
- unresolved。

非目标：

- OCR 依赖；
- 批量页面工具；
- 第二云端模型；
- 全文入库。

### Slice 5：`paper_set`

状态：已完成。实现位于
`src/paper_copilot/agents/paper_set_tool.py`，Codex 源码映射见
`docs/design/paper_set_codex_source_mapping.md`。当前已完成内部工具、append-only
application event、PDF/cache revision 快照、coverage/stale 和 recovery source
session 重放；公开工具列表保持不变，留待 Slice 6 统一切换。

目标：修复跨轮集合遗忘和遍历完成性。

范围：

- create/derive/record_evidence/status；
- immutable set；
- ingest/cache revision snapshot；
- coverage；
- stale；
- session/resume 重建。

非目标：

- 搜索；
- RAG；
- PDF 提取；
- 回答生成。

### Slice 6：公开工具切换与安全收敛

状态：已完成实施。模型公开表面已切换为四个 v2 工具，内建 Skill 已更新为 version 2，
macOS 通用审批协议已核对兼容，异步 Runtime 拒绝未公开旧名称，架构和 Codex 源码映射
已同步。旧实现按计划保留为不可由模型调用的回滚代码。源码映射见
`docs/design/tool_surface_v2_codex_source_mapping.md`。

目标：公开四个 v2 工具，并冻结统一安全边界。

范围：

- `library_exec`；
- `inspect_page`；
- `paper_set`；
- `library_edit`；
- 模型工具列表切换；
- macOS approval UI 兼容；
- adversarial PDF/file names/command output；
- Runtime 拒绝旧模型工具名称；
- `ARCHITECTURE.md` 更新。

旧实现仍保留为不可调用的回滚代码，不在本 slice 删除。

### Slice 7：冻结评测

目标：完成三次可审计四轮评测及第 10 节消融。

完成条件：

- 达到质量和工具行为门槛；
- 报告所有失败、partial 和 unverifiable 字段；
- 不使用模型自报替代 trace；
- 用户决定是否进入旧实现删除。

### Slice 8：删除旧实现

目标：只保留 v2 和仍被复用的稳定基础设施。

删除候选：

- `ReadPaperTool`；
- `SkimPaperTool`；
- `ExtractPaperTool`；
- `LinkRelatedPapersTool`；
- 旧 `read_pipeline`；
- 旧 `paper_search`、query、compare 和 related dispatch；
- Composer 专用工具；
- 只服务旧工具的 schemas、prompts 和兼容代码；
- v2 不再使用的 fields/embedding 索引路径。

保留候选：

- append-only session；
- job/attempt/recovery；
- macOS authorization 和审批 UI；
- observability 基础设施；
- MCP/客户端协议边界；
- 能证明仍被 v2 使用的纯函数和存储原语。

删除前必须有：

- v2 eval 通过；
- App/MCP 对旧工具零调用证明；
- 数据迁移、保留或明确重建策略；
- 用户明确确认删除 slice。

## 12. 依赖与成本

本计划不新增 LLM call site，不增加每篇论文的固定模型调用，也不预设 embedding 成本。

潜在依赖：

- Poppler：Slice 1 前完成打包、签名、sandbox、固定版本、GPL 和传递依赖审查；
- OCR：不属于当前 v2，未来如需要必须单独批准；
- FTS/BM25/vector：不属于当前 v2 基线，未来按独立实验决定。

终端用户不得被要求安装 Homebrew。任何新增依赖必须按仓库规则单独批准，并给出无新增
依赖替代方案。

## 13. 非目标

- 不建设 PostgreSQL 或独立向量数据库；
- 不把 embedding 作为入库条件；
- 不把结构化字段作为问答前置条件；
- 不让一个模型工具隐藏完整论文研究流水线；
- 不为每个论文任务新增专用模型工具；
- 不建设托管 OCR、托管视觉模型或云端论文库；
- 不新增账号、支付、同步或多租户；
- 不为 benchmark 论文、作者、方法或 query 写特例；
- 不让 SwiftUI 重写 Python Core；
- 不在一个 slice 中同时替换全部工具；
- 不宣称纯文本模型可以理解所有图、表和公式；
- 不在 v2 验收前删除可恢复旧系统的 Git 历史。

## 14. 下一步决策门

本文档完成后停止。开始 Slice 1 前，用户需要单独确认：

1. 只实施内容寻址 TXT 缓存，不修改公开工具；
2. 接受 Poppler 作为首选 PDF substrate 候选；
3. 允许进行 GPL、打包、签名和 sandbox 评估，但尚不添加依赖；
4. 接受 `paper-cache` 作为 `library_exec` 可调用的确定性命令原语；
5. 接受 v2 默认不建设向量 RAG；
6. 接受旧 `read_paper`/`paper_search` 在公开切换前继续保留为现状。
