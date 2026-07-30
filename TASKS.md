# TASKS

> Paper Copilot 当前路线图、状态和下一动作。工程规则见
> [AGENTS.md](AGENTS.md)，当前架构见 [ARCHITECTURE.md](ARCHITECTURE.md)，详细设计见
> [docs/design/](docs/design/)，历史实现过程见 Git。

更新于 2026-07-30。

## 1. 当前方向

Paper Copilot 是本地优先的个人论文研究工具，通过 SwiftUI macOS 客户端和 Local MCP
Server 复用同一 Python Core。

- 当前采用 BYOK。
- PDF、索引、session、报告和 trace 默认保存在本地。
- 只有本地选择后的必要上下文发送给用户配置的模型。
- 当前不建设账号、支付、托管模型、云端论文库或多租户。
- Agent 基础设施采用 Codex-first 设计；默认逐个推进 bounded slice，用户明确授权一组
  已命名 slice 时可按边界顺序连续实施。

## 2. 当前工作：Agent 工程对齐 E1–E5、E7

状态：E1 Conversation-owned Session、E2 World State、E3 Unified Library
Environment、E4 Controlled Python、E5 Tool Registry 与 E7 Skill Registry /
On-demand Loading 均已写入工作区。按仓库规则尚未运行完整测试、
工具协议验证、真实 provider smoke 或模型评测。

目标：以固定 Codex 源码 `fe01054a28fa4bd04716d9ceadb410f2443a50ce` 为真源，把
Agent 的 session、上下文、执行环境、工具 registry、provider wire 与 Skill 生命周期
向同一固定 Codex 源码结构收敛；论文授权、Seatbelt、缓存、页码引用和不可信内容边界
保持产品域适配。

本 slice 依次完成：

1. conversation session 目录拥有持久 `LibraryEnvironment` 和固定 logical cwd；
2. `library/`、`cache/` 保持只读，`scratch/` 跨同一 conversation 的命令保留；
3. process manager 分配不透明 session/chunk ID，并限制活动进程数；
4. `library_exec` 用 `yield_time_ms` 替代一次性硬 timeout，未退出进程进入环境 process
   store；
5. 新增 `library_write_stdin`，支持写字符或空写轮询后续输出；
6. 用户中断和 conversation 删除终止环境内全部进程组。

Definition of Done：

- 长命令可 yield，并由 session ID 继续轮询；
- stdin 写入和空写轮询返回增量 chunk；
- scratch 在同一 conversation 的多次命令间保留；
- completed/yielded 输出使用统一字段；
- 中断终止整个进程组；
- 越权读取、library/cache 写入和网络继续被 Seatbelt 阻止。

详细计划见
[codex_paper_copilot_agent_gap_investigation.md](docs/design/codex_paper_copilot_agent_gap_investigation.md)。

当前结论：

- 两套系统的 UDA 误判和 T03 复核遗漏是共同失败，不构成系统间分差；
- 既有冻结运行通过跨 job `recovery_base` 保留了完整模型历史，因此历史丢失不是当次
  分差；E1 进一步消除了“每轮新 session + history copy”的工程差异；
- 新 chat 数据由 conversation 直接拥有 session；`recovery_base` 只用于旧数据的一次
  append-only 迁移，不再作为正常 follow-up 机制；
- Paper Copilot 的逐页证据合同增加了“搜索—定位—逐页读取”的协调成本，实际深章节
  覆盖少于 Codex 的批量读取；
- system prompt 的固定 900 词上限已删除；现在要求先完整满足用户指定字段和证据，
  再保持简洁，不得为缩短篇幅省略必要限定、不确定性或页码引用；
- system prompt 和 `research-papers` Skill 已进一步按 Codex 的目标导向语义适配：
  用户指定输出形态优先，不再强制固定报告标题；以请求字段和证据缺口维护工作清单，
  在安全且相关的读取仍可补全关键结论时继续调查，并按已知位置、搜索结果和输出截断
  情况自适应选择批量搜索或直接读页；
- 跨轮历史丢失、狭义 Agent loop 的 dispatch/feedback、工具失败、提前停止和本次
  compaction 均未得到根因证据。

已严格改为 Codex 式文本读取：删除模型可见的 `read_page`/`read_pages`，模型只通过
`library_exec` 批量搜索和读取带 PDF 页边界的缓存文本，实际命令输出随完整会话历史
保留；Runtime 不再为文本页设置独立登记工具。`inspect_page` 只负责必要的视觉检查。
跨轮历史保留已经实现，固定篇幅上限已经删除。未经确认不执行模型重跑。

### 2.1 已完成背景：工具系统 v2 与三方工作评分

状态：已删除论文专用结束拦截并改为 Codex 式默认不阻断；模型直接输出可点击页码链接，
Runtime 引用层不再改写最终答案。Gold revision 2 下三套目标系统的单次四轮运行和工作
评分均已完成：Codex CLI + `gpt-5.6-sol`、Codex CLI + DeepSeek V4 Pro、Paper
Copilot + DeepSeek V4 Pro。

已完成：

- 冻结 14 篇、1169 页论文、四轮 Query 和私有 Gold；
- 完成原生 Codex CLI 四轮运行并保存逐轮 JSONL 与原生 rollout；
- 完成 DeepSeek V4 Flash 的全新 conversation 四轮运行；
- 完成 Paper Copilot + DeepSeek V4 Pro 的全新 conversation 四轮运行和既有工作评分；
- 完成 Codex CLI + DeepSeek V4 Pro 的本地 adapter、兼容性 smoke 和单次四轮运行；
- 裁决 Gold 中张耀斌论文的监督设定为 UDA，并删除与冻结 Query 冲突的工具自报要求；
- 生成 Gold revision 2 的三方工作评分；
- 完成内容寻址 TXT 缓存、`library_exec`、研究 Skill、`inspect_page`、`paper_set` 和
  四工具公开表面；
- 将批量 cache ensure 移到模型循环前的 Runtime preflight；
- 确认 session 与 lifecycle trace 的 113 个 started call ID 完全一致。

冻结 Query 1 旧失败运行结论：

- Preflight 14/14 成功，0 失败，309 ms；
- 113 次模型工具调用，比旧版 103 次增加 10 次；
- 没有调用 `paper-cache page` 或 `inspect_page`；
- approximate pages 仍使 `paper_set` 显示 14/14 complete；
- 最终引用使用 8 位短 hash，`heuristic_v1` 仍误报 coverage 1.0；
- 正常 `end_turn`，但不满足 bounded slice 的完成条件。

旧阻塞是确定性证据合同，而不是 trace：

```text
模型声明页码
→ 当前 paper_set 接受
→ coverage complete
→ 未观察页面和短 hash 仍可进入最终报告
```

[Runtime 证据源码映射](docs/design/runtime_research_evidence_codex_source_mapping.md)
最初实施了以下接口：

```text
read_page + inspect_page
→ Runtime evidence ledger
→ Query 1 preflight active-set coverage
→ 论文专用结束校验
```

实现删除模型可见 `paper_set`，并从 `library_exec` 移除 `paper-cache` broker；底层
内容寻址缓存、集合状态、stale、coverage 和恢复能力继续由 Runtime 持有。

冻结 Query 1 修订后重跑确认 Runtime 获得 14/14 论文、46 个不同页面的真实证据；
12 次 `library_exec` 和 74 次 `read_page` 均完成且无失败，最终 28 条引用全部有效，
active-set 引用覆盖率为 1.0，正常 `end_turn`。本轮 33 次模型调用、耗时 209.5 秒、
费用 0.19964604 元。该结果属于已撤下的论文专用结束校验实现，只保留为历史记录。

曾为 Query 2–4 增加 `update_research_scope`，把持续排除保存为结构化 session 事件。
Codex 四轮基线没有出现范围记忆失败，Paper Copilot 实跑又确认模型可能只在正文声明
排除而不调用工具，因此该产品特定机制已删除。历史 session 中的事件保留为原始记录，
后续任务不再读取或注入。

固定 Codex 源码复核后，确认 Codex 默认没有论文覆盖或页码引用校验。当前实现因此：

- 通用 Agent loop 只保留可选 Stop hook，默认没有 handler；
- Paper Copilot 不再拦截模型回答，不再自动重答或替换为 Incomplete；
- `research_cache_index` 给模型提供 Runtime 分配的应用内 citation base，模型直接输出
  最终 Markdown 链接；
- Runtime 引用层不解析、验证、替换或清理模型最终答案；
- Chat result 携带可信 citation ref 映射，macOS 解析后继续执行授权目录和 PDF 校验；
- macOS 点击链接后在授权目录内打开对应 PDF 页；
- 流式增量事件不再每个字都强制滚动到底部；
- 页面证据 ledger 继续保留，但不作为最终回答门槛。

本次定向验证：Agent loop、论文范围和 Paper Copilot 测试 38/38 通过；macOS Debug
构建成功。

DeepSeek V4 Flash 四轮结果：

- 4/4 正常 `end_turn`，总耗时约 249 秒，总费用 0.3512006 元；
- 10 次 `library_exec`、52 次 `read_page`，页面读取无失败；
- Gold revision 2 下 required claim occurrence 共 71 项：严格正确率 57.7%，加权
  正确率 66.2%，claim coverage 76.1%；
- Query 2 的 Markdown 引用链路可用，Query 3–4 退化为裸页码；
- 最终 11 篇论文集合正确，但 Query 2 曾错误排除李之赫，Query 4 未做到关键单元格
  逐项可追溯。

Gold revision 2：

- 张耀斌论文 PDF 第 37–38 页明确为“源域监督训练 + 目标域无监督训练”，因此标为
  `unsupervised_domain_adaptation`；刘章平维持 `fully_unsupervised`；
- 新增 C044、E044、E045，T02–T04 将 UDA taxonomy 纳入 required claims；
- 删除四轮中冻结 Query 未要求的模型工具自报约束，工具行为只从权威 trace 评分；
- revision 1 已保留，裁决记录和更新后的工作评分位于私有实验目录。

DeepSeek V4 Pro 烟测：

- 全新 conversation 输入“你好”，实际模型为 `deepseek-v4-pro`；
- 0 次工具调用，正常流式 reasoning/answer 和 `end_turn`，无错误或重试；
- 耗时约 3.56 秒，输入 6977 tokens、输出 104 tokens、费用 0.021555 元；
- 当前每个请求都注入完整 `research_cache_index`，因此模型可看到论文数量和逻辑文件名；
  本轮不调整该行为。

Paper Copilot + DeepSeek V4 Pro 四轮结果：

- conversation 为 `conversation-20260729T141953-65092f325e`，4/4 正常 `end_turn`；
- 总耗时约 537 秒，总费用 0.7021012 元；
- 18 次 `library_exec`、57 次 `read_page`，权威 trace 中均正常完成；
- 42 次模型调用，uncached input 142044、cache read 2411008、output 35949 tokens；
- Gold revision 2 工作评分：严格正确率 57.7%，加权正确率 72.5%，claim coverage
  90.1%；
- 最终 11 篇集合正确，四轮均生成应用内页码链接；主要错误仍是把张耀斌判为完全
  无监督而非 UDA，且最终表没有做到关键单元格逐项可追溯。

Codex CLI + DeepSeek V4 Pro 单次四轮结果：

- Codex CLI 0.146.0，经固定本地 adapter 调用 `deepseek-v4-pro`，reasoning effort
  为 `max`；
- 4/4 正常完成，17 次原生命令调用全部成功，总耗时约 538 秒；
- input 2947977、cached input 2656768、output 78147、reasoning output 46959
  tokens；供应商金额无法从权威 rollout 核实；
- Gold revision 2 工作评分：严格正确率 74.6%，加权正确率 81.0%，claim coverage
  90.1%；
- 与原生 Codex 的 76.1% / 83.1% / 90.1% 接近；与 Paper Copilot + 同一 DeepSeek
  模型相比，严格正确率高 16.9 个百分点、加权正确率高 8.5 个百分点。

评分有效性限制：

- 独立评分复核已由用户取消，三方分数继续标为单次运行的工作评分；
- 单次运行不能估计方差或显著性，本轮只将分差作为根因诊断输入，不作统计推断。

当前不做：

- 不运行三次重复或完整消融；
- 不重复运行 Codex；
- 不重新启动独立评分复核；
- 不修改模型、依赖、API、MCP 或缓存格式；
- 不删除旧实现。

主计划见 [tool_system_v2_plan.md](docs/design/tool_system_v2_plan.md)，实验协议见
[codex_multi_thesis_blind_experiment_plan.md](docs/design/codex_multi_thesis_blind_experiment_plan.md)。

### 2.2 E4–E7 实施与边界决策

- **E4 Controlled Python：** `library_exec` 新增受控 Python；继承同一 Seatbelt、
  logical cwd、process store 和 bounded output，只读标准库/library/cache，只写
  `scratch/`，禁用网络、user site、第三方 site-packages、bytecode 和安装能力。
- **E5 Tool Registry：** registration 统一绑定 schema、Pydantic input、definition、
  handler 和 exposure predicate；模型 schema 与 dispatch 从同一 registry 生成，未注册
  或当前能力不可见的名称在执行前失败。
- **E6 Provider 路径：不实施。** Codex CLI 为适配 DeepSeek Chat API 才需要
  Responses→Chat adapter；Paper Copilot 已原生调用 DeepSeek Chat Completions，
  生产路径增加 Responses transport 没有产品价值。曾加入的可选 Responses transport
  与 provider-item 持久化已清理；协议差异只在独立实验中作为 H6 变量控制。
- **E7 Skill Registry / On-demand Loading：** World State 只放 Skill catalog
  metadata；`load_skill` 首次按需返回固定版本正文并记录 conversation lifecycle，同版本
  后续不重复返回，compaction 保留已加载可信 fragment。

## 3. 已完成里程碑

### 产品里程碑

| 里程碑 | 结果 |
|---|---|
| M20 macOS Client Foundation | SwiftUI 客户端、授权目录、模型配置、Runtime、持久 job、流式事件、停止与恢复 |
| M21 Local Read-only MCP | 有界论文查询、证据检查和比较；不接受任意路径或写操作 |
| M22 MCP Long-running Jobs | MCP 启动、查询、获取和取消长任务，复用 job/attempt/recovery |
| M23 Distribution | 自包含 Apple Silicon `.app` 和开发预览 DMG，内嵌 Python 3.12 与 `sqlite-vec` |
| M24 Legacy Web Retirement | 删除 Next.js Web UI 和仅服务旧界面的 API |

### 工具系统 v2

| Slice | 状态 | 设计依据 |
|---|---|---|
| 1 内容寻址 TXT 缓存 | 已完成 | `poppler_packaging_assessment.md` |
| 2 `library_exec` | 已完成 | `library_exec_codex_source_mapping.md` |
| 3 `research-papers` Skill | 已完成 | `agent_infrastructure_codex_source_mapping.md` |
| 4 `inspect_page` | 已完成 | `agent_infrastructure_codex_source_mapping.md` |
| 5 `paper_set` 原接口 | 历史兼容，不再模型可见 | `paper_set_codex_source_mapping.md` |
| 6 公开工具切换 | 当前为 `library_exec/inspect_page/library_edit`；严格采用 Codex 式命令输出历史，尚未运行验证 | `agent_infrastructure_codex_source_mapping.md` |
| 7 冻结评测 | 三套目标系统单次四轮均完成并形成 Gold revision 2 工作评分；独立复核已取消，结果仅作诊断输入 | `codex_multi_thesis_blind_experiment_plan.md` |
| 8 删除旧实现 | 未开始 | 仅在 Slice 7 通过并获确认后执行 |

旧读取、搜索、查询、比较、文件、笔记和 Composer 工具已从模型表面移除，但仍作为不可
调用的回滚代码保留。

## 4. 待规划需求

以下事项不是 active milestone。开始前必须单独确定目标、范围、非目标和验收方式。

### 4.1 Research Idea Composer

- 重新定义用户目标、证据要求、产出契约和失败模式。
- 比较单 Agent、确定性编排和多 Agent 的质量、成本、延迟与可恢复性。
- 不为采用某种架构形式而增加 Agent。

### 4.2 Agent 系统评估

- 盘点 eval suite、Gold、retrieval gate、质量启发式和趋势报告。
- 校准真实任务质量、证据、工具选择、安全、成本和延迟指标。
- 识别不稳定、可投机优化或缺少判别力的指标。

### 4.3 用户与第三方 Skill

- 工具系统 v2 冻结后再规划，第一阶段仅考虑 instruction-only Skill。
- 需要定义发现、查看、校验、启停、删除、冲突、版本、恢复和 trace attribution。
- Skill 不能新增工具、扩大 sandbox、开放网络、安装软件或获得论文库写权限。
- 带脚本、依赖、MCP、connector 或 Plugin 分发的 Skill 属于后续独立阶段。

## 5. Deferred

只有用户明确选择后才进入规划：

- Developer ID、公证、正式公开发布和 App Store；
- 远程 MCP 与目录提交；
- 账号、套餐、托管模型、计费和多设备同步；
- 团队论文库与 Windows/Linux 客户端；
- Zotero 同步和本地模型推理；
- Swift/Rust 局部性能模块；
- 云端数据库、对象存储和 worker 集群；
- Poppler/PyMuPDF 的长期 `.app` 分发与许可证边界。
