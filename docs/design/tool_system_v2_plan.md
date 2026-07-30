# Paper Copilot 工具系统 v2 计划

状态：三套目标系统单次四轮均已完成并形成 Gold revision 2 工作评分；下一步转入同模型 Agent 差距根因研究
日期：2026-07-30
文档职责：只记录方向、阶段、决策门和 Definition of Done。工具契约、源码映射、实验
明细和历史过程保存在第 9 节链接的专项文档中，不在本计划重复。

## 1. 目标与边界

目标是让 Agent 用少量、可组合的原语完成论文研究，同时由 Runtime 持有安全、缓存、
证据、恢复和完成性不变量。

固定原则：

1. Agent 编排研究步骤，工具只执行一次明确动作。
2. PDF 和页级产物是证据基础；摘要、模型文本、搜索命中和 embedding 不是原文真源。
3. 正常文字层 PDF 默认走全文 TXT、确定性搜索和页级读取，不以向量 RAG 为前置条件。
4. Skill 指导工作流，但不承担授权、安全或完成性校验。
5. session、job 和 trace 保持 append-only，并分别承担模型历史、运行状态和审计职责。
6. Agent 基础设施先映射固定 Codex 源码，再做必要的论文领域适配。
7. 一次只实施并验收一个 bounded slice。

不在 v2 当前范围内：

- OCR、云端论文库、第二模型审稿；
- PostgreSQL、向量数据库或强制 embedding；
- 用模型判断引用是否语义蕴含自然语言 claim；
- benchmark 专用作者、标题、方法、答案或关键词；
- SwiftUI 重写 Python Core；
- 在冻结评测通过前删除旧实现。

## 2. 当前实现

当前模型可见工具表面已切换为：

| 工具 | 当前职责 | 状态 |
|---|---|---|
| `library_exec` | 在授权论文库和只读缓存上批量搜索、读取带页边界文本 | 已实施 |
| `inspect_page` | 检查一张明确 PDF 页面或区域 | 已实施 |
| `library_edit` | 执行授权论文库中的用户可见写操作 | 已实施 |

Runtime preflight 负责批量 cache ensure；`library_exec` 不再接受 `paper-cache`
broker 命令。模型直接读取 `research_cache_index` 给出的逻辑缓存路径，实际命令输出
随完整会话历史保留，不再使用模型可见的文本页面专用工具。

旧 `read_paper`、`paper_search`、query/compare/related、Composer 专用工具、
`library_files` 和 `notes_patch` 已从模型工具表面移除，但回滚代码尚未删除。

当前架构真源是 `ARCHITECTURE.md`。本计划中的候选接口只有在实施并验收后才能写入
架构文档。

## 3. 已完成阶段

| Slice | 结果 | 详细依据 |
|---|---|---|
| 0 计划冻结 | 已完成 | 本计划与 Git 历史 |
| 1 内容寻址 TXT 缓存 | 已完成 | 14 篇、1169 页首次生成 4.211 秒；二次 14/14 命中 83 ms |
| 2 `library_exec` | 已完成 | `library_exec_codex_source_mapping.md` |
| 3 论文研究 Skill | 已完成 | `agent_infrastructure_codex_source_mapping.md` |
| 4 `inspect_page` | 已完成 | `agent_infrastructure_codex_source_mapping.md` |
| 5 `paper_set` | 历史兼容，不再模型可见 | `paper_set_codex_source_mapping.md` |
| 6 公开工具切换 | 已切换为按能力暴露的统一 registry；当前最多五工具；快速测试 45/45 通过 | `agent_infrastructure_codex_source_mapping.md` |
| 7 冻结评测 | 三套目标系统单次四轮均完成并形成工作评分；独立复核已取消，结果仅作诊断输入 | `codex_multi_thesis_blind_experiment_plan.md` |
| 8 删除旧实现 | 未开始 | 仅在 Slice 7 通过并获确认后执行 |

已完成的底层能力包括：

- 以 PDF SHA-256、提取器版本和参数标识跨会话缓存；
- 固定逻辑 workspace、过滤环境、无网络 sandbox、deadline 和输出预算；
- 缓存 preflight、原子发布、revision 和并发去重；
- Skill catalog 常驻，正文由 `load_skill` 首次按需注入，compaction 保留已加载版本；
- `inspect_page` 的模型能力检查和页级渲染；
- `paper_set` 的 append-only 事件、集合快照、stale 检查和恢复；
- session tool call 与 lifecycle trace 的 call ID 对齐。

## 4. Query 1 结论

旧实现的冻结 Query 1 正常 `end_turn`，但页面证据合同未通过：

| 指标 | 结果 |
|---|---:|
| Preflight | 14/14 成功，0 失败，309 ms |
| 模型工具调用 | 113 |
| `library_exec` | 84 |
| `paper_set` | 29 |
| Lifecycle trace | 113 started / 99 completed / 14 failed |
| LLM 调用 | 23 |
| 总耗时 | 约 280 秒 |
| 费用 | 约 ¥0.161 |

关键失败：

- 14 次 `paper_set` 调用因 evidence ref 缺少外层 `[]` 失败后重试；
- 3 次 `library_exec` 非零退出；
- 没有调用 `paper-cache page` 或 `inspect_page`；
- 模型以 approximate pages 使 `paper_set` 显示 14/14 complete；
- 最终 14 个引用均使用 8 位短 hash，不符合完整 SHA-256 合同；
- `heuristic_v1` 仍错误报告 evidence coverage 1.0；
- 与旧版 Query 1 的 103 次调用相比增加 10 次。

session 与 trace 的 113 个 started call ID 完全一致。此前将 99 个 completed 误认为全部
lifecycle 调用的结论已纠正，trace 修复不属于下一 slice。

权威产物：

- `/Users/a123/.paper-copilot/jobs/job-20260728T124406-7645b6c00e/attempts/1/trace.jsonl`
- `/Users/a123/.paper-copilot/papers/paper-copilot-job-20260728T124406-7645b6c00e-attempt-1/session.jsonl`
- `/Users/a123/.paper-copilot/papers/paper-copilot-job-20260728T124406-7645b6c00e-attempt-1/research-report.md`

最后一个路径以实际 job 目录为准；专项实验文档保存完整统计和纠正记录。

修订后的冻结 Query 1 已通过：

| 指标 | 结果 |
|---|---:|
| Runtime 论文准备 | 14/14 |
| 不同观察页面 | 46 |
| `library_exec` | 12 |
| `read_page` | 74 |
| 有效引用 | 28 |
| active-set 引用覆盖率 | 1.0 |
| LLM 调用 | 33 |
| 总耗时 | 209.5 秒 |
| 费用 | ¥0.19964604 |

## 5. 已撤下的持续排除工具

曾为运行冻结 Query 2 增加最小 `update_research_scope`。Codex 四轮基线没有发生
`constraint_memory_failure`，Paper Copilot 实跑又确认模型可能不调用该工具，因此它
不是由基线失败支持的有效改造，现已从工具表面、Runtime 恢复和上下文注入中删除。
历史 session 事件保持 append-only，仅作为原始实验记录。

## 6. 页面证据 slice

### 6.1 已完成目标

把页面读取和证据登记收回 Runtime，减少模型协调工具协议的负担。论文专用最终引用
校验后来因 Codex 默认不存在该机制而撤下。

候选目标表面：

| 能力 | 候选处理 |
|---|---|
| `paper_set` 模型工具 | 删除 |
| `paper-cache status/ensure` | 已由 Runtime preflight 接管，不再暴露给模型 |
| `paper-cache page` | 从 `library_exec` broker 移除；直接读取预生成 `layout.txt` |
| `inspect_page` | 保留，负责视觉页面读取 |
| active paper set | 本 slice 固定为 Query 1 的 Runtime preflight 论文预算 |
| 页级证据 | 文本使用权威命令与模型可见输出；`inspect_page` 继续登记视觉页事实 |
| 完成性与引用 | 默认不拦截；可解析引用转成可点击论文页链接 |

这会删除工具入口，不会删除底层能力：

- 删除 `paper_set` 不等于删除集合、stale、coverage 和恢复；
- 删除 `paper-cache` broker 不等于删除内容寻址缓存或页文本读取；
- `library_exec` 只读取授权的逻辑 library/cache 根，不开放宿主任意路径；
- evidence ledger 不保存完整正文、图片、PDF 或宿主绝对路径。

### 6.2 已确认决策

`runtime_research_evidence_codex_source_mapping.md` 已按严格 Codex 方向修订：

1. 文本命令、模型可见输出和完整会话历史；
2. Query 1 active set 等于 Runtime preflight 成功准备的论文集合；
3. 旧 `paper_set` 事件可重放但不再产生 citation-grade evidence；
4. `library_exec` 明确拒绝全部 `paper-cache` broker 命令；
5. 通用 Stop hook 默认关闭，Paper Copilot 不配置论文专用 handler。

Query 2–4 的范围约束继续由冻结用户消息和同一 conversation 的历史表达，不再维护
产品特定的结构化排除状态。

该映射检查的固定 Codex source ref 为：
`61a44880a85d2fd0d8770908dea5733495e571c8`。Codex 已提供可选 Stop hook 的
block-and-continue 结构，但没有 PDF 页证据、论文集合或 Markdown 论文引用校验；
当前只保留页面证据与安全链接这一最小领域适配。

### 6.3 实现范围

预计修改：

- `src/paper_copilot/agents/loop.py`
- `src/paper_copilot/agents/paper_copilot.py`
- `src/paper_copilot/agents/library_exec_tool.py`
- `src/paper_copilot/agents/inspect_page_tool.py`
- `src/paper_copilot/agents/paper_set_tool.py`
- 新增 `src/paper_copilot/agents/read_page_tool.py`
- 新增 `src/paper_copilot/agents/research_evidence.py`
- research Skill、工具注册、相关设计和状态文档

预计不修改：

- SwiftUI、API transport、MCP 和数据库 schema；
- PDF cache 文件格式、模型配置和依赖；
- trace lifecycle 语义；
- 旧实现删除范围。

## 7. 页面证据 Definition of Done

以下为当前实现条件；此前冻结 Query 1 的通过结果属于已撤下的结束拦截版本：

- 模型工具表面不再包含 `paper_set`；
- `library_exec` 不再接受 `paper-cache status/ensure/page`；
- 文本读取只通过 `library_exec`，命令与实际返回输出进入权威 trace 和会话历史；
- 只有成功返回给模型的 `inspect_page` 产生结构化视觉页证据事实；
- session/recovery 可确定性重建 active set 和 evidence ledger；
- 没有 Stop handler 时，任何模型 `end_turn` 都直接结束；
- 合法完整引用 `[<64-lowercase-hex>:page[<positive-int>]]` 转成可点击页码链接；
- 未知或格式错误的引用保持原样，不触发自动重答；
- `heuristic_v3_unvalidated` 明确不冒充引用校验；
- 不新增 LLM call site、依赖、网络、OCR、embedding 或固定逐篇模型调用；
- session `tool_use` 与 trace `tool_call.started` 的 call ID 集合保持一致。

按照仓库规则，设计修订、代码实施、定向验证和冻结 Query 1 重跑分别属于明确步骤。
未获当前步骤授权时不提前进入下一步。

## 8. Slice 7 冻结评测

三套目标系统已分别在全新连续会话中完成单次四轮运行，并按 Gold revision 2 形成
工作评分。正式冻结仍遵循以下要求：

1. 使用冻结的 14 篇论文、四轮 query 和私有 Gold；
2. 先按同一 Gold 生成新的 Codex CLI JSONL v2 基线报告；
3. 同一配置至少重复三次，保存完整 session、job 和 trace；
4. 报告中位数、最差结果及全部 failure、partial、unverifiable 字段；
5. 比较质量、集合召回、约束保持、页级引用、工具调用、token、费用和耗时；
6. 执行经确认的工具消融；
7. 不使用模型自报替代权威 trace。

Codex 基线已经按 Gold revision 2 重新评分。当前结果只有一次运行，尚未满足第 3–4
项的重复实验要求。用户已取消独立评分复核，因此这些分数不冻结为统计意义上的正式
结果，只作为下一阶段 Agent 根因诊断的描述性输入。当前不沿用已删除的旧桌面端分数，
也不根据 v2 输出修改 Gold。

Slice 7 通过后，另行确认 Slice 8，才可删除旧工具和只服务旧流程的实现。

## 9. 专项文档索引

| 文档 | 职责 |
|---|---|
| `ARCHITECTURE.md` | 当前已实现架构和模块边界 |
| `TASKS.md` | 当前状态、下一动作和工作纪律 |
| `docs/design/library_exec_codex_source_mapping.md` | 命令执行、sandbox、审批和 trace |
| `docs/design/agent_infrastructure_codex_source_mapping.md` | 已实施 Skill、页面视觉和公开工具基础设施 |
| `docs/design/paper_set_codex_source_mapping.md` | 历史集合工具及兼容事件 |
| `docs/design/runtime_research_evidence_codex_source_mapping.md` | 当前 `read_page`、Runtime evidence 和 Query 1 完成合同 |
| `docs/design/codex_multi_thesis_blind_experiment_plan.md` | 冻结实验、指标和运行记录 |

## 10. 下一步

对照同一 DeepSeek V4 Pro 在 Codex CLI 与 Paper Copilot 中的既有模型请求、上下文、
工具反馈和权威 trace，定位 T02 UDA 误判、T03 复核遗漏和 T04 单元格不可追溯的首个
分叉点。先形成源码支持的根因表和最小消融建议，不重跑模型、不修改实现、不删除旧代码。
