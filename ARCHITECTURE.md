# ARCHITECTURE

> 当前架构与硬性边界。产品进度见 [TASKS.md](TASKS.md)，实现细节以代码为准。

## Principles

- **Single Agent:** 一个 Paper Copilot bounded tool loop；读论文能力是有界工具，不做
  multi-agent 编排。
- **Local first:** PDF、索引、session、报告和 trace 默认在本地；只有本地检索选出的
  必要片段可以发送给用户配置的云端模型。
- **One Core:** macOS 客户端和 MCP Server 复用同一 Python Core。
- **Personal scale:** 面向约 50–100 篇论文，不为多租户或分布式规模优化。

## Product Surfaces

```text
SwiftUI macOS Client ──► local HTTP job API ──┐
Local MCP Server ──────► MCP services ─────────┤
                                               ▼
                                       Python Paper Core
```

- `apps/macos/`：窗口、目录授权、Keychain、模型设置、任务/报告界面和 Runtime 生命周期。
- `api/`：macOS Runtime 的本地 HTTP 边界。
- `mcp/`：本地 `stdio` MCP 查询与长任务边界。

SwiftUI 和 MCP 只处理各自的协议与产品边界；论文处理、检索、job 状态和恢复均由 Core
负责。

## Modules

```text
apps/macos/

src/paper_copilot/
├── api/            # macOS Runtime HTTP transport
├── chat/           # chat runtime、持久 job 与 conversation
├── mcp/            # stdio MCP 服务
├── agents/         # Paper Copilot loop 与论文工具
├── schemas/        # Pydantic 输出契约
├── session/        # append-only session JSONL
├── retrieval/      # 单篇论文章节切分
├── knowledge/      # 跨论文索引与 hybrid retrieval
├── observability/  # job attempt rollout trace
├── eval/           # 回归、retrieval gate 与趋势报告
└── shared/         # logging、cost、cache、errors 等公共原语
```

### `api/`

基于 Python stdlib HTTP server，提供 health，以及 job 创建、列表、详情、增量事件、
SSE、interrupt、resume、approval 和 diagnostics。这里只做 JSON/HTTP 边界处理，
业务编排属于 `chat/`。

### `chat/`

接收自然语言请求，组装上下文并调用 Paper Copilot 的公开入口。`chat/jobs.py` 是
持久任务生命周期边界：

- 一个 job 保存原始请求、状态、attempt、最终结果和 append-only 事件。
- 客户端断线不影响后台执行；服务重启后遗留的 queued/running job 转为 interrupted。
- interrupt 取消真实 Agent task，Agent 退出后才写 interrupted 终态。
- resume 在同一 job 下创建 attempt，从最近可恢复历史重建上下文；缺失结果的 tool
  call 变为 `aborted`，不会自动重放外部操作。
- `conversation_id` 聚合顺序 job。只有 completed 轮次进入后续上下文。

上下文达到阈值时写入结构化 checkpoint；原始 job、session 和费用仍独立保留。

### `mcp/`

`paper-copilot-mcp` 使用官方 Python MCP SDK 和本地 `stdio` transport。

只读工具直接调用 `knowledge/` 和 evidence 接口，不进入 Agent loop：

- `library_status`
- `list_papers`
- `search_papers`
- `get_paper`
- `inspect_evidence`
- `compare_papers`

长任务工具调用既有 `chat.jobs`：

- `start_read_paper`
- `get_job_status`
- `get_job_result`
- `cancel_job`

MCP 工具没有任意路径参数，只访问 `PAPER_COPILOT_HOME` 和配置的论文目录。查询输出
限制论文数、字段数、evidence、事件和文本长度，不返回完整 PDF、session 或本机结果
路径。`start_read_paper` 只接受论文目录内已有 PDF 的 `paper_id`，立即返回 job ID。

语义搜索在有 embedding Key 时使用 vector + BM25 + RRF，否则退回本地 FTS5/BM25。
MCP Host 把结果交给云端模型时，返回的摘要、evidence 和报告会离开设备。

### `agents/`

系统只有一个自主循环：

- **Paper Copilot:** 根据请求选择工具、聚合证据并生成 Markdown；终止条件为
  `end_turn`、`max_turns` 或 `max_budget_cny`。

读论文链路由四个无自主循环的工具组成：

- `ReadPaperTool`：编排一次单篇论文读取。
- `SkimPaperTool`：提取元数据和章节结构。
- `ExtractPaperTool`：按章节提取贡献、方法、实验和局限。
- `LinkRelatedPapersTool`：从本地知识库生成跨论文关系。

PDF 文本、检索结果和既有字段均视为不可信输入；只有 system prompt、runtime context
和 tool schema 能定义行为。Runtime 在工具结果后刷新权威预算与计划状态。

主 loop 有重复工具签名熔断、单工具 deadline 和整个 rollout deadline。用户取消、
工具超时和 rollout 超时保持不同终态。

### `schemas/`

定义 `Paper`、`Contribution`、`Method`、`Experiment`、`Limitation` 和
`CrossPaperLink` 等 Pydantic 契约。所有跨模块 LLM 产出必须经过 schema 校验；失败
最多重试一次，仍失败则抛出 `SchemaValidationError`。

### `session/`

负责 append-only JSONL session tree 的读写，不感知 Agent 或 schema 语义。

- 首行是 session 元信息。
- 后续行为带 `id`、`parent_id` 和 `type` 的事件。
- compaction 只追加 replacement history，不覆盖原始记录。

### `retrieval/`

只负责单篇论文的章节切分，公开入口为 `split_by_sections`。它不维护持久向量索引。

### `knowledge/`

负责跨论文知识库：

1. 将结构化字段写入 `fields.db`。
2. 将 chunks 写入 `embeddings.db`。
3. 通过字段过滤、FTS5/BM25、vector、RRF、论文聚合和确定性 evidence 选择提供
   hybrid search。

Embedding 锁定 DashScope `text-embedding-v4`、1024 维。模型或维度变化时必须重建
索引；不允许多种 embedding 共存。具体接口边界见
[docs/design/dashscope_text_embedding.md](docs/design/dashscope_text_embedding.md)。

`shared/chunking.py` 是 `retrieval/` 与 `knowledge/` 的共享纯函数边界。当前不使用
cross-encoder 或 LLM reranker。

### `observability/`

每个 job attempt 写入独立 bundle：

- `trace.jsonl`：有序 lifecycle、父子关系、状态和耗时。
- `payloads/`：脱敏、有界的诊断 payload。
- `state.json`：由完整事件前缀严格归约得到的可重建缓存。
- `manifest.json`：job、attempt、session 和脱敏策略身份。

Session 是模型历史与恢复真源，job 是调度状态真源，trace 只用于诊断。Reducer 忽略
未换行的 torn tail，并校验序号、父实体、lifecycle 和 payload 引用。

默认 `local_safe_v1` 策略清除凭据并限制 payload 大小。旧 payload 不会被自动重写。
`scripts/observability_payloads.py` 默认只扫描；显式 `--apply` 才把符合条件的历史
payload 原子替换为保留身份和哈希的 tombstone。

### `eval/`

在隔离数据目录复用真实 `ReadPaperTool`，比较字段级 golden，并记录成本、延迟和趋势。
严格断言必须高于模型噪声下限；模型升级要求零回归和可测量的正向 ROI。

### `shared/`

存放无上层业务依赖的公共原语，包括结构化日志、成本跟踪、prompt cache、异常、
JSON Schema 处理和共享 chunking。

## Dependency Rules

```text
apps/macos ─► api ─► chat ─► agents ◄── schemas
MCP server ─────────► chat / knowledge
                               │
                    ┌──────────┼──────────┐
                    ▼          ▼          ▼
                 session   retrieval   knowledge
                    └──────────┬──────────┘
                               ▼
                             shared

chat / agents ─► observability
eval ─► public agent run entrypoint + allowed suite boundaries
```

硬性规则：

- `session/`、`retrieval/`、`knowledge/`、`shared/` 不能导入 `agents/`、`chat/`
  或 `api/`。
- `schemas/` 不能导入其他 `paper_copilot` 模块。
- `retrieval/` 与 `knowledge/` 不能互相导入。
- `eval/` 可调用 `agents/` 的公开 run 入口；`eval/suite.py` 还可使用 `LLMClient`
  和 `ReadPaperTool`，但不能依赖其他 Agent 内部实现或 `retrieval/`。

违反任一规则都是 code review blocker。

## Storage

```text
~/.paper-copilot/
├── papers/<paper_id>/
│   ├── source.pdf
│   ├── session.jsonl
│   └── chunks/
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

`paper_id = SHA1(PDF bytes)[:12]`，移动或重命名 PDF 不改变 ID。用户数据目录位于仓库
之外，不随应用升级迁移或覆盖。

## Model and Context Policy

- 所有 LLM 调用经过 `agents/llm_client.py`，使用客户端选择的同一模型，不做模型分层。
- 未显式配置时兼容默认值为 `qwen3.6-flash`。
- 支持 OpenAI-compatible endpoint；macOS 客户端把 API Key 保存到 Keychain，并通过
  Runtime 环境变量传入。
- Paper Copilot 的 LLM 调用必须开启 provider 支持的 Thinking 和流式输出；未知协议
  不能静默退化为非思考模式。
- 项目按 256K input token 工作窗口管理：预计下一轮达到 200K 时压缩到不超过 80K，
  240K 为普通调用硬门槛。
- `CompactionSummary` 保留请求、目标、约束、决策、证据、失败尝试、runtime state 和
  近期完整 tool round；原始 session 保持 append-only。
- 模型变更前运行 smoke eval，并比较质量、成本和延迟。历史单点价格不作为预算承诺。

## Main Flows

### Client Job

```text
macOS client
  → POST /jobs
  → chat.jobs creates attempt
  → chat.runtime
  → Paper Copilot bounded tool loop
  → session/report/index updates
  → completed, failed, or interrupted job
```

客户端用 SSE 接收事件，失败时改用同一 `seq` 游标增量轮询。重启后只恢复显示；任务
不会自动重跑。

### Read and Index a Paper

```text
Paper Copilot
  → ReadPaperTool
  → SkimPaperTool
  → ExtractPaperTool
  → LinkRelatedPapersTool
  → Paper schema validation
  → session append
  → knowledge index update
```

中间产物持续写入 session，失败不会清除既有记录。

### Search and Compare

```text
Paper Copilot or MCP
  → knowledge.hybrid_search
  → field filter + BM25/vector RRF
  → paper aggregation + evidence selection
  → deterministic comparison or grounded Markdown
```

对比工具只读取已落盘字段，不额外调用 LLM。

## Non-goals

- 多 Agent 协商或分布式执行。
- 云端多租户、账号、支付、ACL 或托管论文库。
- 自动绕过付费墙或访问控制。
- 大规模索引、多 embedding 共存或图谱 entity resolution。
- PDF 图表 CV 理解。
- 无评测依据的 Agent Core Swift/Rust 重写。
