# ARCHITECTURE

> 状态：当前架构。历史实测只保留仍会影响实现选择的结论；工作进度与未完成
> DoD 见 `TASKS.md`。

## 设计哲学

借鉴 Claude Code 的三条工程原则：

1. **Harness is everything, trust the model.** 脚手架做到位，不过度 prompt
   调优。模型会进步，脚手架该删就删。
2. **Radical simplicity.** 系统只有一个 `Paper Copilot`，主 loop 单线程，
   其余能力都是有界工具；不做 multi-agent 编排。
3. **Local-first, file-as-source-of-truth.** 所有状态以人类可读文件形式落盘
   （JSONL、markdown），用户可以 cat / grep / git diff。

## 目标规模

锚定 **50-100 篇论文的个人知识库**。所有技术选型都在这个规模下优化：
不做分布式、不做多租户、不做 > 500 篇规模的索引优化。

## 顶层模块

```
apps/
└── macos/        # SwiftUI 原生客户端

src/paper_copilot/
├── api/          # macOS Runtime 的 HTTP job 边界
├── chat/         # 单输入框运行时入口与历史记录
├── mcp/          # M21/M22 本地 stdio MCP 查询与长任务边界
├── agents/       # 单一 Paper Copilot loop + 工具实现
├── schemas/      # Pydantic 模型，结构化输出契约
├── session/      # JSONL session tree 读写
├── retrieval/    # 单论文内 chunk 检索（深挖用）
├── knowledge/    # 跨论文索引与检索（结构化字段 + 语义）
├── observability/ # job attempt 的本地 rollout trace
├── eval/         # 回归、retrieval gate 与趋势报告
└── shared/       # 通用工具：logging、cost tracker、cache helpers
```

## 模块职责

### `api/`
macOS Runtime 边界层。使用 Python stdlib HTTP server 暴露 health，以及持久 job 的
创建、查询、事件、SSE、恢复、中断、approval 和 diagnostics，不引入 FastAPI 等新
依赖。API 层只做 JSON 边界校验、header、错误响应和调用 `chat.jobs`；业务编排仍归
`chat/`。

### `mcp/`
M21/M22 的本地 MCP 边界。`paper-copilot-mcp` 使用官方 Python MCP SDK 和 `stdio`
transport。只读面提供 library status、论文列表、跨论文检索、结构化论文读取、
evidence 反查和确定性对比，直接调用 `knowledge/` 与既有 evidence 接口。长任务面
提供论文深读任务的启动、状态、结果和取消，直接调用 `chat.jobs`，不复制检索、论文
业务逻辑或任务状态机。

MCP Host 的模型负责理解请求和工具编排。普通只读工具不进入 `agents/` 的 Paper
Copilot loop，不创建 agent session，也不调用 `LLMClient`；只有显式调用
`start_read_paper` 才通过既有 job runtime 启动后台 Agent。FastMCP/Pydantic 负责协议
参数 schema 校验，`MCPReadService` 负责只读查询边界，`MCPJobService` 负责 MCP job
参数和返回边界。

MCP 工具没有任意路径参数，只访问 `PAPER_COPILOT_HOME` 和配置的论文目录。只读工具
使用 fields / embeddings SQLite read-only connection，不初始化或更新 schema。
`start_read_paper` 只接受配置目录内已有 PDF 的 `paper_id`，会花费现有 LLM budget
并写 job、attempt、session、report 和索引状态，但不能修改 PDF 论文库；它立即返回
job id，后续查询使用有界事件游标。取消先登记请求并取消真实 Agent task，只有 Agent
退出后 job 才进入 interrupted。所有 MCP 输出限制论文数、字段项数、evidence、事件和
文本长度，不返回完整 PDF、session 或本机结果路径。语义搜索在存在 embedding Key 时
沿用 vector + BM25 + RRF；否则使用同一本地索引的 FTS5/BM25 模式。MCP 客户端把工具
结果交给云端模型时，返回的本地论文摘要、evidence 和任务报告会离开设备，客户端安装
说明必须明确这一数据边界。

### `apps/macos/`
M20 的原生 SwiftUI 客户端。它负责窗口、侧栏、聊天输入、任务状态、任务诊断、
Markdown 报告、目录授权、Keychain 和 Python Runtime 生命周期；论文处理、job
状态机、恢复、检索和 LLM 调用仍由 Python Core 负责。客户端通过动态本地端口连接
现有 job API，不复制 Python 业务逻辑。

客户端为每个已有 attempt 的任务提供轻量诊断入口，使用独立原生 Sheet 按需调用
只读 diagnostics API，展示 Trace ID、耗时、首错、慢操作、未完成实体和重复工具
签名。它不直接读取 trace/payload 文件，不显示完整 prompt 或 PDF 正文，也不改变
`observability/` 的归约和脱敏边界。

### `chat/`
Chat-first 产品入口层。接收裸自然语言请求，组装 knowledge stores / agent
context，调用 `Paper Copilot` 的公开 run 入口，并返回客户端可直接消费的
`ChatRunResult`（report、session path、quality/report 路径、cost、paper budget）。
它不做关键词或规则路由；是否直接回答、是否调用工具及调用顺序均由 Paper
Copilot 在正常 tool loop 中决定。
HTTP job runtime 和客户端单输入框复用这一层。

`chat/jobs.py` 是长任务生命周期边界。一个 job 保存原始请求、状态、attempt 列表、
最终结果和 append-only 生命周期/工具进度事件。客户端断线不影响后台执行；服务启动
后首次加载 job registry 时，遗留的 queued/running job 会转为 interrupted。恢复会在
同一个 job 下创建新 attempt，并从前一 attempt 的 session rollout 重建模型 history。
重建从最近 `recovery_base` 或 compaction replacement history 开始，重放后续 assistant、
tool call 和 tool result；没有 result 的 call 规范化为 `aborted`，再追加新的继续 turn。
`runtime_state` 恢复论文预算、累计成本和完整 Composer plan。它不声称从上一次 LLM
token、网络流或未完成外部进程原地续跑。

显式停止使用 `POST /jobs/<id>/interrupt`。registry 先登记取消请求，再通过目标 job
事件循环的线程安全入口取消当前 asyncio task；Agent 实际退出后才把 attempt/job 标为
interrupted，并追加 `turn_aborted`。若工具调用已持久化但结果尚未产生，后续 rollout
重建会把它规范化为 `aborted`，不会由框架自动重放。

用户可见会话由 job 上持久化的 `conversation_id` 表示，不另建可漂移的消息副本。
一个 conversation 可以包含多个顺序 job；客户端按该 id 聚合消息，当前追问创建新 job，
中断恢复则仍在原 job 下创建 attempt。新 job 执行前收集同 conversation 中已经
completed 的旧 job：未达到自动压缩阈值时携带全部活动轮次，不做固定 token 滑动
截断；达到现有 200K 阈值后，把结构化摘要作为 conversation checkpoint 持久化到
completed job，后续用最近 checkpoint 加其所在轮及之后的完整轮次构造
`<conversation_context>`。
原始 job 问答继续完整保留，failed/interrupted 结果不会进入会话记忆。任务内工具
历史仍由 `run_agent_loop` 维护，并与跨轮历史共用同一自动压缩调用。

### `agents/`
项目的核心。系统只有一个 Agent：

- **Paper Copilot**：面向聊天请求的 bounded tool loop。三种终止信号：
  `end_turn` / `max_turns` / `max_budget_cny`。负责选择工具、聚合证据并生成报告。

读论文链路由四个有界工具组成，它们没有自主规划循环：

- **ReadPaperTool**：编排一次单篇论文读取，聚合其他三个工具的结构化结果。
- **SkimPaperTool**：读取论文前部和目录，产出元数据与章节结构。
- **ExtractPaperTool**：读取按章节切分的全文，产出 Contribution / Method /
  Experiment / Limitation 字段。
- **LinkRelatedPapersTool**：查询 knowledge 索引，从本地库候选中生成
  CrossPaperLink。

这些工具中的 forced `tool_use` 只是 LLM 结构化输出通道，不代表内部存在
第二个 Agent。工具只向调用者返回有 schema 约束的结果，不暴露完整调用历史。

三个 worker 的 LLM 边界都把 PDF 文本、PDF outline、已提取字段和检索候选记录
视为不可信来源。动态来源使用显式边界包裹；只有 worker system prompt 和 forced
tool schema 能定义任务与输出契约。来源文本不能改写角色、请求其他工具或变更输出
格式，应用生成的 schema validation 错误仍是可信的 retry 约束。

Paper Copilot 在首条 user message 注入 application-generated
`<runtime_context>`，并在每批 tool results 后追加最新权威快照。后发快照覆盖旧
状态，包含论文预算、已触达论文、LLM 成本预算，以及 Composer 已启动时的当前步骤、
允许工具、选中项和 final report contract。该刷新属于 harness 状态，不依赖模型从
历史 tool result 自行拼接约束。

主 loop 对连续工具调用保留一个轻量在线熔断器。签名由工具名和 canonical JSON 参数
组成；相同签名连续出现 3 次时，第 3 次不进入 dispatch，trace 记为
`tool_call.aborted`，job 以 `ToolLoopError` 失败。不同工具或参数立即重置计数，避免把
跨阶段合法复用误判成循环。恢复仍遵循 session rollout replay：没有 tool result 的被
拦截调用补 `aborted`，但框架不会自行重放。

每次工具 dispatch 另有 600 秒默认 deadline，只覆盖工具执行本身，不包含生产 LLM、
历史压缩或结果持久化。deadline 到达时抛出 `ToolTimeoutError`，tool span 以 failed 结束
并记录实际 duration 与 timeout 配置。外部用户取消仍保留 `CancelledError` 语义，不会
被转换成 timeout。该上限可在 `LoopConfig` 中设为 `None` 关闭。

持久 job attempt 还有 3600 秒默认 rollout deadline。job 父协程创建并监管独立 Agent
task，因此 HTTP interrupt 和 deadline 都作用于同一个 child，但终态不同：用户
停止是 interrupted/cancelled，deadline 是 `RolloutTimeoutError` 和 failed。deadline 到达
后先取消并等待 child 收敛，再写 rollout terminal event 和 job 状态，避免留下仍在后台
运行的 Agent task。旧 job spec 缺失该字段时使用默认值，显式 `None` 可关闭。

### `schemas/`
所有结构化输出的 Pydantic 模型：`Paper`、`Contribution`、`Method`、
`Experiment`、`Limitation`、`CrossPaperLink`。

约定：**任何跨模块传递的 LLM 产出必须经过 schema 校验**。schema 校验失败
自动 retry 一次，并把失败输入与错误位置写入 session；仍失败则抛出
`SchemaValidationError`，由顶层边界转换为用户可见错误。

### `session/`
JSONL session tree 的读写。一个 session = 一篇论文的完整分析过程。

文件布局：

```
~/.paper-copilot/
├── papers/
│   ├── <paper_id>/
│   │   ├── source.pdf              # 原始 PDF
│   │   ├── session.jsonl           # 主 session（树形）
│   │   └── chunks/                 # 分块文本（单篇 retrieval 用）
│   └── ...
├── jobs/
│   └── <job_id>/
│       ├── job.json                # 原子替换的任务状态与 attempt 列表
│       ├── events.jsonl            # append-only 用户可见生命周期与工具进度
│       └── attempts/<n>/
│           ├── manifest.json       # job / attempt / session / turn 关联
│           ├── trace.jsonl         # append-only runtime event spine
│           ├── state.json          # 由 trace 严格归约、可随时重建的状态缓存
│           └── payloads/*.json     # 脱敏、有界的 prompt/响应/工具诊断证据
├── embeddings.db                  # sqlite-vec + FTS5：跨论文 chunk 索引
├── fields.db                      # sqlite：结构化字段索引
├── embeddings_meta.json           # embedding 模型版本、维度和索引计数
├── embedding_cache.sqlite         # query / semantic eval 文本向量缓存
├── graph/
│   └── cross-paper-links.jsonl     # 跨论文关联（CrossPaperLink 落盘）
└── eval/
    ├── goldens/                    # 被标记为 ground truth 的 session
    └── runs/<timestamp>.jsonl      # eval 历史运行结果
```

Session JSONL 结构（借鉴 OpenClaw）：
- 第一行：`{type: "session", id, paper_id, cwd, timestamp, model}`
- 后续行：`{id, parent_id, type, ...}`，type ∈ {message, tool_result,
  compaction, branch_summary, schema_validation}
- Append-only，崩溃最多丢一行。

这个模块是**其他所有模块的底层存储 API**，它只关心"怎么存/读 JSONL"，
不关心 agent 或 schema 语义。

### `observability/`

本地、按 job attempt 写入的 rollout trace。`trace.jsonl` 只保存有序生命周期、
父子实体、状态和耗时；payload 先写入 `payloads/`，事件只保留引用。它与
`session.jsonl`、`job.json` 双写，保持恢复和客户端协议不变：session 仍是模型
历史与恢复真源，job 仍是调度状态真源，trace 只承担诊断。生产调用链覆盖 rollout、
turn、LLM、tool 和 compaction；`contextvars` 传播当前 recorder 和父实体，不把观测
参数穿透工具接口。

Reducer 对完整事件前缀执行严格归约：检查连续序号、manifest 身份、唯一 lifecycle、
父实体和 payload 引用，并把结果原子写为可重建的 `state.json`。只读接口
`GET /jobs/<id>/diagnostics?attempt=N` 默认分析最新 attempt，返回各阶段累计耗时、首个
错误、慢操作、未完成实体，以及按工具名和规范化输入哈希聚合的重复调用。最后一条未
换行的 event 视为并发 append 或崩溃留下的 torn tail，不参与当前归约。OTEL exporter
留到需要跨进程聚合或远端告警时再做。

Trace payload 默认使用 manifest 标记的 `local_safe_v1`：按键递归清除 authorization、
API key、token、cookie、password 和 secret，并处理文本中的常见 Bearer/Basic、`sk-`
和凭据赋值形式。单字符串保留最多 2000 字符预览，集合/层级有界；脱敏后的单 payload
超过 256 KiB 时只保存 16 KiB 预览、长度和 SHA-256。Trace 因而用于诊断而不是完整
模型历史；完整会话与恢复仍以 `session.jsonl` 为准。旧 manifest 缺少 policy 字段时按
默认字段保持 schema 可读，但不会把已经落盘的旧 payload 伪装成已脱敏或自动重写。

Payload 生命周期采用显式、可审计的 tombstone 策略，不删除 attempt bundle。运行
`uv run python scripts/observability_payloads.py` 只扫描并输出报告：manifest 未显式记录
policy 的历史 bundle 归为 `legacy_unclassified`，报告仅给出文件身份、哈希和汇总，不输出
原始内容。默认 30 天前且 rollout 已终止的 payload 进入 candidate；运行中 attempt 即使
过期也跳过。只有追加 `--apply` 才会在同一次扫描后原子改写 candidate，tombstone 保留
原值 SHA-256、原文件 SHA-256、原大小、policy 与清理时间，所以 trace 引用、严格 reducer
和重复工具签名仍然可用，正文与错误预览不再保留。改写前重新校验路径、manifest 身份和
扫描时的文件哈希，扫描后发生变化就拒绝执行。当前没有后台自动清理，也不删除整个
bundle；容量上限和整 bundle 删除仍需另行明确授权。

### `retrieval/`
仅负责单篇论文内部的章节切分。当前公开接口是 `split_by_sections`：
根据 `PaperSkeleton` 把 PDF 全文切成带页码范围的 `SectionText`，供
`ExtractPaperTool` 和读取后的跨论文索引同步使用。

这个模块不维护持久向量索引；跨论文 chunk、FTS5 和 sqlite-vec 全部属于
`knowledge/`。两者刻意分开，避免单篇解析逻辑与累积知识库的生命周期耦合。

### `knowledge/`
跨论文索引与检索。三个职责：

1. **字段索引维护**：每次 `read` 完成后，把 Paper 的结构化字段
   （Contribution/Method/Experiment/Limitation）写入 `fields.db`。
   支持 SQL-like 查询（"所有 Method 包含 'contrastive' 的论文"）。
2. **向量索引维护**：把每篇论文的 chunks 同步到 `embeddings.db`（除了
   单篇内部使用外，也作为跨论文语义检索的底层）。带 paper_id 分区，
   支持"在 N 篇候选中检索"的过滤。
3. **Hybrid 检索接口**：给 agents 和 chat runtime 用。输入是 query + 可选的字段过滤
   （如"只查 NLP 类论文"），输出是 top-k 论文 + 每篇的相关 chunk + 结构化
   字段摘要。内部流程：字段过滤 → FTS5/BM25 + vector 检索 → RRF →
   论文聚合 → 每篇 deterministic evidence chunk 选择。

**embedding 模型锁定** `text-embedding-v4`（DashScope OpenAI-compatible,
1024 维）。`embeddings_meta.json` 记录当前使用的模型 + 维度；换模型需要
重建索引后才能继续查询。百炼接口参数、价格和边界记录在
`docs/design/dashscope_text_embedding.md`。
**不支持多 embedding 共存**（存储翻倍、索引复杂，不值得）。

当前不做 cross-encoder 或 LLM reranker；只有 retrieval eval 出现稳定、可复现
且 deterministic selector 无法解决的 miss 时才重新评估。

`fields.db` 使用单表 JSON 和表达式索引；`embeddings.db` 同时维护 chunk
FTS5 与 sqlite-vec，`hybrid_search` 用 RRF 融合词法和向量排名，再按论文聚合并
选择非重复 evidence chunks。`shared/chunking.py` 是 `retrieval/` 与
`knowledge/` 共用的纯函数边界，两个模块仍不互相 import。模型名或维度与
`embeddings_meta.json` 不匹配时查询必须早失败并要求重建，不能混用旧向量。

### `eval/`
内部 eval 模块。Goldens 是仓库内的字段级快照，suite 在隔离数据目录中重跑
`ReadPaperTool`，通过 `assertions.py` 检查灾难性字段回归及成本、延迟预算。
`runs.py` 把每个 `(run_id, paper_id, field)` 写成扁平历史记录，
`report.py` 生成无 JavaScript 的静态趋势报告。

断言必须高于实际 LLM noise floor：稳定的 meta 字段可以严格比较；methods 和
contributions 只检查灾难性长度下降；experiments 检查 dataset/metric 对齐。
已知会在同 prompt、同模型下漂移的名称、布尔值和细粒度枚举不做单跑严格断言。
模型升级必须同时满足无回归与可测量的正向 ROI。

### `shared/`
- `logging.py`：统一结构化日志（JSON 格式，落盘 + 终端美化）
- `cost.py`：Cost tracker,按 session 累计 input/output/cached token。
  支持 Qwen 3.6 与 DeepSeek V4 tier 计费，`pricing_for_model(model)` 按 model id
  前缀路由
- `cache.py`：Prompt cache 辅助（layer 打标、边界插入）
- `errors.py`：统一异常基类
- `jsonschema.py`：JSON Schema 工具。当前提供 `inline_refs`，把 Pydantic
  生成的 `$defs` + `$ref` schema 展开成扁平形态后作为 LLM tool input_schema。
  这是兼容当前模型结构化 tool input 的集中边界；未来更换 provider 或模型后
  应重新验证是否仍需要。

## 模块依赖方向

```
apps/macos ──► api ──► chat ──► agents  ◄────────── schemas
MCP server ───────────► chat / knowledge
                                  │
                       ┌──────────┼──────────┐
                       ▼          ▼          ▼
                    session   retrieval   knowledge
                       │                     │
                       └──────────┬──────────┘
                                  ▼
                                shared

chat / agents ──► observability

eval ──► agents 的公开运行入口，以及 suite 明确使用的 LLMClient / ReadPaperTool
         session, schemas, knowledge, shared（不依赖 retrieval）
```

**硬性规则**：

- `session/`、`retrieval/`、`knowledge/`、`shared/` **不能**反向 import
  `agents/`、`chat/` 或 `api/`
- `schemas/` **不能** import 任何其他模块（它只定义数据结构）
- `retrieval/` 和 `knowledge/` 之间**不能**互相 import——它们是兄弟模块，
  共享的只有 `shared/` 里的 embedding util
- `eval/` 可以调用 `agents/` 的公开 run 入口；`eval/suite.py` 还可以直接使用
  `LLMClient` 和 `ReadPaperTool`，确保 smoke suite dogfood 真实读论文链路。
  除这两个明确边界外不进入 `agents/` 内部，也不依赖 `retrieval/`

违反以上任何一条都是代码 review 的 blocker。

## 模型分配

唯一的 Paper Copilot、所有 LLM-backed 工具，以及 query rewrite /
chunk rerank 等子任务统一使用用户在客户端选择的同一个模型，
**不做模型分层**。未经过客户端配置时，Runtime 仍以
**qwen3.6-flash** 为兼容默认值；具体 model id 在
`agents/llm_client.py` 里一处收敛。

- **默认端点**：`https://dashscope.aliyuncs.com/compatible-mode/v1`
  （阿里云百炼 OpenAI-compatible Chat Completions）；也可通过 `LLM_BASE_URL`、
  `LLM_API_KEY`、`LLM_MODEL` 切换到其他 OpenAI-compatible 端点。macOS
  客户端保存每条模型配置的端点、model id 和价格，API Key 单独存入 Keychain；
  选择模型时通过 Runtime 环境变量传入，API Key 不写入 job、日志或 session
- **Thinking 与流式输出**：Agent 系统的所有 LLM 调用必须开启模型 Thinking，
  当前明确支持 Qwen/DashScope 的 `enable_thinking` 和 DeepSeek 的
  `thinking.type=enabled` 协议；未知协议不能静默退化为非思考模式。主 Paper Copilot
  调用使用 Chat Completions SSE，把 `reasoning_content`、回答文本和工具生命周期
  转换为可持久化 activity events。内部 forced-tool 调用同样开启 Thinking，但不把
  结构化 JSON 生成过程展示为用户可见回答。客户端为每条模型配置保存思考设置；
  Qwen 3.6 继续使用 Chat Completions 的 `enable_thinking` 和
  `thinking_budget`，轻度/中/高/极高/最高是 Paper Copilot 定义的产品预设，
  分别限制为 4K/8K/16K/24K/32K 思考 token，不代表 Qwen 官方
  `reasoning.effort` 档位。DeepSeek 仅提供其原生支持的 `high`/`max`。
  推理 token 按输出价格计入同一预算。
- **上下文压缩策略**：模型真实窗口记为 1M tokens，项目工作窗口按 256K
  input tokens 管理；预计下一轮输入达到 200K 时自动压缩到不超过 80K，240K
  是禁止继续普通调用的紧急门槛。每轮同时记录真实输入 token 高水位。
  压缩摘要采用结构化 `CompactionSummary`，原始 session 保持 append-only；
  `compact_history()` 已能安全保留完整 tool-use/tool-result round、原始请求、最新
  runtime state 和近期原文，并把摘要和 token 计数写入 compaction entry。主 loop
  已启用自动调用和重复增量压缩。单次 200K input + 最多 8K output 预计约
  ¥0.30，校验失败最多重试一次，成功或失败的费用都进入同一个 `CostTracker`。
  2026-07-21 的真实模型受控评测把 223,704 estimated input tokens 压到 22,859，
  产出 872 output tokens，成本 ¥0.24626；目标、约束、决策、证据引用、失败尝试和
  下一步均通过确定性断言。
- **HTTP 客户端**：`httpx.AsyncClient`；`agents/llm_client.py` 负责把内部
  Anthropic 风格的历史 content blocks 转换成 OpenAI Chat Completions message、
  function tool calls 和统一 usage，业务 loop 不感知服务商差异
- **cost 参考**：单篇 `read` 的真实成本随论文长度、cache 命中和模型输出波动；
  以当前 trace 和 eval run 实测为准，不把历史单点数字当预算承诺
- **为什么不做分层**：当前 qwen3.6-flash 在 flash 档位价格已经足够便宜，
  分层带来的实现复杂度不值
- 历史 smoke 对比中 qwen3.6-plus 无可测质量上行，但成本 2.03x、延迟
  2.22x，因此继续使用 flash。`pricing_for_model()` 保留多 tier 计费，
  后续升级仍需重新测量质量、成本和延迟

`AGENTS.md` 的 "Cost discipline" 只保留操作规则（所有 LLM 调用必须走
`agents/llm_client.py` 等），不再重复默认——此节为单一真源。

## 关键数据流

### 用例 1：客户端提交和恢复长任务

```
apps/macos
  → api.http POST /jobs                               # 可携带 conversation_id
  → chat.jobs 后台创建 attempt
  → chat.runtime.handle_chat_request(message)
  → agents.run_paper_copilot(...)                     # bounded tool loop
      → 按需调用 search / inspect / compare / read 等工具
      → 通过 callback 追加 reasoning / assistant delta 和工具生命周期事件
      → 生成最终 Markdown 回答
  → chat 落 session / report / quality 记录
  → chat.jobs 原子写回 completed / failed 和最终结果
```

客户端从持久 job 列表恢复 conversation，重开应用或 API 重连后重新查询状态和增量
事件。运行期间使用 HTTP SSE；SSE 不可用时回退到增量轮询。两个事件通道共享 job
event `seq` 游标。
queued/running 只恢复显示，不自动
重新执行；interrupted/failed 也保持终态，
直到用户在原会话输入明确的恢复指令，客户端才调用 `POST /jobs/<id>/resume`。恢复入口
仍是普通输入框，不增加专用按钮。运行期间发送按钮切换为 ChatGPT 桌面端式的停止按钮，
调用 interrupt API；停止完成后输入框恢复正常发送状态。

已完成任务下继续输入普通问题时，客户端沿用当前 `conversation_id` 创建新 job。后端将
尚未压缩的全部前序 completed 问答，或最近 conversation checkpoint 加 checkpoint
所在轮及后续轮次的完整问答，放入 `<conversation_context>`，随后以当前问题作为新的
原始请求；因此每轮有独立 session、费用和恢复状态，但在产品层仍显示为同一个会话。

持久 job API：

```
POST /jobs
  → chat.jobs 持久化 queued job
  → 后台线程更新 running 并创建 attempt session
  → agent event callback 追加结构化 activity events
  → completed / failed 原子写回 job.json

GET /jobs/<id>                 # 断线后重新发现状态
GET /jobs/<id>/events?after=N  # 增量读取事件
GET /jobs/<id>/diagnostics     # 最新/指定 attempt 的本地 trace 诊断
GET /jobs/<id>/stream?after=N  # SSE 事件流
POST /jobs/<id>/interrupt      # 取消当前 asyncio Agent task
POST /jobs/<id>/resume         # replay rollout 后创建新 attempt/turn
```

### 用例 2：Paper Copilot 读取未索引 PDF

```
Paper Copilot tool loop
  → read_paper(pdf_path)
  → agents.read_pipeline.run_read_pipeline(pdf_path)
      → ReadPaperTool.run(pdf_path)                    # 有界读取流程
      → session.create_session(paper_id)               # 创建 JSONL 文件
      → SkimPaperTool.run(pdf_path)                    # 元数据与章节结构
          ← 返回 Paper.skeleton                        # 章节结构
      → ExtractPaperTool.run(pdf_path, skeleton)       # 按章节读取全文
          ← 返回 Contribution/Method/...               # schema 校验
      → aggregate into Paper (初步版本)
      → LinkRelatedPapersTool.run(paper_draft)
          ← 用 knowledge.hybrid_search 找库里相关 3 篇
          ← 返回 CrossPaperLink[]
      → merge into Paper (最终版本)
      → schemas.Paper.model_validate(result)           # 终检
      → session.append_final(paper)                    # 落盘
      → knowledge.index_paper(paper)                   # 更新跨论文索引
  ← 返回结构化读取结果给 Paper Copilot
```

每一步的中间产物都写入 `session.jsonl`，不因为失败丢失。

### 用例 3：自然语言检索与对比

```
POST /jobs
  → Paper Copilot 根据用户请求选择工具
  → knowledge.hybrid_search(query, filters)
      → 字段预过滤 + FTS5/BM25 + vector RRF
      → 按论文聚合相关 evidence chunks
  → query_paper / compare_papers
  → Paper Copilot 生成带证据引用的 Markdown 回答
```

对比工具本身不跑 LLM，只基于已落盘的结构化字段；LLM 只负责决定是否调用
以及组织最终自然语言回答。

### 用例 4：内部 eval suite

```
tests / internal caller
  → eval.run_suite(suite)
      → for each test case:
          → load golden from session.load_golden(paper_id, field)
          → call ReadPaperTool (same as use case 2)       # 产出新结果
          → eval.assertions.compare(actual, golden)
          → record to runs/<timestamp>.jsonl
      → eval.report.generate_html()
```

注意 eval 路径**完全复用**主功能的读取工具链，不另开一套——这是
"eval 必须 dogfood 主功能"的设计。

## 当前架构取舍

- 主 Agent 使用单线程 bounded tool loop，不引入多 Agent 编排框架。
- 读论文拆成有界工具，主要用于上下文隔离、结构化契约和独立成本追踪。
- Session 与恢复历史使用 append-only JSONL；热查询和索引使用 SQLite。
- `retrieval/` 负责单篇论文章节边界，`knowledge/` 负责跨论文持久索引；
  两者共享 `shared/` 原语但不互相 import。
- Embedding 索引只允许一种模型和维度；切换后整体重建，不支持混合向量。
- 对比工具基于已落盘结构化字段，不额外调用 LLM。
- Eval 以确定性断言和跨运行趋势为主，不把 LLM-as-judge 作为主要机制。

## 非目标

- 多 Agent 协商或分布式执行
- 云端多租户、账号、支付、ACL 或托管论文库
- 自动绕过付费墙或访问控制
- 超过个人论文库规模的索引优化
- 图谱遍历、引用链 entity resolution 或 PDF 图表 CV 理解
- 多 embedding 模型共存
- 在 M20 内重写 Agent、RAG 或 schemas
