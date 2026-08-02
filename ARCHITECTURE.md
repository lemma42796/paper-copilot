# ARCHITECTURE

> Paper Copilot 当前已实现的架构、所有权和硬边界。产品状态见
> [TASKS.md](TASKS.md)，工程规则见 [AGENTS.md](AGENTS.md)，详细决策见
> [docs/design/](docs/design/)；具体接口以代码为准。

更新于 2026-08-03。

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

当前模型按能力条件看到最多五个工具：

| 工具 | 当前职责与边界 |
|---|---|
| `load_skill` | 从可信 Skill catalog 按需加载固定版本研究指令；同一 conversation 同版本只首次返回正文 |
| `library_exec` | 在 conversation 级逻辑 workspace 中执行有界命令；`library/`、`cache/`、`papers/`、`research-manifests/` 只读，持久 `scratch/` 可写；长命令可 yield |
| `library_write_stdin` | 以不透明 session ID 写入或轮询已 yield 的 `library_exec` 进程；继承原命令 sandbox |
| `inspect_page` | 按授权 PDF SHA-256、页码和可选 region 渲染单页图像；不做 OCR、批量处理或文本回退 |
| `library_edit` | 授权论文库内的用户可见写操作；禁止静默覆盖和永久删除，需要时持久审批 |

### 5.1 研究上下文与缓存

World State 只发布内建只读 `research-papers` Skill 的 catalog metadata。模型按需调用
`load_skill`；session 固定首次加载的名称、版本、正文和 SHA-256，后续不重复返回正文。
Skill 只指导研究流程，不授予权限。

Runtime 在模型循环前按论文预算准备内容寻址文本缓存。conversation 环境通过只读的
`research-manifests/current.jsonl` 和短 `papers/*.layout.txt` 别名提供按需发现；manifest
保存授权 PDF locator、哈希、页数、缓存状态和应用内 `citation_base`。缓存文本以换页符
保留物理页定位，模型通过有界命令批量搜索和读取，模型可见输出进入会话历史。详细契约见
[library_exec_codex_source_mapping.md](docs/design/library_exec_codex_source_mapping.md)。

`*.layout.txt` 是从 PDF 派生的搜索、普通正文读取和物理页定位层，不是 PDF 原文或
通用的引用级（citation-grade）内容层。换页边界只保证定位关系，不保证公式字形、数学
符号、复杂表头、合并单元格、勾叉标记或二维布局的语义保真；这些内容可能变成 Unicode
替换字符（replacement character）、私用区字形（private-use glyph）或错误的阅读顺序。
原始 PDF 始终是权威来源。未经视觉或结构化证据复核，模型不得从乱码缓存精确转写公式，
也不得把符号列不完整的表格作为完整证据。

### 5.2 页面证据与引用展示

`inspect_page` 只在模型支持图像输入时渲染 PNG。结果绑定 PDF SHA-256、页码、region
和 render SHA-256；图像只进入当前模型上下文，不写入 session、日志或 trace。

纯文本（text-only）模型不能使用该视觉回退。当前 Runtime 没有确定性的公式 OCR、
PDF-to-LaTeX 或复杂表格结构恢复层，因此 text-only 运行遇到公式、符号表格或明显提取
损坏时只能明确报告证据限制，不能把 `layout.txt` 猜测性修复成看似合法的公式。结构化
Markdown/LaTeX 缓存、置信度与原页回退属于待设计能力，不是当前已实现架构。

成功 `inspect_page` 后，Runtime 只追加不含图像正文的页面观察事件。文本读取不另设
登记工具；权威命令、模型可见输出和完整会话历史构成审计依据。默认 Agent loop 不按
论文覆盖率或引用格式阻断模型 `end_turn`。

模型使用 manifest 的 `citation_base` 生成 Markdown 链接；Runtime 不改写最终答案。
Chat result 携带可信 citation ref 映射，macOS 在授权目录、扩展名和文件存在校验通过后
打开指定 PDF 页。完整设计见
[runtime_research_evidence_codex_source_mapping.md](docs/design/runtime_research_evidence_codex_source_mapping.md)。

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

一个 conversation 拥有一个长生命周期 session；job 只记录一个用户 turn 的调度和结果，
attempt 只记录该 turn 的一次执行。客户端断线不终止任务；服务重启后遗留的
queued/running job 转为 interrupted。Resume 在同一 job/turn 下创建新 attempt，继续
同一 session，不复制 conversation history。每个 attempt 在 session 中追加
`turn_started`，并以 `turn_completed` 或带 turn/job/attempt 标识的 `turn_aborted`
结束。后续新 turn 只使用已完成 turn；当前 job 的重试可使用该 turn 已持久化的部分历史。
同一 conversation 同时只运行一个 turn。

旧 session 通过 append-only 兼容路径迁移，不改写原记录。每个 attempt 有独立
observability bundle；Reducer 只消费完整事件前缀并校验顺序与引用。恢复和迁移细节见
[codex_paper_copilot_agent_gap_investigation.md](docs/design/codex_paper_copilot_agent_gap_investigation.md)。

用户授权目录保存原始 PDF 和用户文档。应用数据默认位于
`~/.paper-copilot/`：

```text
papers/<conversation_id>/session.jsonl
papers/<standalone_session_id>/session.jsonl
jobs/<job_id>/{job.json,events.jsonl,attempts/<n>/{manifest.json,trace.jsonl,state.json,payloads/}}
fields.db / embeddings.db / embeddings_meta.json / embedding_cache.sqlite
graph/cross-paper-links.jsonl / eval/
```

PDF 的 `paper_id = SHA1(PDF bytes)[:12]`，移动或重命名不改变 ID；它与 chat
conversation session ID 是不同命名空间。模型凭据由 macOS 客户端保存在权限受限的
Application Support 中，经 Runtime 环境变量传入，不进入论文库、session 或 trace。

客户端优先通过 SSE 接收 job 事件，断线后按同一游标增量轮询。App 重启只恢复显示，
不自动重跑任务。

Embedding 当前固定为 DashScope `text-embedding-v4`、1024 维；模型或维度变化必须
重建索引，不允许在同一索引混用。详见
[dashscope_text_embedding.md](docs/design/dashscope_text_embedding.md)。

## 8. 模型与上下文

- 所有 LLM 调用经过 `agents/llm_client.py`。
- `agents/context/` 按稳定 section 构建模型可见 World State。一个 context window 首次
  注入 `full`，后续 turn 和工具 batch 只在状态变化时追加 RFC 7386 merge patch；
  session 同步持久化 full/patch，恢复时从最后 full 顺序应用 patch 重建 baseline。
- 当前 section 包含论文授权摘要、模型、静态预算、模型可见工具、research Skill 和
  可选 Composer 状态；逐论文 inventory 不再进入 World State。费用、deadline、授权与
  工具策略仍由 Runtime 强制；World State 不是授权边界。
- Compaction 删除旧窗口中的 World State fragment，并在 replacement history 与 session
  中重新建立 full baseline。
- 一个 conversation 拥有一个持久 `LibraryEnvironment`：固定 logical cwd、只读
  `library/`/`cache/`/`papers/`/`research-manifests/`、跨命令 `scratch/` 和进程表。
  `library_exec` 在 yield 窗口后返回
  session/chunk ID；`library_write_stdin` 写入或轮询同一进程。用户中断和 conversation
  删除会终止环境内全部进程组；无 PTY、任意 workdir、shell 选择、网络或权限升级。
  受控 `python` 与 `python3` 指向同一解释器，只开放标准库读取和 `scratch/` 写入，
  关闭网络、user site、第三方 site-packages 和 bytecode 写入。
- 一次任务使用客户端选择的同一模型，不做模型分层。
- 主 Agent 和回答修复不设置客户端 `max_tokens`；有界专用调用可按契约设置。
- OpenAI-compatible endpoint 必须支持所选 Thinking 与流式协议，不能静默退化。
- 上下文预算、压缩阈值、UI 百分比和 `CompactionSummary` 遵循固定 Codex 语义；具体
  参数以代码和
  [context_window_codex_source_mapping.md](docs/design/context_window_codex_source_mapping.md)
  为准，原始 session 始终保持不变。
- 默认模型变更前必须运行 smoke eval；零回归只是必要条件，还需有质量、成本或延迟的
  可测量收益。

## 9. 非目标

- 多 Agent 协商或分布式执行。
- 云端多租户、账号、支付、ACL、托管模型或云端论文库。
- 自动绕过付费墙或访问控制。
- 大规模索引、多 embedding 共存或图谱 entity resolution。
- PDF 图表的独立 CV 理解。
- 无评测依据的 Agent Core Swift/Rust 重写。
