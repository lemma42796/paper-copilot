# TASKS

> Paper Copilot 的当前路线图与完成状态。工程规则见
> [AGENTS.md](AGENTS.md)，技术结构和稳定架构决策见
> [ARCHITECTURE.md](ARCHITECTURE.md)，历史实现过程见 Git。

更新于 2026-07-28。

## Current Direction

Paper Copilot 是本地优先的个人论文研究工具。产品通过 SwiftUI macOS 客户端和 Local
MCP Server 两个入口复用同一 Python Core。

当前采用 BYOK。PDF、索引、结构化字段、session、报告和 trace 默认保存在本地；只有
本地检索选出的必要文本可以发送给用户配置的云端模型。当前不建设账号、支付、托管模型
或云端论文库。

## Current Work

当前已完成 Codex CLI 四轮可审计基线、工具系统 v2 实施计划和 Slice 1–6。权威基线
位于私有 `runs/codex-cli-jsonl-v2/`，固定 `codex-cli 0.145.0`、
`gpt-5.6-sol` 和 `low` reasoning，保存逐轮 JSONL 与原生 session rollout。旧桌面端
回答及其依赖模型自报的评测报告已删除；新 CLI 基线尚待按同一 Gold 重新评分。
首次 v2 Query 1 预检在进入质量评测前暴露了 Unicode 论文目录 sandbox 授权、
macOS 客户端沿用默认五篇预算，以及空 `paper_set` 真空完成三个阻塞问题。纠正实现
已落地。第二次 Query 1 证明目录和 14 篇预算已生效，但被 Paper Copilot 专有的固定
`max_turns` 截断；该非 Codex 终止条件现已从 API、job、Runtime、Agent loop 和 trace
删除。第三次 Query 1 随后暴露 Poppler 解析规则分裂、broker 复合命令误用、
`inspect_page` ID 协议不一致和 Skill 版本常量漂移；对应修正已落地。第四次 Query 1
中 Skill v4 已生效，但 broker 将模型从 workspace 发现的
`library/<relative-pdf>` 错误地再次拼到 library 根，导致模型绕过 cache 并输出无页码
猜测。路径现已归一化，Skill 更新为 version 5，明确 call-local scratch、broker 失败
不得退化为临时全文脚本、全量 coverage 未完成不得输出填充后的分类表。确定性
end-turn coverage guard 尚待按 Codex-first 设计确认。下一步先用同一冻结 Query 1 和
全新 Paper Copilot 会话重跑端到端验收。通过后再继续完整四轮预检，以新的 Codex CLI
JSONL 基线作为对照，保存完整工具 trace，并对照私有 Gold 报告质量、跨轮约束、遍历
完成、引用和工具行为。比较前必须先生成新的 CLI 基线评分报告；当前不再重复运行
Codex，也不执行完整消融。

第五次 Query 1 触发 3000-token 客户端输出上限且工具编排显著重于当时的旧桌面端
自报基线后，用户确认启动 Codex 风格简化重构；该比较只保留为历史决策背景，不作为
当前量化基线。第一 bounded slice 已把预算内 PDF 的 cache ensure
移到模型循环前的 Runtime preflight，并通过受信任 `research_cache_index` 一次提供
逻辑 TXT 路径；Skill 不再要求模型逐篇调用 `paper-cache status/ensure`。`paper_set`
和页级 evidence 协议本 slice 保持不变，尚待后续 slice 与冻结 Query 1 验收。

该预检不等于完成 Slice 7。三次重复、完整消融和正式冻结结论继续留在 Slice 7，是否
投入由预检结果和后续用户确认决定。计划见 `docs/design/tool_system_v2_plan.md`。

已完成：

- 冻结 14 篇硕士学位论文、四轮 query 和私有 Gold；
- 完成原生 Codex CLI 四轮盲测，保存 4 轮回答、17 次实际命令调用、逐轮 JSONL、
  原生 session rollout、token 和耗时；
- 校验 CLI 基线的 14 篇 PDF 哈希与冻结 manifest 一致；旧桌面端评分结论不再作为
  当前基线事实，新评分报告尚待生成；
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
PATH。`paper_set` 已在 Slice 5 完成，公开工具切换仍留待 Slice 6。

v2 Slice 3 已完成：加入可审查的内建 `research-papers` Skill，覆盖缓存检查、确定性
全文提取、`rg`/`awk` 搜索、PDF 页定位、`paper-cache page` 有界证据以及
`incomplete`/`unresolved` 表述。Skill 在首次运行、恢复和 context compaction 后重新
注入，版本和正文 SHA-256 进入权威 trace 与 final payload，并随 `.app` Runtime
打包。源码映射见 `docs/design/research_skill_codex_source_mapping.md`。当前没有新增
宿主软件安装能力；Poppler 缺失时 Skill 先请求明确同意，宿主能力不可用时明确停止，
不会借 `library_exec` 绕过无网络和无权限升级边界。

v2 Slice 4 已完成：加入内部 `inspect_page`，使用授权 `paper_id`、单页页码和可选
归一化 region 调用 `pdftoppm` 生成有界 PNG，并返回绑定 PDF SHA-256、页码、region
和 render SHA-256 的 evidence metadata。模型配置按固定 Codex 语义声明
`input_modalities`，旧配置缺失时默认 `text + image`；不支持图像的模型在解析 PDF
和渲染前明确拒绝，不执行文本回退。图像 data URL 只进入当前模型上下文，不写入
session、日志或 trace。真实 134 页论文的整页、局部区域、纯文本能力拒绝和越界页
手工验收已通过。公开工具列表仍未切换，OCR、批量页面、第二模型和全文入库均未加入。
源码映射见 `docs/design/inspect_page_codex_source_mapping.md`。

v2 Slice 5 已完成：加入内部 `paper_set`，提供 create/derive/record_evidence/status，
以不可变集合绑定 PDF SHA-256、授权 locator 和当前 cache revision；coverage 只有在
每篇成员均记录可验证页级 evidence 且没有 stale 成员时才 complete。状态通过通用
append-only application event 写入 session，并可沿 recovery source session 顺序重放
重建。cache 缺失时不会触发提取，需先显式运行 `paper-cache ensure`。公开工具列表、
Research Skill 更新和 macOS 兼容仍留待 Slice 6。源码映射见
`docs/design/paper_set_codex_source_mapping.md`。

v2 Slice 6 已完成公开表面实施：模型公开表面切换为 `library_exec`、`inspect_page`、
`paper_set` 和 `library_edit`；异步 Runtime 在 schema 解析和执行前拒绝未公开旧名称。
首次 Query 1 端到端预检后已修正 Unicode sandbox 路径、客户端论文预算传递和空集合
完成语义。第二次预检确认宿主 Poppler 可用，但 cache、命令 sandbox 与页渲染各自使用
不同的可执行文件解析规则，模型还把 broker 当成 PATH 命令写入循环，并截断 SHA-256
调用 `inspect_page`；现已统一解析规则、拒绝复合 broker 命令，并允许页检查直接接收
完整 SHA-256。Slice 6 的内建 `research-papers` Skill 修正版本为 version 5；当前简化
slice 已更新为 version 6，版本均从同一正文解析，不维护重复常量。该简化版本尚待用
冻结 Query 1 重跑验收，因此 Slice 6 尚未重新冻结。
旧实现只作为不可由模型调用的回滚代码保留；Slice 7 的三次冻结评测与消融尚未开始。源码映射见
`docs/design/tool_surface_v2_codex_source_mapping.md`。

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
- 已完成四轮多论文 Codex CLI JSONL 基线、稳定结果集合和四工具公开表面切换。
- 已确认先运行一次完整 v2 四轮预检，复用新的 Codex CLI 基线并暂缓完整消融；比较前
  先按私有 Gold 重新评分 CLI 回答。该预检不产生 Slice 7 已完成结论。
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

- 在工具系统 v2 完成并冻结后再规划，不并入当前 Slice 7。
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
