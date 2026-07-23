# TASKS

> 当前路线图与完成状态。历史实现过程见 Git，技术结构见
> [ARCHITECTURE.md](ARCHITECTURE.md)。

## Current Direction

更新于 2026-07-24。

Paper Copilot 是本地优先的个人论文研究工具，面向约 50–100 篇论文的知识库。产品有
两个入口，复用同一 Python Core：

- SwiftUI macOS 客户端：管理论文目录、模型配置、Agent 任务、报告和应用生命周期。
- Local MCP Server：向支持 MCP 的 Agent 客户端提供论文查询与长任务工具。

### Product Boundary

- PDF、索引、结构化字段、session、报告和 trace 默认保存在本地。
- 本地检索选出的文本片段可以发送给用户配置的云端模型；产品必须明确展示此边界。
- 当前采用 BYOK，不建设账号、支付、托管模型或云端论文库。
- SwiftUI 负责界面、目录授权、Keychain 和 Runtime 生命周期；Python 负责 Agent、
  PDF、RAG、存储、恢复、eval 和 observability。
- MCP 与 macOS 客户端必须复用 Python Core，不复制业务逻辑。

## Completed Milestones

### M20 — macOS Client Foundation

已完成 SwiftUI 原生客户端、security-scoped 论文目录、Keychain 模型配置、动态端口
Runtime、持久 conversation/job、SSE 与 polling、停止/恢复、Markdown 报告和任务诊断。
已通过真实论文任务、停止操作及 App 重启恢复验收。

### M21 — Local Read-only MCP

已完成本地 `stdio` MCP Server，提供：

- `library_status`
- `list_papers`
- `search_papers`
- `get_paper`
- `inspect_evidence`
- `compare_papers`

工具只访问配置的论文库和数据目录，输出有界，无任意路径、导入、删除、覆盖或命令执行
能力。已通过 Codex 中的真实工具发现与查询验收。

### M22 — MCP Long-running Jobs

已完成 `start_read_paper`、`get_job_status`、`get_job_result` 和 `cancel_job`。它们复用
既有 job/attempt/recovery 状态机，启动立即返回 job ID，状态查询使用增量事件游标。
已通过启动、查询、取消和 interrupted 终态验收。

### M23 — Distribution

已完成自包含的 Apple Silicon `.app` 和开发预览 DMG。App 内嵌 Python 3.12 Runtime
及 `sqlite-vec`，终端用户无需安装 Python、uv 或 Node.js。已通过签名检查、DMG
安装、Runtime 握手和真实论文任务验收。

Developer ID 与 Apple 公证留到正式公开发布阶段。

### M24 — Legacy Web Retirement

已删除 Next.js Web UI 和仅为旧界面服务的 API。当前仅保留 macOS 客户端、MCP 和
Python Core 共同需要的 health、job、events、SSE、interrupt、resume、approval 与
diagnostics 能力。

## Current Status

M20–M24 全部完成，当前没有进行中的里程碑。

## Deferred

以下方向只有经用户明确选择后才成为新里程碑：

- Developer ID、公证、正式公开发布和 App Store。
- 远程 MCP 与目录提交。
- 账号、套餐、托管模型、计费和多设备同步。
- 团队论文库与 Windows/Linux 客户端。
- Zotero 同步和本地模型推理。
- Swift/Rust 局部性能模块。
- 云端数据库、对象存储和 worker 集群。

## Stable Decisions

- Python 3.12+，所有函数和方法使用完整类型标注。
- 模块边界以 [ARCHITECTURE.md](ARCHITECTURE.md) 为准。
- 所有 LLM 调用经过 `agents/llm_client.py`。
- session 使用 append-only JSONL；热查询和索引使用 SQLite。
- LLM 结构化输出必须经过 Pydantic 校验；语义约束使用确定性 validator。
- 模型升级必须同时满足零回归和可测量的质量、成本、延迟收益。
- 本地 MCP 默认最小权限；写操作和外部副作用必须显式标注并审批。
- 未经用户确认不新增依赖、不改变发布技术栈。

## Working Discipline

1. 一次只推进一个 milestone 或 bounded slice。
2. 开始前查看现有接口；非平凡里程碑先给出计划并等待确认。
3. 新模块先稳定公开接口并完成一次手动运行，再考虑测试。
4. 未经明确要求，不主动新增或运行 Ruff、mypy、pytest 等验证。
5. DoD 满足后停止，列出完成项、缺失项和未修改的相邻问题。
6. 默认不 commit、不 push。
