# Paper Copilot 面试亮点：AI Agent 长任务中断恢复

> 记录日期：2026-07-22  
> 当前状态：桌面端交互、持久化 job、多 attempt、rollout replay、显式停止和专项验收均已完成。  
> 验证结果：相关后端限定测试 28 项通过，前端 TypeScript 检查通过。  
> 准确边界：不宣称 token 级续传、外部进程原地恢复或工具 exactly-once。

## 一句话定位

为本地论文研究 Agent 设计并实现 Codex 风格的长任务中断恢复机制：使用 append-only
rollout 和多 attempt 状态机持久化执行轨迹，在客户端断线、服务重启、模型异常或用户
主动停止后，从最近可靠边界重建模型历史和运行状态，复用已完成工具结果，并将状态不明
的调用规范化为 `aborted`，避免整项任务盲目重跑。

## 为什么这是一个工程亮点

普通聊天只需要保存用户和助手文本，但 Agent 长任务还包含：

- 模型生成的工具调用及其协议 ID；
- 已经完成、失败或仍在执行的工具；
- 论文数量预算和累计 LLM 成本；
- Composer 的 baseline、候选模块、拒绝理由和流程阶段；
- 长上下文压缩后的工作历史；
- 当前 job、attempt 和用户可见会话之间的关系。

如果中断后只重新发送原始问题，模型会丢失已经完成的研究工作，重复调用昂贵工具，甚至
重复产生写入副作用。如果直接重放最后一条工具调用，又无法判断工具是否已经部分执行。

因此核心问题不是“重新打开聊天”，而是：

> 如何确定哪些执行事实可以安全复用、哪些状态必须恢复、哪些调用只能标记为未知，并让
> Agent 在不伪造成功的前提下继续决策。

## 故障模型

系统明确区分以下情况：

| 场景 | 预期行为 |
|---|---|
| 浏览器或桌面客户端关闭 | 后端 job 继续执行，重开客户端后重新查询状态 |
| 前端与 API 断线 | 不取消后台 job，恢复连接后继续轮询 |
| 上游模型请求失败 | attempt 记为 failed，等待用户显式恢复 |
| 本地服务重启 | 遗留 queued/running job 转为 interrupted |
| 用户点击停止生成 | 取消当前 asyncio Agent task，落盘 interrupted |
| 工具结果已经持久化 | 恢复时直接复用，不再次 dispatch |
| 只有 tool call、没有 result | 补充 `aborted` 结果，不由框架自动重跑 |
| JSONL 最后一行写了一半 | 忽略或截断损坏尾行，从最后完整记录继续 |

## 核心数据模型

### Conversation、Job、Attempt 分层

```text
Conversation                     用户看到的一个多轮会话
  ├─ Job 1                       第一轮用户请求
  │    └─ Attempt 1              正常完成
  └─ Job 2                       第二轮用户请求
       ├─ Attempt 1              执行中断
       └─ Attempt 2              从 Attempt 1 的 rollout 恢复
```

- `conversation_id` 聚合 ChatGPT 式多轮对话；
- 每条新的用户问题创建新 job；
- 同一任务中断后的恢复仍属于原 job，但创建新 attempt 和新 session；
- `resumed_from_attempt` 记录恢复链，不覆盖旧 attempt。

这样既保留用户层面的连续对话，又能审计一次任务经历过多少次执行尝试。

### Append-only Session Rollout

每个 attempt 使用 JSONL session 追加记录：

- system/user/assistant message；
- LLM call 及 token、成本和停止原因；
- tool use 与 tool result；
- runtime state；
- compaction checkpoint；
- recovery base；
- turn aborted；
- final output。

原轨迹不被覆盖。恢复产生的新 attempt 写入独立 session，并在开头记录来源 session、恢复
历史和运行状态，使连续多次恢复仍然自包含。

## 恢复算法

### 1. 找到最近可靠恢复点

优先使用最新的：

1. `recovery_base`；
2. 带 `replacement_history` 的 compaction checkpoint；
3. 如果两者都不存在，则从原始用户请求开始重建。

这避免每次恢复都从最早 session 全量扫描并重复拼接已恢复过的历史。

### 2. 重建模型可见历史

从恢复点之后依次重放：

```text
assistant message
tool_use(call_id=X)
tool_result(tool_use_id=X)
user runtime context
```

已持久化的工具结果作为历史事实直接交给模型，不会再次进入工具 dispatcher。

### 3. 规范化未完成调用

重建结束后按 `call_id` 检查每个工具调用是否有配对结果。缺失结果时插入：

```json
{
  "type": "tool_result",
  "tool_use_id": "call-X",
  "content": "aborted",
  "is_error": true
}
```

这一步有两个作用：

- 保证下一次模型请求仍满足 tool call/tool result 协议；
- 明确告诉模型原调用没有可靠结果，而不是把它当成成功或自动重跑。

### 4. 恢复权威运行状态

模型历史不等于完整业务状态，因此 session 还持久化 `runtime_state`：

- touched paper IDs 与论文预算；
- 主 Agent 累计 token 和成本；
- worker 成本；
- 完整 Composer plan；
- 最近的 compaction summary。

恢复累计成本尤其重要。如果每次新 attempt 都把成本清零，用户可以通过反复恢复绕过预算。

### 5. 追加新的继续 turn

恢复不是继续上一次网络字节流，而是在重建后的历史上追加一个新 turn，其中包含：

- 最新权威 Runtime Context；
- 已完成多轮会话上下文；
- “继续刚才中断的任务”这一明确用户意图。

然后模型根据已完成结果、`aborted` 调用和现场状态决定下一步。

## 显式停止设计

任务运行时，ChatGPT 桌面端式输入框把发送按钮切换成方形停止按钮。点击后调用：

```http
POST /jobs/<job_id>/interrupt
```

后端处理流程：

```text
登记 interrupt request
  ↓
通过目标事件循环 call_soon_threadsafe(task.cancel)
  ↓
Agent loop / async tool 收到 CancelledError
  ↓
实际退出后写 turn_aborted
  ↓
attempt/job → interrupted
```

接口不会在工具还没退出时就提前宣布“已经停止”。前端收到请求后显示“正在停止”，继续
轮询直到 job 真正进入 interrupted。

系统没有增加“继续任务”按钮。恢复仍通过普通输入框中的显式自然语言触发，保持与
ChatGPT 桌面端一致的交互方式。

## 为什么不保证工具 Exactly-once

最危险的时间窗是：

```text
工具已经产生外部副作用
  ↓
进程在 tool_result 持久化前崩溃
```

恢复系统只能看到 `tool_use`，无法知道外部动作是否成功。通用 Agent 框架不能替所有
文件系统、数据库、网络 API 和第三方服务实现分布式事务。

本项目采用与 Codex 相同的保守语义：

- 已有持久化结果：复用，不重跑；
- 缺失结果：标记 `aborted`；
- 模型获知工具可能部分执行；
- 是否检查现场或重新调用，由下一轮模型决定；
- 真正有写副作用的业务工具应自行提供幂等键或状态查询能力。

面试中可以强调：**不虚构 exactly-once 保证，本身就是可靠性设计的一部分。**

## 为什么选择显式恢复而不是自动重试

中断后的外部世界可能已经改变。自动重试容易造成：

- 重复写文件或重复提交外部任务；
- 重复消耗模型和论文读取预算；
- 在用户本来想停止时继续执行；
- 服务重启后形成无限重试循环。

因此 failed/interrupted 是稳定终态。只有用户明确输入恢复意图时，系统才创建下一
attempt。客户端重连只恢复显示和轮询，不扩大为自动执行授权。

## 持久化安全

### Session JSONL

每条记录写入后执行 flush 和 `fsync`。追加前检查文件末尾：如果上一进程只写入半条
JSON，则截断到最后一个完整换行，再追加新记录。

### Job 状态

`job.json` 使用临时文件写入、flush、`fsync` 后再原子替换。生命周期事件使用
append-only `events.jsonl`，同样处理损坏尾行。

这种设计没有引入数据库依赖，适合本地桌面应用，同时覆盖了常见的进程崩溃写入问题。

## 与长上下文压缩的关系

恢复不能假设历史永远小于模型窗口。达到阈值后，compaction 会保存实际发送给模型的
`replacement_history`。恢复从最近 checkpoint 开始，同时继续保留完整原始 JSONL 用于
审计。

因此两个机制的职责不同：

- 上下文压缩解决“历史太长，如何继续工作”；
- 中断恢复解决“执行被打断，如何从可靠边界继续”；
- replacement history 把二者连接起来。

详细压缩设计见 [`long_context_compaction.md`](long_context_compaction.md)。

## 实现范围

- `session/types.py`：`RuntimeState`、`RecoveryBase`、`TurnAborted` 和 compaction replacement history；
- `session/store.py`：append-only 写入、`fsync`、损坏尾行修复；
- `session/recovery.py`：rollout 重建和缺失结果规范化；
- `agents/loop.py`：模型响应、工具结果后的恢复状态快照；
- `agents/paper_copilot.py`：恢复成本、论文预算、Composer plan 和模型历史；
- `agents/composer_plan.py`：完整计划反序列化；
- `chat/jobs.py`：job/attempt 生命周期、服务重启处理、interrupt/resume；
- `api/http.py`：job 查询、事件、停止和恢复 API；
- `apps/web/`：任务轮询、重连恢复显示和停止生成按钮；
- `tests/session/test_recovery.py`、`tests/chat/test_jobs.py`：故障注入验收。

没有新增第三方依赖，也没有新增 LLM call site。

## 验证证据

使用无外网、确定性假模型和可控阻塞工具进行故障注入，覆盖：

1. 客户端提交后断开，后台 job 仍完成；
2. 上游模型断网，job 停在 failed，不自动重跑；
3. 服务读取遗留 running 记录后转为 interrupted；
4. 已完成工具结果在恢复后仍存在，dispatcher 调用次数保持为 1；
5. 只有 tool call 没有 result 时补 `aborted`；
6. 阻塞工具期间调用 interrupt，async task 被取消；
7. 显式停止后恢复，原工具不自动重跑；
8. attempt 1→2→3 连续恢复链正确；
9. 最近 RecoveryBase 和 compaction checkpoint 生效；
10. JSONL 损坏尾行修复后可以继续追加。

最终结果：

```text
28 passed
frontend TypeScript typecheck passed
```

准确表述是“确定性故障注入覆盖的恢复不变量全部通过”，不要扩大为“任意外部工具都能
无损恢复”。

## 简历表述

### 推荐版本

> 设计并实现 AI Agent 长任务中断恢复机制，基于 append-only rollout 与多-attempt
> 状态机，在客户端断线、服务重启、模型异常和用户取消后恢复执行上下文；复用已完成
> 工具结果，将状态不明调用规范化为 aborted，并恢复累计成本、论文预算、上下文压缩
> checkpoint 与规划状态，避免整任务重跑和无条件工具重试。

### 更偏后端可靠性

> 为本地 Agent 平台建立可审计的 job/attempt 生命周期和崩溃恢复协议，采用原子 job
> 状态写入、append-only JSONL、fsync、损坏尾行修复及线程安全 asyncio 取消；通过
> 确定性故障注入验证已完成工具不重复 dispatch、未完成调用安全终止和连续多次恢复。

### 更偏全栈

> 实现 ChatGPT 桌面端式长任务体验：客户端重连恢复状态、运行中停止生成、显式自然语言
> 恢复和多轮会话聚合；后端以 rollout replay 延续 Agent 工作，并保持工具结果、成本预算
> 和规划状态一致。

### 不要这样写

> 实现断点续传，保证 Agent 和所有工具 exactly-once。

这会夸大能力。系统不是从 LLM token、HTTP 字节流或任意外部进程的程序计数器继续，也
不能为未知第三方副作用提供 exactly-once。

## 30 秒面试回答

> 我在 Paper Copilot 里实现了一套 Codex 风格的 Agent 中断恢复。每个长任务是一个
> 持久化 job，每次执行是独立 attempt，模型消息、工具调用、工具结果和运行状态都追加到
> JSONL rollout。恢复时不会重跑原始问题，而是重建最近历史，复用已有工具结果，对缺失
> 结果的调用补一个 aborted，再恢复成本预算和 Composer 计划并创建新 attempt。用户停止
> 生成时会线程安全地取消 asyncio task。这个方案不虚构 exactly-once，而是明确处理工具
> 可能部分执行的灰色状态。

## 2 分钟 STAR 讲法

### Situation

论文研究 Agent 一次任务可能调用多个搜索、读取和比较工具，执行时间长。客户端关闭、
网络错误或服务重启后，如果只能从原始问题重跑，会重复消耗模型费用和论文分析预算，也
可能重复产生工具副作用。

### Task

在不引入新数据库或分布式事务的情况下，让本地桌面 Agent 可以安全停止和恢复，同时
保留多轮会话体验、上下文压缩和成本限制。

### Action

1. 将用户会话、job 和 attempt 分层；
2. 用 append-only JSONL 持久化完整 rollout；
3. 在模型响应和工具结果后保存 runtime state；
4. 从 RecoveryBase 或 compaction checkpoint 重建历史；
5. 按 call ID 复用完成结果，为缺失结果补 `aborted`；
6. 恢复累计成本、论文预算和 Composer 状态；
7. 用线程安全 asyncio task cancellation 接入停止按钮；
8. 用阻塞工具和网络异常做确定性故障注入。

### Result

客户端断线不影响后台执行；服务重启、模型失败和用户停止都会形成可审计终态；用户明确
恢复后创建新 attempt，完成工具不会重复 dispatch。相关后端测试 28 项和前端类型检查
全部通过。

## 高频追问

### 为什么恢复要创建新 attempt，而不是继续写旧 session？

旧 attempt 的终止原因和最后可靠边界需要保持不可变，便于审计和定位问题。新 attempt
记录来源并拥有独立 session，可以清楚区分原执行和恢复执行，也支持连续多次恢复。

### 如何保证工具不会重复调用？

已经有持久化 `tool_result` 的调用不会重新进入 dispatcher。只有 call 没有 result 时才
标记为 `aborted`。框架不会自动重跑，但模型之后可能基于现场检查发起一个新的调用。

### 如果工具已经成功，但结果还没来得及写盘呢？

这是无法由通用框架消除的不确定窗口。系统会告诉模型工具可能部分执行，并将调用标记为
`aborted`。写入型业务工具如果要求更强语义，应提供幂等键、事务日志或状态查询接口。

### 为什么不用数据库和消息队列？

这是单机桌面应用，当前并发和部署规模不需要分布式基础设施。原子替换加 append-only
JSONL 已覆盖本地崩溃恢复，并保持依赖和运维成本较低。如果扩展到多实例 worker，才需要
把 job lease、幂等执行和事件日志迁移到数据库或队列。

### 为什么不自动恢复 interrupted job？

自动恢复既可能违背用户停止意图，也可能重复执行状态不明的副作用。显式恢复把授权边界
交还用户，同时避免服务重启后的无限重试。

### 前端关闭为什么不会中断任务？

HTTP 创建接口只负责持久化 job 并启动后台线程，任务生命周期不绑定创建请求的 TCP
连接。前端只保存 job ID，重开后通过 job 查询和增量事件接口重新发现状态。

### 如何处理上下文窗口？

未达到压缩阈值时保留全部活动历史；达到阈值后使用结构化 compaction replacement
history。恢复从最近 checkpoint 开始，而原始 session 仍完整保留用于审计。

### 与 Codex 的做法有什么关系？

设计上借鉴了 Codex 的几个关键原则：持久化 rollout、resume thread、给缺失工具输出补
`aborted`、向模型暴露 turn aborted，并承认工具可能部分执行。项目没有照搬 Codex 的
全部基础设施，而是为单机论文 Agent 实现了与当前规模匹配的最小闭环。

### 这项工作的最大技术取舍是什么？

选择 at-least-observable，而不是虚构 exactly-once：系统保证执行轨迹可审计、完成结果
可复用、未知状态被明确标记；更强的副作用一致性交给具体工具的幂等协议处理。

## 面试前快速检查清单

- 能否画出 Conversation → Job → Attempt 三层关系；
- 能否解释为什么恢复创建新 attempt；
- 能否说清 `tool_use` 有结果和无结果的不同处理；
- 能否解释 exactly-once 不成立的崩溃窗口；
- 能否说明为什么显式恢复比自动重试安全；
- 能否说明成本、论文预算和 Composer plan 为什么必须恢复；
- 能否准确报出验证结果：28 个相关后端测试、前端 typecheck；
- 不要声称 token 级断点续传、外部进程原地恢复或所有工具无副作用重试。
