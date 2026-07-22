# Paper Copilot 面试亮点：Agent Rollout 可观测与运行时防护

> 记录日期：2026-07-22  
> 当前状态：Rollout trace、严格 reducer、诊断 API、Web 面板、循环熔断、工具超时、
> Rollout deadline 和安全 Payload 已完成；retention dry-run/tombstone 工具已实现，尚待
> 独立验证和提交。  
> 准确边界：这是面向本地 Agent Runtime 的可观测系统，不宣称是完整的分布式链路追踪
> 平台；当前没有 OTEL exporter、远端聚合告警或后台自动删除。

## 一句话定位

为本地论文研究 Agent 设计并实现一套 Codex 风格的 Rollout 可观测系统：将一次任务执行
拆成带父子关系的 Rollout、Turn、LLM、Tool 和 Compaction 事件链，使用 append-only
JSONL 保存事实、严格 reducer 重建状态，并结合诊断 API、前端面板和运行时 guard，定位
无限工具循环、工具失败、未完成操作和高延迟问题。

## Rollout 是什么

Rollout 是 Agent 为完成一次用户任务而产生的完整执行轨迹，而不只是模型的一次回答。

```text
Rollout：一次 job attempt
  └─ Turn：一次 Agent 决策轮次
       ├─ LLM Call：模型请求
       ├─ Tool Call：工具执行
       └─ Compaction：上下文压缩
```

一个 Rollout 可能经历多轮“模型决定 → 调工具 → 把结果交回模型”，直到完成、失败、取消
或超时。观察 Rollout 才能回答“Agent 为什么卡住”，普通应用日志通常只能看到最后一个
异常字符串。

## 为什么这是可观测性，而不只是加日志

普通日志通常是互相独立的文本行，难以可靠回答：

- 哪个工具调用属于哪次模型决策；
- 首个故障发生在哪里，后续错误是否只是连锁反应；
- 总延迟主要来自 LLM、工具还是上下文压缩；
- 某个工具是否使用完全相同的参数反复调用；
- 进程中断后哪些操作只有 started、没有 terminal；
- 日志文件最后半行损坏时，前面的执行事实是否仍然可信。

本项目为每个操作提供稳定的 `entity_id`、`parent_entity_id`、开始/终止事件、状态、耗时、
错误和 Payload 引用。Trace 因而可以归约、校验和查询，而不是只能全文搜索。

## 数据落盘设计

每个 job attempt 使用独立 bundle：

```text
jobs/<job_id>/attempts/<n>/
├── manifest.json       # trace/job/attempt/session/turn 身份与 Payload policy
├── trace.jsonl         # append-only 生命周期事实
├── state.json          # reducer 生成的可重建缓存
└── payloads/*.json     # 脱敏、有界的输入输出证据
```

### Trace 是事实，State 是投影

- `trace.jsonl` 只追加，不原地修改历史事件；
- reducer 从完整事件前缀重建所有 operation；
- `state.json` 只是缓存，损坏或丢失时可从 trace 重建；
- 最后一条没有换行的 JSON 被视为崩溃或并发 append 留下的 torn tail，不参与归约；
- reducer 检查连续序号、事件 ID 唯一性、父子关系、实体类型、生命周期和 Payload 引用。

这与 event sourcing 的思路相似：事实日志与派生视图分离，但范围只覆盖本地 Agent 诊断，
没有把整个业务系统改造成事件溯源架构。

### 三个真源各负其责

| 数据 | 职责 |
|---|---|
| `session.jsonl` | 模型历史和中断恢复真源 |
| `job.json` | 调度状态、attempt 状态和用户可见任务真源 |
| `trace.jsonl` | 性能、调用链和故障诊断真源 |

没有让 Trace 同时承担恢复和调度，避免诊断模型与业务状态机强耦合。

## Trace 上下文如何传播

使用 Python `contextvars` 保存当前 recorder 和父实体。进入 LLM、Tool 或 Compaction
操作时自动取得当前父节点，退出时恢复原上下文。

这样做的收益：

- 不需要给每个工具接口增加 `trace_id`、`span_id` 参数；
- 异步 task 内仍能传播当前调用链；
- 工具保持业务接口，不依赖可观测实现；
- Agent loop、LLM client 和 job runner 可以在各自边界记录 span。

面试时可以强调：可观测性是横切关注点，但不能以污染所有业务函数签名为代价。

## 如何定位典型问题

### 无限或重复工具循环

诊断器按“工具名 + 规范化 JSON 参数的 SHA-256”聚合调用。同一工具使用相同输入重复出现
时，报告调用次数和相关 entity IDs。

系统还提供在线保护：连续第三次出现完全相同的工具调用时，在 dispatch 前写入
`tool_call.aborted` 并抛出 `ToolLoopError`。因此它同时具备：

- 事后诊断：知道哪个工具和输入发生重复；
- 在线止损：避免继续消耗时间、Token 或产生副作用；
- 可恢复语义：中断恢复时把缺失结果规范化为 aborted，不自动重放。

不同工具或不同参数会重置连续计数，避免把正常的迭代搜索误判为死循环。

### 工具错误

每个 Tool Call 记录 started、terminal status、真实持续时间、错误类型和错误消息。诊断器
按事件顺序返回第一个 failed/aborted operation，而不是只展示最终 job error。

这样能区分：

- 工具自身失败；
- 连续重复调用被 guard 拦截；
- 工具超过 600 秒 deadline；
- 用户主动取消；
- 整次 Rollout 超时导致子任务取消。

### 高延迟

诊断结果按实体类型累计耗时：

```text
rollout / turn / llm_call / tool_call / compaction
```

同时列出超过阈值的 slow operations，并按耗时倒序展示。面试时不要声称这些累计时间一定
等于墙钟时间：父子 span 会重叠，累计值用于归因比较，总墙钟时间以根 Rollout 为准。

### 卡死或进程异常退出

只有 started、没有 terminal 的 operation 会进入 unfinished 列表。结合最后完整事件，
可以判断任务停在 LLM 请求、工具 dispatch 还是上下文压缩阶段。

## 运行时防护

### 单工具 Timeout

工具 dispatch 默认最多 600 秒，只包围工具执行，不误伤 LLM 请求、持久化或 Compaction。
超时后：

- 抛出独立的 `ToolTimeoutError`；
- Tool span 标记 failed；
- 保存实际耗时和 timeout 配置；
- 用户取消仍保持 cancelled，不被误报为 timeout。

### Rollout Deadline

每个 job attempt 默认最多运行 3600 秒。父协程监管独立 Agent child task；deadline 到期
后取消并等待 child task 收敛，再抛出 `RolloutTimeoutError`。

这避免出现“job 已经失败，但后台 Agent 还在继续调用工具”的幽灵任务。用户显式停止与
deadline 是两套语义：前者进入 interrupted/cancelled，后者进入 failed。

### 为什么需要两层超时

- Tool timeout 限制一次外部操作；
- Rollout deadline 限制模型、工具和压缩组合形成的整次任务；
- 只有 Tool timeout 无法阻止大量短调用组成的长任务；
- 只有 Rollout deadline 又难以指出具体是哪个工具卡住。

## Payload 安全与生命周期

### 写盘前安全处理

`local_safe_v1` 在 Payload 写盘前执行：

- 按键清除 authorization、cookie、password、secret、token 和 API key；
- 清除文本中的 Bearer/Basic credential、`sk-...` 和常见凭据赋值；
- 单字符串最多保留 2000 字符预览；
- 限制集合大小、映射键数和嵌套深度；
- 脱敏后超过 256 KiB 的 Payload 只保留 16 KiB 预览、大小和 SHA-256。

Trace 的目标是留下足够的诊断证据，不是复制完整 Prompt 和论文内容。完整模型历史仍由
session 保存。

### 为什么使用 Tombstone，而不是直接删除文件

直接删除过期 Payload 会让 trace 中的引用悬空，严格 reducer 随即报告完整性错误。
Retention 工具将正文原子改写为 tombstone，保留：

- Payload ID 和 kind；
- 原值 SHA-256；
- 原文件 SHA-256；
- 原文件大小和 policy；
- 清理时间与原因。

重复工具检测可直接使用 tombstone 保存的原值哈希，因此正文过期后仍能识别相同输入。

默认命令只做 dry-run：

```bash
uv run python scripts/observability_payloads.py
```

只有显式传入 `--apply` 才会改写超过 30 天且 Rollout 已终止的 Payload。运行中的 attempt
永不改写；扫描后文件发生变化时，哈希校验会拒绝执行。当前没有后台自动清理。

## 诊断接口和前端

后端提供：

```http
GET /jobs/<job_id>/diagnostics?attempt=N&slow_ms=1000&repeat_threshold=3
```

默认分析最新 attempt，返回：

- Rollout 状态、事件数和总耗时；
- 各类 operation 累计耗时；
- 第一个错误；
- 慢操作；
- 未完成操作；
- 重复工具调用。

Web 右侧诊断面板展示同一信息；运行中任务定时刷新，终态到达时立即刷新，也支持手动刷新。

## 关键设计取舍

### 为什么没有一开始就接 OpenTelemetry

项目当前是本地单体应用，首要目标是可恢复、可检查的本地证据。JSONL 方案具备：

- 无新依赖；
- 无需部署 Collector、Jaeger 或 Grafana；
- 离线可用；
- 崩溃后仍可直接检查；
- 与本地 job attempt 天然对应。

代价是暂时没有跨进程 trace、远端查询和告警。等系统演进为多进程或远程服务时，可以把
当前 operation 模型映射为 OTEL span，而不需要推翻本地事实模型。

### 为什么不是所有重复调用都立即禁止

Agent 可能合法地重复查询，尤其是幂等读取工具。系统只拦截“连续、同工具、同规范化输入”
达到阈值的情况，并保留可配置开关。它是针对明显失控模式的 guard，不是通用策略引擎。

### 为什么错误要“首错优先”

Agent 系统常出现级联失败：一个工具失败后，模型继续尝试，最终以预算耗尽或总超时结束。
最终错误描述结果，首个错误更接近根因。诊断报告两者都保留，但默认突出首错。

## 验证证据

核心可观测里程碑的相关限定测试共 36 项通过，覆盖：

- 正常生命周期、序号断裂、重复 terminal 和缺失 Payload；
- torn tail；
- 首错、慢操作、未完成操作和重复工具；
- completed、failed、interrupted 的真实 HTTP job diagnostics；
- 循环熔断及恢复；
- Tool timeout 与 Rollout deadline；
- Payload 脱敏、大小限制和旧 manifest 兼容。

前端 TypeScript 检查和生产构建通过。Retention 目前完成了临时合成数据手动演练：2 个
过期 Payload 改写后，reducer 仍返回 completed，重复工具计数仍为 2。真实默认数据目录的
dry-run 当前扫描到 0 个 bundle。Retention 尚未运行独立 Ruff、mypy、pytest，面试时不要
把手动演练描述成完整自动化测试。

## 简历表述

### 一条综合版

> 设计并实现本地优先的 Agent Rollout 可观测与故障防护系统，将 Turn、LLM、Tool 和
> Context Compaction 建模为可归约的父子事件链；基于 append-only JSONL、严格状态归约、
> 诊断 API 和 Web 面板，支持首错定位、阶段耗时、慢调用、未完成 Span 与重复工具检测，
> 并通过循环熔断、分层超时和安全 Payload 生命周期限制失控任务与敏感数据风险。

### 拆成两条

> 基于 append-only JSONL 和严格 reducer 构建 Agent Rollout trace，校验事件顺序、父子
> 生命周期和 Payload 引用，支持崩溃尾行容错、首错定位、慢调用和重复工具诊断。

> 实现连续相同工具调用熔断、600 秒 Tool timeout 和 3600 秒 Rollout deadline，并设计
> 写盘前脱敏、大小限制和保留引用完整性的 tombstone retention 策略。

## 两分钟面试回答模板

> 论文 Agent 的一次任务不是单次模型请求，而是多轮 LLM、工具和上下文压缩组成的
> Rollout。原来只靠普通日志，很难判断无限循环、工具失败或延迟究竟发生在哪一层。
>
> 我把每个 job attempt 建模成一棵 operation tree，根节点是 Rollout，下面是 Turn、
> LLM Call、Tool Call 和 Compaction。每个实体都有 started 和 terminal 事件，事件追加到
> JSONL；严格 reducer 校验序号、父子关系、生命周期和 Payload 引用，再生成可重建状态。
> 诊断层可以直接给出首错、各阶段耗时、慢操作、unfinished span 和相同工具输入的重复
> 次数，前端也有对应面板。
>
> 我没有只做事后观察，还增加了运行时保护：连续第三次相同工具输入会在 dispatch 前
> 熔断，单工具和整次 Rollout 分别有 timeout，并严格区分用户取消与系统超时。Payload
> 写盘前脱敏和限长，过期后用 tombstone 移除正文但保留哈希与引用，所以 reducer 和重复
> 调用诊断不会失效。
>
> 关键取舍是让 session、job 和 trace 分别负责恢复、调度和诊断；当前本地场景没有急于
> 引入 OTEL，未来需要跨进程聚合时再把现有 operation 映射成 span。

## 常见追问

### “这和 OpenTelemetry 的 Trace/Span 有什么区别？”

概念上 Rollout 对应一条 trace，LLM/Tool/Compaction operation 类似 span；区别是当前实现
针对本地 Agent 的恢复与诊断需求，存储为 JSONL 并带有严格业务生命周期校验。OTEL 更擅长
跨服务传播、统一 exporter 和后端查询。两者不是互斥关系，未来可以增加 exporter。

### “为什么不用数据库？”

当前是单用户本地应用，按 attempt 顺序追加的写入模式与 JSONL 很匹配。JSONL 易审计、
崩溃损失边界清晰、无需迁移和常驻服务。当前规模下先保持简单；如果需要跨任务聚合查询、
高并发写入或长期分析，再增加索引数据库或 OTEL 后端。

### “怎么避免观测系统本身拖慢主流程？”

事件只写有界元数据和 Payload 引用，正文单独脱敏并限制大小；状态投影按需归约，不在每条
事件后执行复杂分析。代价是每条事件执行 flush/fsync，换取本地崩溃后的证据完整性。若未来
吞吐成为瓶颈，可批量刷盘，但需要重新评估崩溃丢失窗口。

### “能保证检测所有无限循环吗？”

不能。当前准确检测的是连续相同工具名和相同规范化参数的重复调用。参数不断变化、多个
工具交替或模型纯文本自循环需要更高层的策略、预算和 deadline 共同约束。面试中应主动
说明这个边界。

### “为什么累计阶段耗时可能超过总耗时？”

父子 span 会包含或重叠。例如 Turn duration 包含其内部 LLM 和 Tool duration。阶段累计值
用于同类操作的成本归因，不能与根 Rollout 墙钟时间直接求和。

## 不能夸大的能力边界

- 不是完整的分布式 tracing 平台；
- 当前没有 OTEL、Jaeger、Grafana 或远端告警；
- 不保证检测所有形式的 Agent 循环；
- 不保证工具 exactly-once；
- Trace Payload 不是完整会话备份；
- tombstone 会删除正文预览，之后只能使用哈希和元数据诊断；
- 当前 retention 不后台自动运行，也不删除整个 attempt bundle；
- 尚无生产规模的磁盘、吞吐和长期保留压测数据。

## 面试前 30 秒复习

记住五个关键词：

1. **Rollout operation tree**：Rollout → Turn → LLM/Tool/Compaction；
2. **append-only + strict reducer**：事实与投影分离，可校验、可重建；
3. **first error + slow + unfinished + repeat**：四类核心诊断；
4. **loop breaker + two-level timeout**：事后可见，也能在线止损；
5. **safe payload + tombstone**：移除敏感正文但保持引用和哈希诊断能力。
