# TASKS

> 状态：活文档。这里只保留当前产品方向、正在推进的里程碑、完成标准和仍然有效的
> 工程决策。历史实现过程由 Git 历史保存，详细结构见 `ARCHITECTURE.md`。

## Current Direction

更新于 2026-07-23。

Paper Copilot 重构为两个开源、本地优先的产品入口：

1. **macOS 客户端**：使用 SwiftUI 构建原生界面，管理本地论文库、Agent 任务、
   报告、设置和应用生命周期。
2. **MCP Server**：向 ChatGPT/Codex、Claude、VS Code、Cursor、Gemini CLI 等
   支持 MCP 的 Agent 客户端提供本地论文工具。

二者复用现有 Python Core，不维护两套论文处理逻辑：

```text
                       ┌── macOS SwiftUI Client
Python Paper Core ─────┤
                       └── Local MCP Server
```

### Product Boundary

- PDF、提取文本、RAG 索引、结构化字段、session、报告和 trace 默认保存在用户设备。
- 本地检索选择出的必要文本片段可以发送给用户配置的云端模型；产品必须明确展示这一
  数据边界，不能把“PDF 未上传”描述成“任何论文内容都不离开设备”。
- 第一阶段采用 BYOK，继续支持现有 DashScope / DeepSeek 配置，不建设账号、支付、
  托管模型或云端论文库。
- SwiftUI 负责 macOS 界面、窗口、菜单、目录授权、Keychain 和进程生命周期。
- Python 继续负责 Agent、PDF 解析、RAG、SQLite/sqlite-vec、LLM 调用、session、
  recovery、eval 和 observability。
- 当前不把 Agent Core 重写为 Swift 或 Rust。只有性能数据证明某个本地 CPU 步骤是
  明确瓶颈时，才讨论局部迁移。
- MCP 第一版使用本地 `stdio` transport；远程 Streamable HTTP MCP 延后。
- macOS 客户端可以继续调用本地 job API；MCP 和客户端必须调用同一组 Python 业务
  能力，不能复制实现。

## Existing Baseline

重构必须保留以下已经工作的能力：

- 单一 Paper Copilot Agent 和有界论文读取工具。
- 本地 PDF 解析、结构化提取和 Markdown 报告。
- `fields.db`、FTS5/BM25、sqlite-vec、RRF 和 evidence chunk 检索。
- append-only `session.jsonl`、持久 job/attempt、interrupt/resume 和 rollout replay。
- 多轮 conversation、上下文压缩、费用与论文预算。
- Research Idea Composer、deterministic plan 和 proposal checker。
- rollout trace、payload 脱敏、reducer 和 diagnostics。
- WebSocket → SSE → polling 的现有本地 job 事件协议，直到原生客户端不再需要它。

现有 Next.js Web UI 是迁移期实现。SwiftUI 达到功能对等且经过人工确认前，不删除
`apps/web/`，也不删除现有本地 HTTP API。

## Completed Milestone: M20 macOS Client Foundation

目标：建立可运行的 SwiftUI macOS 客户端骨架，并复用现有 Python Runtime 完成一条
真实本地任务链路。

### Scope

- 新增 `apps/macos/` SwiftUI macOS App。
- 原生实现窗口、侧栏、聊天输入、任务状态、停止操作、报告显示和设置入口。
- App 启动时启动一个长驻 Python Runtime，退出时正常关闭。
- Runtime 使用动态本地端口或等价的无冲突握手，前端不能硬编码开发者机器路径。
- 使用 `NSOpenPanel` 选择论文目录，并保存 security-scoped bookmark。
- API Key 保存到 macOS Keychain，不写入普通配置文件、日志或 session。
- 继续使用现有本地数据目录和数据库格式，不迁移用户数据。

### Definition of Done

- 从 Xcode 启动后出现 SwiftUI 原生窗口。
- 用户可以选择并重新打开一个本地论文目录。
- 客户端自动启动并连接 Python Runtime。
- 用户能提交一个请求、查看任务进度、停止任务并查看最终 Markdown 报告。
- App 重启后仍能看到既有 job、conversation 和报告。
- PDF、索引和 session 保持本地，没有新增论文上传接口。
- 完成一次真实手动运行后停止，总结仍缺少的客户端能力；不自动进入 M21。

### Progress (2026-07-23)

- 已实现 Python Runtime CLI、动态本地端口 ready 握手和正常关闭。
- 已建立 SwiftUI 原生窗口、conversation 侧栏、聊天区、任务事件、停止操作、
  Markdown 报告和设置入口。
- 已实现论文目录 security-scoped bookmark 恢复，以及按模型独立保存到 Keychain
  的 API Key。
- 已实现通用模型配置列表：添加、编辑、启用、删除、OpenAI-compatible 端点、
  Model ID 和自定义价格；聊天区只显示配置完整的已启用模型。
- 已接入现有 job API、SSE 事件流及 polling fallback；沿用现有本地 job、
  session 和索引目录。
- 已将 Agent 的 Qwen/DeepSeek 模型调用强制切换到 Thinking + SSE；推理内容、
  回答增量和工具开始/完成/失败状态写入可恢复的结构化 activity events。
- 已实现 Codex 风格活动时间线：实时思考、增量回答、工具卡片及中断/失败终态。
- 已为每条 Qwen/DeepSeek 模型配置增加持久化思考设置，并在聊天区提供 Codex
  风格菜单；Qwen 显示产品预设及对应思考 Token 上限，DeepSeek 显示其原生
  推理强度，切换后自动重启本地 Runtime。
- 已把聊天输入区收敛为单张紧凑圆角卡片，只保留多行输入、模型/思考设置和
  发送/停止按钮；论文目录继续通过工具栏或设置页选择。
- 最新 Thinking、activity timeline、模型思考设置和输入区改动已在 Xcode
  成功构建并启动，用户已通过实际 App 截图完成界面检查；模型 API Key 已配置。
- 已完成人工验收：真实论文任务正常完成并显示 Markdown 报告，运行中任务可停止
  并持久化为中断状态；App 重启后论文目录、job、conversation、报告和中断状态
  均正常恢复。
- M20 已完成。按里程碑边界在此停止，不自动进入 M21。

### Follow-up (2026-07-23)

- macOS 客户端新增原生任务诊断 Sheet，按需读取既有只读 diagnostics API。
- 用户可切换 job attempt，并查看 Trace ID、阶段耗时、首个错误、慢操作、未完成实体
  和重复工具调用签名；诊断内容保留实体 ID，便于关联本地 trace 溯源。
- 诊断入口保持在任务时间线内，详细内容使用独立 Sheet，避免把开发者信息混入主要
  对话和报告阅读流程。
- 本次只补充客户端诊断展示，没有修改 trace/payload 格式、保留策略或 Python
  observability 实现，也没有开始 M21。

### Not in M20

- 不删除 Next.js Web UI。
- 不重写 Agent、RAG 或 schemas。
- 不制作 App Store 版本。
- 不做 Developer ID 签名、公证、DMG 或自动更新。
- 不做登录、订阅、支付、云同步和远程任务。
- 不引入 Rust。

## M21 Local Read-only MCP

只有 M20 完成且用户明确要求继续后才开始。

目标：提供开源、本地、默认只读的 `stdio` MCP Server。

第一版工具：

- `library_status`
- `list_papers`
- `search_papers`
- `get_paper`
- `inspect_evidence`
- `compare_papers`

完成标准：

- MCP Server 调用现有 Python Core，不复制检索或论文业务逻辑。
- 只允许访问用户配置的论文目录和 Paper Copilot 数据目录。
- 工具返回有长度和数量上限，不把完整 PDF 或完整 session 放入模型上下文。
- 至少在一个主流 MCP 客户端完成手动安装、工具发现和真实查询。
- 没有导入、删除、覆盖或任意命令执行工具。
- 完成后停止，不自动进入 M22。

## M22 MCP Long-running Jobs

只有 M21 完成且用户明确要求继续后才开始。

目标：让 MCP 客户端可靠地启动、观察和取消长时间论文处理任务。

计划工具：

- `start_read_paper`
- `get_job_status`
- `get_job_result`
- `cancel_job`

这些工具必须复用现有 job/attempt/recovery 语义。不得让单次 MCP tool call 阻塞数分钟，
也不得额外实现一套任务状态机。

## M23 Distribution

只有客户端核心流程稳定后才开始：

- 将 Python Runtime 打包为用户无需安装 Python、uv 或 Node.js 的应用内 helper。
- 生成开发用 `.app`，随后再决定 Developer ID、Notarization 和 DMG。
- 正式公开发布前再加入 Apple Developer Program；开发阶段不提前支付会员费。
- Mac App Store 和 App Sandbox 适配另行决策，不作为首个公开版本的前置条件。

## M24 Legacy Web Retirement

只有 SwiftUI 客户端达到功能对等并获得用户明确确认后才开始：

- 删除不再使用的 Next.js 界面。
- 收窄仅为旧 Web UI 服务的 HTTP API。
- 保留 macOS 客户端、MCP 和 Python Core 共同需要的 job、history、report 和
  diagnostics 能力。

## Deferred

- 公共远程 MCP 和 ChatGPT Plugins Directory 提交。
- 账号、套餐、托管模型网关和用量计费。
- 加密多设备同步和团队共享论文库。
- Windows/Linux 客户端。
- App Store、StoreKit 和 Mac App Sandbox 版本。
- Zotero 自动同步。
- 本地模型推理。
- Swift/Rust 局部性能模块。
- 云端 Redis、PostgreSQL、对象存储和 worker 集群。

以上项目只有用户明确选择后才能成为新里程碑。

## Stable Engineering Decisions

- Python 3.12+，所有函数和方法使用完整类型标注。
- schemas 保持模块独立；现有模块边界继续遵守 `ARCHITECTURE.md`。
- LLM 调用统一经过 `agents/llm_client.py`。
- session 使用 append-only JSONL；热查询和个人知识库索引使用 SQLite。
- 结构化 LLM 输出必须经过 Pydantic 校验；语义约束使用 deterministic validator，
  不依赖 prompt 自觉遵守。
- 高噪声 LLM 字段不做低于实际 noise floor 的单跑严格断言。
- 模型升级必须同时满足无回归和可测量的正向 ROI。
- 新 LLM call site 必须先说明预期 token、成本和 eval 覆盖。
- 本地 MCP 默认最小权限；写操作、外部副作用和危险操作以后必须显式标注并审批。
- 不新增依赖、不改变发布技术栈，除非用户先确认。

## Working Discipline

1. 一次只推进一个 milestone 或 bounded slice。
2. 开始前查看相关现有接口，不猜测或平行重写。
3. 非平凡里程碑先给出计划并等待确认。
4. 新模块先稳定公开接口并完成一次手动运行，再考虑测试。
5. 除非用户在当前任务中明确要求，否则不主动增加或运行 Ruff、mypy、pytest 等验证。
6. DoD 满足后停止，列出已完成项、缺失项和未修改的相邻问题。
7. 默认不 commit、不 push；只有用户明确要求时执行。
