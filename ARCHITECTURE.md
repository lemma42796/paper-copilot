# ARCHITECTURE

> Paper Copilot 的当前架构、所有权和硬性边界。产品状态与待办见
> [TASKS.md](TASKS.md)，工程执行规则见 [AGENTS.md](AGENTS.md)，具体接口以代码为准。

更新于 2026-07-27。

## Principles

- **Single Agent:** 系统只有一个 Paper Copilot bounded tool loop；论文读取是有界
  工具链，不做多 Agent 编排。
- **Local first:** PDF、索引、session、报告和 trace 默认保存在本地。只有完成本地
  选择后的必要文本可以发送给用户配置的云端模型。
- **One Core:** macOS 客户端和 MCP Server 复用同一 Python Core，不复制论文处理、
  检索、任务或恢复逻辑。
- **Personal use:** 不建设多租户、分布式存储或托管论文库。
- **Least privilege:** 模型提出工具调用，应用完成参数校验、授权和副作用审批。Prompt
  不是安全边界。

## Product Surfaces

```text
SwiftUI macOS Client ──► local HTTP Runtime ──► chat/jobs ──┐
Local MCP Server ──────► bounded MCP services ──────────────┤
                                                            ▼
                                                    Python Paper Core
```

- `apps/macos/`：界面、security-scoped 论文目录、本地凭据、模型设置、审批交互和
  Runtime 生命周期。
- `api/`：只服务本地 macOS Runtime 的 JSON/HTTP、SSE 和 diagnostics 边界。
- `mcp/`：本地 `stdio` 查询与长任务边界。

SwiftUI 和 MCP 负责协议与产品表面；Python Core 负责 Agent、PDF、RAG、索引、job、
session、恢复、eval 和 observability。

## Module Ownership

```text
apps/macos/

src/paper_copilot/
├── api/            # macOS Runtime HTTP transport
├── chat/           # chat runtime、conversation 和持久 job
├── mcp/            # stdio MCP services
├── agents/         # bounded loop、模型工具和读论文工具链
├── schemas/        # Pydantic 跨边界契约
├── session/        # append-only model/session history
├── retrieval/      # 单篇论文章节切分
├── knowledge/      # 跨论文字段、索引和 hybrid retrieval
├── observability/  # job attempt rollout trace
├── eval/           # 回归、retrieval gate 和趋势评估
└── shared/         # 无上层依赖的公共原语
```

### Transport and orchestration

- `api/` 解析本地 HTTP 请求并输出协议响应，不拥有业务编排。
- `chat/` 组装请求上下文、调用 Paper Copilot 公开入口，并管理 conversation、job、
  attempt、事件、interrupt、resume 和 approval 生命周期。
- `mcp/` 的只读查询直接复用 knowledge/evidence 服务；长任务复用 `chat.jobs`。
  MCP 工具不是内部 Agent 工具。

### Paper Core

- `agents/` 拥有唯一自主循环、模型可见工具、工具策略和单篇论文读取编排。
- `schemas/` 定义 LLM、文件和模块边界上的结构化契约。
- `session/` 只负责 append-only session tree，不理解 Agent 或论文 schema 语义。
- `retrieval/` 只负责单篇论文章节切分，不维护持久索引。
- `knowledge/` 拥有结构化字段、chunks、embedding、图关系和跨论文检索。
- `observability/` 记录 attempt rollout，不参与业务状态决策。
- `eval/` 在隔离数据目录复用公开读取链路，记录质量、成本、延迟和趋势。
- `shared/` 只放无上层业务依赖的日志、错误、成本、cache、环境和纯函数原语。

## Dependency Rules

```text
apps/macos ─► api ─► chat ─► agents ◄── schemas
MCP server ─────────► chat / knowledge / session
                                │
                     ┌──────────┼──────────┐
                     ▼          ▼          ▼
                  session   retrieval   knowledge
                     └──────────┬──────────┘
                                ▼
                              shared

chat / agents ─► observability
eval ─► public Agent entrypoint + explicit suite exceptions
```

硬性规则：

- `schemas/` 不能导入其他 `paper_copilot` 模块。
- `session/`、`retrieval/`、`knowledge/`、`shared/` 不能导入 `agents/`、`chat/`
  或 `api/`。
- `retrieval/` 与 `knowledge/` 不能互相导入；共享纯函数放入 `shared/`。
- `eval/` 可调用 `agents/` 的公开 run 入口；`eval/suite.py` 还可使用 `LLMClient`
  和 `ReadPaperTool`，但不能依赖其他 Agent 内部实现或 `retrieval/`。
- SwiftUI 和 MCP 不复制 Python Core 业务逻辑。

违反任一规则都是 code review blocker。

## Agent and Tool Architecture

Paper Copilot 根据用户请求选择工具、聚合证据并生成自然语言或 grounded Markdown。
循环以 `end_turn`、预算、deadline、用户中断或失败为终止条件。重复工具签名、
单工具超时和 rollout 超时由 Runtime 确定性处理。

模型只看到四个工具：

- `library_exec`
- `inspect_page`
- `paper_set`
- `library_edit`

运行时还会加载一个只读的内建 `research-papers` Skill，指导 Agent 组合工具完成缓存
检查、全文命令搜索、PDF 页定位和有界证据绑定。Skill 以应用生成的受信任上下文进入
首次运行、恢复和压缩后的 turn；名称、版本和正文 SHA-256 写入权威 trace。Skill 不
授予工具、路径、网络、安装或写入权限。

Runtime 在模型循环前按本轮论文预算批量准备内容寻址文本缓存，并通过受信任的
`research_cache_index` 提供授权 PDF locator、完整 SHA-256、页数和逻辑 `cache/`
文本路径。该索引在 attempt 内只读，并在恢复和 context compaction 后重新注入。模型
直接对这些逻辑路径执行批量搜索，不再逐篇调用 `paper-cache status/ensure`；未被预算
纳入索引的论文仍可使用兼容 broker 按需准备。

### `library_exec`

- 固定工作目录为 Runtime 创建的逻辑 workspace，其中 `library/` 和 `cache/` 只读，
  只有调用级 `scratch/` 可写。
- 用于列举、统计、哈希和读取等只读命令组合。
- 通过 macOS sandbox 限制网络、库外读取和论文库写入，并限制时间与输出。
- 不提供模型可选 shell、登录环境、远程环境或 sandbox 失败后的权限升级。
- `paper-cache status/ensure/page` 作为兼容和按需路径，由窄化 broker 调用内容寻址
  缓存服务，必须作为一次
  `library_exec` 的完整命令，不能进入循环、管道、命令链或替换，也不能指定输出路径。
- broker 接受逻辑 workspace 输出的 `library/<relative-pdf>` 或相对于授权 library 根的
  `<relative-pdf>`，并统一归一化为授权 locator。
- 命令结果是不可信、有界数据，不获得新的工具权限。

### `library_edit`

- 承担模型发起的论文库目录、PDF 和 Markdown 写操作。
- 路径必须解析在授权论文库内；不允许静默覆盖或永久删除。
- 删除进入 macOS 系统废纸篓；Markdown 写入使用完整文档和变更预览。
- 所有修改先经过工具策略；需要批准时进入持久 job 审批状态。

### `inspect_page`

- 只接受授权 PDF 的完整 SHA-256（首选）或兼容旧 session 的 12 位 `paper_id`、一个
  PDF 页码和可选归一化 region；不得截断完整 SHA-256 冒充旧 ID。
- 仅在模型声明支持图像输入时使用 Poppler 渲染有界 PNG。
- 结果绑定 PDF SHA-256、页码、region 和 render SHA-256；图像只进入当前模型上下文，
  不写入 session、日志或 trace。
- 不执行 OCR、批量页面处理、全文入库或纯文本模型回退。

### `paper_set`

- 通过 create、derive、record_evidence 和 status 保存不可变论文集合。
- 集合成员绑定 PDF SHA-256、授权 locator、ingest revision 和当前 cache revision。
- 只有每个成员都有可验证页级 evidence 且没有 stale 成员时 coverage 才能 complete。
- 状态以 append-only application event 写入 session，并沿 recovery source session 重放；
  不承担搜索、RAG、PDF 提取或回答生成。

旧的读取、搜索、查询、比较、文件、笔记和 Composer 实现作为不可调用的回滚代码继续
存在，但不属于模型工具表面；Runtime 拒绝模型调用未公开的旧名称。

## Authorization and Trust

用户输入、PDF 文本、文件名、检索片段、既有字段和工具输出均为不可信数据。只有 system
prompt、应用注入的 runtime context、Pydantic tool schema 和应用策略可以定义行为。

每次模型工具调用按以下顺序处理：

```text
model request
  → schema validation
  → capability and path policy
  → allow / deny / require approval
  → exact approval binding when required
  → tool execution
  → bounded untrusted output
  → authoritative runtime-state refresh
```

批准绑定 tool call、已校验参数摘要、目标快照和变更预览。执行前任一绑定条件发生变化，
批准即失效。拒绝不产生磁盘修改；中断、失败和恢复不会自动重放缺少结果的副作用工具。
高影响操作必须由用户显式确认，不能由自动审核代替。

## State and Recovery

三个状态真源相互独立：

- **session:** 模型历史、工具调用与恢复上下文的 append-only 真源。
- **job:** 调度状态、attempt、审批、最终结果和客户端事件的真源。
- **trace:** rollout 诊断真源，不决定 job 或 session 状态。

一个 job 可以有多个 attempt。客户端断线不终止后台任务；服务重启后遗留的
queued/running job 转为 interrupted。Resume 在同一 job 下创建新 attempt，并从最近
可恢复历史构造上下文；只有 completed conversation 轮次进入后续对话上下文。

每个 attempt 写入独立 observability bundle。Trace reducer 只从完整事件前缀构造可重建
状态，忽略 torn tail，并校验事件顺序、父子关系和 payload 引用。

## Storage

用户授权的论文目录保存原始 PDF 及用户创建的文档。应用数据默认位于：

```text
~/.paper-copilot/
├── papers/<paper_id>/session.jsonl
├── jobs/<job_id>/
│   ├── job.json
│   ├── events.jsonl
│   └── attempts/<n>/
│       ├── manifest.json
│       ├── trace.jsonl
│       ├── state.json
│       └── payloads/
├── fields.db
├── embeddings.db
├── embeddings_meta.json
├── embedding_cache.sqlite
├── graph/cross-paper-links.jsonl
└── eval/
```

`paper_id = SHA1(PDF bytes)[:12]`，移动或重命名 PDF 不改变 ID。Session 和事件只追加；
derived state 可以重建，不能反向覆盖源记录。模型凭据由 macOS 客户端保存在权限受限的
Application Support 文件中，通过 Runtime 环境变量传入，不进入论文库、session 或
trace。

Embedding 当前锁定 DashScope `text-embedding-v4`、1024 维；模型或维度变化时必须重建
索引，不允许多种 embedding 在同一索引中共存。具体约束见
[docs/design/dashscope_text_embedding.md](docs/design/dashscope_text_embedding.md)。

## Model and Context Policy

- 所有 LLM 调用经过 `agents/llm_client.py`。
- 一次任务使用客户端选择的同一模型，不做模型分层。
- 主 Agent 和回答修复调用不设置客户端 `max_tokens`，由模型/API 决定单次输出上限；
  压缩、审批审核和结构化抽取等专用调用可以按其有界契约显式设置。
- 支持 OpenAI-compatible endpoint；Paper Copilot 调用必须使用 provider 支持的
  Thinking 和流式输出，未知协议不能静默退化为非思考模式。
- 按固定 Codex 模型配置的 272K 原始窗口管理：258.4K 为有效工作窗口，预计下一轮达到
  244.8K 时压缩到不超过 80K，258.4K 为普通调用硬门槛。客户端工作窗口百分比采用
  Codex 口径：主 Agent 最近一次模型调用的输入、缓存和输出 token 均计入；绝对用量和
  有效窗口保持原值，仅在百分比计算时从分子和分母扣除 12K 固定基础预算。
- `CompactionSummary` 保留请求、目标、约束、决策、证据、失败尝试、runtime state
  和近期完整 tool round；原始 session 保持 append-only。
- 模型变更前运行 smoke eval，并同时比较质量、成本和延迟。零回归是必要条件，但必须
  有可测量收益才能改变默认模型。

## Main Flows

### Client job

```text
macOS client
  → local HTTP job API
  → chat.jobs creates attempt
  → chat.runtime
  → Paper Copilot bounded loop
  → session / report / derived cache or approved library updates
  → completed / failed / interrupted
```

客户端优先通过 SSE 接收事件，断线后使用同一事件游标增量轮询。App 重启只恢复显示，
不会自动重跑任务。

### Research and answer

```text
research-papers Skill
  → Runtime preflight prepares bounded cache index
  → library_exec searches prepared cache paths in batches
  → rg / awk bounded search and PDF page location
  → paper-cache page evidence
  → inspect_page when visual verification is necessary
  → paper_set coverage for explicit multi-paper scopes
  → grounded answer
```

缓存是可重建派生状态；`paper_set` 事件和模型历史持续追加到 session。失败不清除已经成功
写入的历史，也不把 partial 或 stale 集合报告为 complete。

### Library mutation

```text
library_exec discovers current state
  → library_edit proposes exact mutation
  → policy and impact classification
  → approval when required
  → precondition recheck
  → atomic write or move to Trash
  → job event and Agent result
```

## Non-goals

- 多 Agent 协商或分布式执行。
- 云端多租户、账号、支付、ACL、托管模型或云端论文库。
- 自动绕过付费墙或访问控制。
- 大规模索引、多 embedding 共存或图谱 entity resolution。
- PDF 图表的独立 CV 理解。
- 无评测依据的 Agent Core Swift/Rust 重写。
