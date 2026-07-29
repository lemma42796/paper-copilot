# ARCHITECTURE

> Paper Copilot 当前已实现的架构、所有权和硬边界。产品状态见
> [TASKS.md](TASKS.md)，工程规则见 [AGENTS.md](AGENTS.md)，详细决策见
> [docs/design/](docs/design/)；具体接口以代码为准。

更新于 2026-07-28。

## 1. 原则

- **Single Agent：**只有一个 Paper Copilot bounded tool loop，不做多 Agent 编排。
- **Local first：**PDF、索引、session、报告和 trace 默认保存在本地；仅将完成本地
  选择后的必要上下文发送给用户配置的模型。
- **One Core：**macOS 客户端和 MCP 复用 Python Core，不复制论文处理、检索、job 或
  恢复逻辑。
- **Least privilege：**模型提出调用，Runtime 校验 schema、路径、授权和副作用；
  Prompt 与 Skill 都不是安全边界。
- **Append only：**session、job event 和 trace 保留原始历史；派生状态可重建，不反向
  改写源记录。
- **Personal use：**不建设多租户、分布式存储或托管论文库。

## 2. 产品表面

```text
SwiftUI macOS Client ──► local HTTP Runtime ──► chat/jobs ──┐
Local MCP Server ──────► bounded MCP services ──────────────┤
                                                            ▼
                                                    Python Paper Core
```

| 表面 | 所有权 |
|---|---|
| `apps/macos/` | UI、security-scoped 目录、凭据、模型设置、审批和 Runtime 生命周期 |
| `api/` | 本地 JSON/HTTP、SSE 和 diagnostics transport |
| `mcp/` | 本地 stdio 查询及长任务协议 |
| Python Core | Agent、PDF、检索、索引、job、session、恢复、eval 和 observability |

SwiftUI 与 MCP 是协议边界。MCP 工具不是内部 Agent 工具；长任务复用 `chat.jobs`。

## 3. 模块所有权

```text
src/paper_copilot/
├── api/            # macOS Runtime transport
├── chat/           # conversation、job、attempt、approval、interrupt、resume
├── mcp/            # stdio services
├── agents/         # bounded loop、LLM client、模型可见工具和 Skill
├── schemas/        # 跨 LLM、文件和模块边界的 Pydantic 契约
├── session/        # append-only model/session history
├── retrieval/      # 单篇论文章节切分
├── knowledge/      # 字段、chunks、embedding、图关系和跨论文检索
├── observability/  # attempt rollout trace
├── eval/           # 回归、检索 gate 和趋势评估
└── shared/         # 无上层依赖的错误、日志、成本、环境和纯函数
```

关键职责：

- `api/` 只翻译本地协议；`chat/` 负责业务编排和持久 job 生命周期。
- `agents/` 拥有唯一自主循环、模型工具、工具策略和论文读取编排。
- `session/` 不理解 Agent 或论文 schema；`observability/` 不决定业务状态。
- `retrieval/` 只负责单篇切分；`knowledge/` 负责持久跨论文知识。
- `eval/` 通过公开 Agent 入口评测，不成为产品运行依赖。

## 4. 依赖边界

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

- `schemas/` 不导入其他 `paper_copilot` 模块。
- `session/`、`retrieval/`、`knowledge/`、`shared/` 不导入 `agents/`、`chat/` 或
  `api/`。
- `retrieval/` 与 `knowledge/` 不互相导入；共享原语放入 `shared/`。
- `eval/` 可调用公开 Agent run 入口；`eval/suite.py` 可额外使用 `LLMClient` 和
  `ReadPaperTool`，但不依赖其他 Agent internals 或 `retrieval/`。
- SwiftUI 和 MCP 不复制 Python Core 业务逻辑。

违反这些规则是 code review blocker。

## 5. Agent 与工具

Agent loop 根据请求调用工具、聚合证据并生成自然语言或 grounded Markdown。终止条件为
模型 `end_turn`、预算、deadline、用户中断或失败；Runtime 处理重复签名、工具超时和
rollout deadline。

当前模型只看到五个工具：

| 工具 | 当前职责与边界 |
|---|---|
| `library_exec` | 在逻辑 workspace 中执行有界只读命令；`library/`、`cache/` 只读，调用级 `scratch/` 可写；无网络、无权限升级 |
| `read_page` | 从 Runtime preflight 冻结的 cache revision 读取一页文本，并产生页证据事实 |
| `inspect_page` | 按授权 PDF SHA-256、页码和可选 region 渲染单页图像；不做 OCR、批量处理或文本回退 |
| `update_research_scope` | 仅在用户明确要求后续持续排除论文时，追加保存有本轮页面证据的排除项；不能搜索、推断或取消排除 |
| `library_edit` | 授权论文库内的用户可见写操作；禁止静默覆盖和永久删除，需要时持久审批 |

### 5.1 研究上下文与缓存

内建只读 `research-papers` Skill 在首次运行、恢复和 compaction 后注入；名称、版本和
正文 SHA-256 进入 trace。Skill 只指导缓存搜索、页定位和证据工作流，不授予权限。

Runtime 在模型循环前按论文预算准备内容寻址文本缓存，并注入只读
`research_cache_index`：

- 授权 PDF locator；
- 完整 PDF SHA-256；
- 页数；
- 逻辑 `cache/.../layout.txt` 路径。

模型通过 `library_exec` 批量搜索逻辑路径；`paper-cache status/ensure/page` 不再暴露。
页文本只能通过 `read_page` 按完整 PDF SHA-256 和正整数页码读取。

### 5.2 页面证据与引用展示

`inspect_page` 只在模型支持图像输入时渲染 PNG。结果绑定 PDF SHA-256、页码、region
和 render SHA-256；图像只进入当前模型上下文，不写入 session、日志或 trace。

成功 `read_page` 或 `inspect_page` 后，Runtime 追加不含正文的
`research_evidence.page_observed` event，供审计、恢复和论文范围变更使用。它不作为
最终回答的默认发布门槛。Agent loop 与 Codex 一样只提供默认关闭的通用 Stop hook；
Paper Copilot 默认不配置 handler，因此模型 `end_turn` 后直接结束，不因论文覆盖率或
引用格式自动重答。

模型生成的完整 SHA-256/page 引用若能解析到当前论文，Runtime 会将其转换为标准
Markdown 链接，用户看到 `《论文题目》第 N 页`，点击后由 macOS 客户端在授权目录内
打开对应 PDF 页。无法解析的文本保持原样，不拦截回答。结构化 `evidence_refs` 保存
成功解析的引用，不包含宿主绝对路径。设计见
[runtime_research_evidence_codex_source_mapping.md](docs/design/runtime_research_evidence_codex_source_mapping.md)。

`update_research_scope` 仍只追加保存用户明确要求在后续讨论中持续排除的论文，并校验
完整 PDF SHA-256、本轮已观察页面和当前授权目录；后续 job 从同一 conversation 的
已完成 session 重建排除集合并注入 `research_scope`。它不判断排除结论在语义上是否
正确，也不管理普通的单轮筛选。

旧 `paper_set` 事件和代码仅供历史 session 兼容，不再属于模型工具表面或
citation-grade coverage。其他旧读取、搜索、查询、比较、文件、笔记和 Composer 实现
也仅作为不可调用回滚代码存在。

## 6. 授权与信任

用户输入、PDF、文件名、检索片段、已有字段和工具输出均为不可信数据。只有 system
prompt、Runtime context、Pydantic tool schema 和应用策略能够定义行为。

```text
model request
  → schema validation
  → capability and canonical path policy
  → allow / deny / require approval
  → exact approval binding
  → tool execution
  → bounded untrusted output
  → authoritative state refresh
```

- dispatch 前创建 lifecycle trace；schema/payload 失败记录 failed 终态。
- approval 绑定 tool call、已校验参数、目标快照和预览；执行前变化会使批准失效。
- 拒绝不修改磁盘；中断、失败和恢复不自动重放缺少结果的副作用工具。
- 高影响操作必须由用户明确确认，不能由自动审核替代。
- 模型自报工具调用不是权威 trace。

## 7. 状态、恢复与存储

| 真源 | 职责 |
|---|---|
| session | 模型历史、工具调用和恢复上下文 |
| job | 调度、attempt、审批、客户端事件和最终结果 |
| trace | rollout 诊断；不决定 job 或 session 状态 |

一个 job 可有多个 attempt。客户端断线不终止任务；服务重启后遗留的 queued/running job
转为 interrupted。Resume 在同一 job 下创建新 attempt，并从最近可恢复历史构造上下文；
只有 completed conversation 轮次进入后续对话。

每个 attempt 有独立 observability bundle。Reducer 只消费完整事件前缀，忽略 torn
tail，并校验事件顺序、父子关系和 payload 引用。

用户授权目录保存原始 PDF 和用户文档。应用数据默认位于
`~/.paper-copilot/`：

```text
papers/<paper_id>/session.jsonl
jobs/<job_id>/{job.json,events.jsonl,attempts/<n>/{manifest.json,trace.jsonl,state.json,payloads/}}
fields.db / embeddings.db / embeddings_meta.json / embedding_cache.sqlite
graph/cross-paper-links.jsonl / eval/
```

`paper_id = SHA1(PDF bytes)[:12]`，移动或重命名不改变 ID。模型凭据由 macOS 客户端保存
在权限受限的 Application Support 中，经 Runtime 环境变量传入，不进入论文库、
session 或 trace。

客户端优先通过 SSE 接收 job 事件，断线后按同一游标增量轮询。App 重启只恢复显示，
不自动重跑任务。

Embedding 当前固定为 DashScope `text-embedding-v4`、1024 维；模型或维度变化必须
重建索引，不允许在同一索引混用。详见
[dashscope_text_embedding.md](docs/design/dashscope_text_embedding.md)。

## 8. 模型与上下文

- 所有 LLM 调用经过 `agents/llm_client.py`。
- 一次任务使用客户端选择的同一模型，不做模型分层。
- 主 Agent 和回答修复不设置客户端 `max_tokens`；有界专用调用可按契约设置。
- OpenAI-compatible endpoint 必须支持所选 Thinking 与流式协议，不能静默退化。
- 原始窗口为 272K：258.4K 有效工作窗口；预计下一轮达到 244.8K 时压缩至不超过
  80K；258.4K 是普通调用硬门槛。
- UI 工作窗口百分比沿用 Codex 口径，主 Agent 最近调用的输入、缓存和输出 token 均
  计入；仅百分比计算从分子、分母扣除 12K 固定基础预算。
- `CompactionSummary` 保留请求、目标、约束、决策、证据、失败尝试、Runtime state
  和近期完整 tool round；原始 session 不变。
- 默认模型变更前必须运行 smoke eval；零回归只是必要条件，还需有质量、成本或延迟的
  可测量收益。

## 9. 非目标

- 多 Agent 协商或分布式执行。
- 云端多租户、账号、支付、ACL、托管模型或云端论文库。
- 自动绕过付费墙或访问控制。
- 大规模索引、多 embedding 共存或图谱 entity resolution。
- PDF 图表的独立 CV 理解。
- 无评测依据的 Agent Core Swift/Rust 重写。
