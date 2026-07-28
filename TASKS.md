# TASKS

> Paper Copilot 当前路线图、状态和下一动作。工程规则见
> [AGENTS.md](AGENTS.md)，当前架构见 [ARCHITECTURE.md](ARCHITECTURE.md)，详细设计见
> [docs/design/](docs/design/)，历史实现过程见 Git。

更新于 2026-07-28。

## 1. 当前方向

Paper Copilot 是本地优先的个人论文研究工具，通过 SwiftUI macOS 客户端和 Local MCP
Server 复用同一 Python Core。

- 当前采用 BYOK。
- PDF、索引、session、报告和 trace 默认保存在本地。
- 只有本地选择后的必要上下文发送给用户配置的模型。
- 当前不建设账号、支付、托管模型、云端论文库或多租户。
- Agent 基础设施采用 Codex-first 设计，每次只推进一个 bounded slice。

## 2. 当前工作：工具系统 v2

状态：Runtime 页面证据 slice 已完成代码实施和定向验证；冻结 Query 1 待授权，
Query 2–4 和 Slice 7 暂停。

已完成：

- 冻结 14 篇、1169 页论文、四轮 Query 和私有 Gold；
- 完成原生 Codex CLI 四轮运行并保存逐轮 JSONL 与原生 rollout；
- 完成内容寻址 TXT 缓存、`library_exec`、研究 Skill、`inspect_page`、`paper_set` 和
  四工具公开表面；
- 将批量 cache ensure 移到模型循环前的 Runtime preflight；
- 确认 session 与 lifecycle trace 的 113 个 started call ID 完全一致。

冻结 Query 1 当前结论：

- Preflight 14/14 成功，0 失败，309 ms；
- 113 次模型工具调用，比旧版 103 次增加 10 次；
- 没有调用 `paper-cache page` 或 `inspect_page`；
- approximate pages 仍使 `paper_set` 显示 14/14 complete；
- 最终引用使用 8 位短 hash，`heuristic_v1` 仍误报 coverage 1.0；
- 正常 `end_turn`，但不满足 bounded slice 的完成条件。

当前阻塞是确定性证据合同，而不是 trace：

```text
模型声明页码
→ 当前 paper_set 接受
→ coverage complete
→ 未观察页面和短 hash 仍可进入最终报告
```

[Runtime 证据源码映射](docs/design/runtime_research_evidence_codex_source_mapping.md)
及以下接口已完成代码实施：

```text
read_page + inspect_page
→ Runtime evidence ledger
→ Query 1 preflight active-set coverage
→ end-turn citation validator
```

实现删除模型可见 `paper_set`，并从 `library_exec` 移除 `paper-cache` broker；底层
内容寻址缓存、集合状态、stale、coverage 和恢复能力继续由 Runtime 持有。Query 2–4
的派生集合不在本 slice 猜测实现。

定向验证已确认新四工具表面、broker 拒绝、真实缓存页读取、短 hash 拒绝、evidence
recovery、end-turn continuation、预算 Incomplete 降级和非论文直接回答。现有 Agent
loop 测试 14/14 通过；旧 `test_paper_copilot.py` 有 19 项通过、7 项因仍断言 v2 之前的
公开工具和 Skill 布局而失败，未为兼容旧断言恢复已删除工具。

冻结 Query 1 首次重跑确认 Runtime 获得 14/14 论文、63 页真实证据，74 次工具调用均
进入权威 trace 且无失败；同时暴露省略号短引用未被识别的问题。当前实现已扩大非法
引用候选扫描，并在验证通过后把用户可见引用渲染为 `《论文题目》第 N 页`，完整
SHA-256/page 仅保留在结构化证据和 trace 中；该修订尚未重跑验证。

本 slice 当前仍缺：

- 用冻结 Query 1 重跑端到端验收；
- 根据实际 trace 判断是否通过并决定后续 scope-transition 设计。

当前不做：

- 不继续 Query 2–4；
- 不运行三次重复或完整消融；
- 不重复运行 Codex；
- 不修改模型、依赖、SwiftUI、API、MCP 或缓存格式；
- 不删除旧实现。

主计划见 [tool_system_v2_plan.md](docs/design/tool_system_v2_plan.md)，实验协议见
[codex_multi_thesis_blind_experiment_plan.md](docs/design/codex_multi_thesis_blind_experiment_plan.md)。

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
| 6 公开工具切换 | 已切换为 `library_exec/read_page/inspect_page/library_edit`，待验证 | `agent_infrastructure_codex_source_mapping.md` |
| 7 冻结评测 | 未开始 | 被 Query 1 证据合同阻塞 |
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
