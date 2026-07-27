# TASKS

> Paper Copilot 的当前路线图与完成状态。工程规则见
> [AGENTS.md](AGENTS.md)，技术结构和稳定架构决策见
> [ARCHITECTURE.md](ARCHITECTURE.md)，历史实现过程见 Git。

更新于 2026-07-27。

## Current Direction

Paper Copilot 是本地优先的个人论文研究工具。产品通过 SwiftUI macOS 客户端和 Local
MCP Server 两个入口复用同一 Python Core。

当前采用 BYOK。PDF、索引、结构化字段、session、报告和 trace 默认保存在本地；只有
本地检索选出的必要文本可以发送给用户配置的云端模型。当前不建设账号、支付、托管模型
或云端论文库。

## Current Work

当前已完成 Codex 四轮基线、工具系统 v2 实施计划、Slice 1、Slice 2 和 Slice 3。
Slice 4 尚未开始，需要单独确认后实施。计划见
`docs/design/tool_system_v2_plan.md`。

已完成：

- 冻结 14 篇硕士学位论文、四轮 query 和私有 Gold；
- 完成原生 Codex 四轮盲测和基线评测；
- 基线未发现作者—方法错配，主要失败类型为 `constraint_memory_failure`；
- 确认当前 `read_paper` 的单次全文结构化抽取不作为 v2 入库核心；
- 规划 Poppler 候选底座、异常页本地恢复、能力自适应 `inspect_page`、稳定结果集合和
  Codex-inspired 安全边界。

v2 Slice 1 已完成：已加入 Poppler adapter、内容寻址 TXT revision、manifest、
cache hit/integrity 校验、原子 current 发布、进程内并发去重和页级文本读取接口。冻结
的 14 篇、1169 页论文首次缓存全部生成，耗时 4.211 秒；新缓存实例二次检查 14/14
命中，耗时 83 毫秒；三个同 key 并发请求只生成一个 revision。尚未接入公开工具或
Runtime 打包，也没有添加 Poppler/OCR 依赖。Poppler 打包评估见
`docs/design/poppler_packaging_assessment.md`。当前已选择不随 `.app` 分发 Poppler；
未来论文研究 Skill 检测到缺失时，先征得用户明确同意，再执行
`brew install poppler`。现有 PyMuPDF 同样采用 AGPL/商业双许可证，当前 MIT `.app` 的
既有分发边界仍需单独解决。

v2 Slice 2 已完成：`library_exec` 采用固定 Codex commit
`61a44880a85d2fd0d8770908dea5733495e571c8` 的 command resolution、sandbox attempt
和受控输出结构。源码映射见
`docs/design/library_exec_codex_source_mapping.md`。当前已按映射回改：使用 `cmd`/
`max_output_tokens` schema、固定逻辑 workspace、声明式 filesystem/network policy、
macOS Seatbelt renderer、Codex 非交互环境、聚合 head-tail buffer、token 截断、
Codex-style 输出、内部权威 trace attributes，以及 command resolution 后的
`paper-cache status/ensure/page` 拦截。用户已确认固定授权根、无 PTY/持续 session、
无权限升级、硬 timeout 和额外 CPU/file-size limit。Runtime 手工验收已通过普通命令、
三项受控外部命令、权限拒绝、无网络、资源限制、输出截断、broker 和权威 trace。
`.app` 按同一 Codex commit 的 package builder 固定 ripgrep 15.2.0 官方发布包，通过
manifest 记录 archive size 和 SHA-256，下载缓存命中前必须重新校验，只提取指定
Apple Silicon `rg` 和许可证。该二进制自包含 PCRE2，不再复制 Homebrew ripgrep、
PCRE2 dylib 或重写 install name。`.app` 验收已通过签名、固定 artifact 校验、PCRE2
搜索、Runtime 握手、真实 `library_exec rg`、broker 和权威 trace；trace 中三项外部
命令均可用。Poppler 仍只解析用户安装后的固定 Homebrew 位置，不开放完整 Homebrew
PATH。尚未开始其他三个 v2 工具。

v2 Slice 3 已完成：加入可审查的内建 `research-papers` Skill，覆盖缓存检查、确定性
全文提取、`rg`/`awk` 搜索、PDF 页定位、`paper-cache page` 有界证据以及
`incomplete`/`unresolved` 表述。Skill 在首次运行、恢复和 context compaction 后重新
注入，版本和正文 SHA-256 进入权威 trace 与 final payload，并随 `.app` Runtime
打包。源码映射见 `docs/design/research_skill_codex_source_mapping.md`。当前没有新增
宿主软件安装能力；Poppler 缺失时 Skill 先请求明确同意，宿主能力不可用时明确停止，
不会借 `library_exec` 绕过无网络和无权限升级边界。Slice 4 需要单独确认后开始。

## Recently Completed

### M20 — macOS Client Foundation

完成 SwiftUI 原生客户端、security-scoped 论文目录、本地模型配置、Runtime 生命周期、
持久 conversation/job、流式事件、停止与恢复、Markdown 报告和任务诊断。已通过真实
论文任务、停止操作及 App 重启恢复验收。

### M21 — Local Read-only MCP

完成本地 `stdio` MCP Server 的有界论文库查询、证据检查与论文比较能力。工具只访问
配置的论文库和数据目录，不接受任意路径，也不提供导入、删除、覆盖或命令执行能力。
已在 Codex 中通过真实工具发现与查询验收。

### M22 — MCP Long-running Jobs

完成通过 MCP 启动、查询、获取和取消长任务，并复用既有 job/attempt/recovery 状态机。
已通过启动、增量状态查询、取消和 interrupted 终态验收。

### M23 — Distribution

完成自包含的 Apple Silicon `.app` 和开发预览 DMG。App 内嵌 Python 3.12 Runtime 与
`sqlite-vec`，终端用户无需安装 Python、uv 或 Node.js。已通过签名检查、DMG 安装、
Runtime 握手和真实论文任务验收。

Developer ID、Apple 公证和正式公开发布仍在 `Deferred`。

### M24 — Legacy Web Retirement

删除 Next.js Web UI 和仅为旧界面服务的 API。保留 macOS 客户端、MCP 和 Python Core
共同需要的本地 Runtime 边界。

### Post-M24 bounded slices

- 完成需要批准的工具操作在 macOS 客户端中的展示、批准、拒绝、中断与恢复闭环。
- 为模型加入有界的论文库只读命令和编辑能力，并收敛公开工具表面。
- 加入面向多篇超长论文的分层读取、召回和游标遍历能力。
- 旧的专用查询与编辑实现暂时保留为内部能力；是否迁移或删除需要后续评估。

## Requirements To Plan

第 1 项已进入实验评估，但尚未成为代码实现 bounded slice。其余需求仍未成为 active
milestone。开始实现前需要先确定目标、范围、验收方式和明确不做的内容。

### 1. 完成工具系统评估（进行中）

- 以当前 command-first 工具表面为基线，盘点职责、粒度、输入输出、权限、副作用和
  组合方式。
- 排查能力缺口、职责重叠、隐式耦合、安全策略不一致及难以评估的接口。
- 评估仍保留的旧内部工具应继续复用、迁移还是删除。
- 已完成四轮多论文 Codex 基线，并将稳定结果集合纳入 v2 Slice 5。
- v2 按 `docs/design/tool_system_v2_plan.md` 的 bounded slices 实施；每个 slice 单独确认、
  验收后再进入下一项。

### 2. 重新设计 Research Idea Composer

- 重新定义用户目标、工作流、证据要求、产出契约和失败模式。
- 对比单 Agent、确定性编排和多 Agent 方案的质量、成本、延迟、可恢复性与可评估性。
- 先完成设计和实验，再决定是否引入多 Agent；不为架构形式增加 Agent。

### 3. 完成 Agent 系统评估

- 盘点现有 eval suite、golden、retrieval gate、质量启发式和趋势报告的覆盖范围。
- 检查指标是否对应真实用户任务、证据质量、工具选择、安全性、成本和延迟。
- 识别不稳定、可被投机优化或缺少判别力的指标，并提出校准、替换或新增方案。

### 4. 支持用户与第三方 Skill

- 在工具系统 v2 完成并冻结后再规划，不并入当前 Slice 4–6。
- 第一阶段只支持 instruction-only Skill，提供专用本地目录发现、内容查看、格式校验、
  启用、禁用和删除。
- 用户或第三方 Skill 不能新增模型工具、扩大 Runtime sandbox、开放网络或路径，也不能
  获得软件安装和论文库写入权限。
- 明确 Skill 名称冲突、版本、更新、损坏文件、恢复、trace attribution 和用户信任
  边界，并设计对应验收。
- 带脚本、依赖、MCP、connector 或其他可执行能力的 Skill，以及 Plugin 分发，作为后续
  独立阶段评估，不与 instruction-only 支持同时落地。

## Deferred

以下方向只有经用户明确选择后才进入规划：

- Developer ID、公证、正式公开发布和 App Store。
- 远程 MCP 与目录提交。
- 账号、套餐、托管模型、计费和多设备同步。
- 团队论文库与 Windows/Linux 客户端。
- Zotero 同步和本地模型推理。
- Swift/Rust 局部性能模块。
- 云端数据库、对象存储和 worker 集群。
