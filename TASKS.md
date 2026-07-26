# TASKS

> Paper Copilot 的当前路线图与完成状态。工程规则见
> [AGENTS.md](AGENTS.md)，技术结构和稳定架构决策见
> [ARCHITECTURE.md](ARCHITECTURE.md)，历史实现过程见 Git。

更新于 2026-07-26。

## Current Direction

Paper Copilot 是本地优先的个人论文研究工具，面向约 50–100 篇论文的知识库。产品通过
SwiftUI macOS 客户端和 Local MCP Server 两个入口复用同一 Python Core。

当前采用 BYOK。PDF、索引、结构化字段、session、报告和 trace 默认保存在本地；只有
本地检索选出的必要文本可以发送给用户配置的云端模型。当前不建设账号、支付、托管模型
或云端论文库。

## Current Work

当前正在执行 command-first 工具系统评估的四轮多论文 pilot，尚未进入代码实现
bounded slice。

已完成：

- 冻结 14 篇硕士学位论文、四轮 query 和私有 Gold；
- 完成原生 Codex 四轮盲测和基线评测；
- 基线未发现作者—方法错配，主要失败类型为 `constraint_memory_failure`；
- 给出一个优先工具方向：让 `paper_search` 返回可在后续轮次续用、并能报告遍历覆盖的
  稳定结果集合。

当前停在工具改造决策门。上述方向尚未获得实现确认，也没有修改公开工具契约、
`ARCHITECTURE.md` 或产品代码。Paper Copilot 盲测和最终对比评测尚未开始。下一步由
用户决定是停止在基线报告，还是把唯一建议定义为独立 bounded slice，明确目标失败
类型、工具契约、状态生命周期、非目标和验收方式后再实施。

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
- 已完成四轮多论文 Codex 基线；是否实施稳定结果集合方向仍待用户确认。
- 根据评估结论决定后续 bounded slice，不预设重构范围，也不在决策前修改工具。

### 2. 重新设计 Research Idea Composer

- 重新定义用户目标、工作流、证据要求、产出契约和失败模式。
- 对比单 Agent、确定性编排和多 Agent 方案的质量、成本、延迟、可恢复性与可评估性。
- 先完成设计和实验，再决定是否引入多 Agent；不为架构形式增加 Agent。

### 3. 完成 Agent 系统评估

- 盘点现有 eval suite、golden、retrieval gate、质量启发式和趋势报告的覆盖范围。
- 检查指标是否对应真实用户任务、证据质量、工具选择、安全性、成本和延迟。
- 识别不稳定、可被投机优化或缺少判别力的指标，并提出校准、替换或新增方案。

## Deferred

以下方向只有经用户明确选择后才进入规划：

- Developer ID、公证、正式公开发布和 App Store。
- 远程 MCP 与目录提交。
- 账号、套餐、托管模型、计费和多设备同步。
- 团队论文库与 Windows/Linux 客户端。
- Zotero 同步和本地模型推理。
- Swift/Rust 局部性能模块。
- 云端数据库、对象存储和 worker 集群。
