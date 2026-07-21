# Paper Copilot 面试亮点：Prompt 可追溯与 Eval 回归归因

> 记录日期：2026-07-21  
> 当前状态：Prompt 指纹、session 调用记录和 eval run 归因链路已实现；趋势图版本切换标记和真实 Prompt 前后对照实验尚未完成。

## 一句话定位

为论文研究 Agent 建立内容寻址的 Prompt 可追溯机制：对实际发送的 System Prompt、Tool Schema 和 Tool Choice 生成稳定 SHA-256 指纹，将其贯通每次 LLM 调用日志与 eval 历史，使质量、成本和延迟变化能够归因到具体 Prompt 合同，而不只依赖 Git commit。

## 为什么这是亮点

“给 Prompt 加一个版本号”只是普通配置管理。这里解决的是 LLM 系统特有的可复现与归因问题：

- Prompt 不只存在于 System Prompt；Tool Schema、工具描述和 Pydantic `Field.description` 都会影响模型行为；
- Git SHA 无法识别未提交改动，也无法直接区分 Prompt、Schema、模型和普通代码变化；
- 同一个 Prompt、同一个模型仍有随机噪声，必须把版本身份与多次 eval 趋势结合；
- Schema retry 会产生多次 LLM 调用，重复调用不能被误认为多个 Prompt 版本；
- 旧 session 和旧 eval JSONL 仍需继续读取，不能因观测字段升级破坏历史数据。

这项设计体现的是 LLMOps、可观测性、内容寻址、Schema Engineering 和 eval 归因，而不是单纯 Prompt Engineering。

## 问题背景

项目原本已经记录：

- session header 中的模型；
- 每次 LLM 调用的 agent、token、缓存、延迟和 stop reason；
- eval run 的 Git SHA、字段通过率、成本、延迟和缓存命中率；
- 完整 System Prompt 文本。

但这些信息无法回答一个关键问题：

> 某次 eval 趋势断崖，究竟对应哪一组实际发送给模型的 Prompt 与 Schema？

只保存 System Prompt 还不够。例如修改 `Method.novelty_vs_prior` 的 `Field.description`，不会改变 `_SYSTEM_PROMPT`，却会改变 LLM 在 forced tool call 中看到的生产指令。

## 关键设计

### 1. 指纹覆盖“指令合同”，不覆盖动态任务数据

单次 Prompt 指纹覆盖：

```text
实际发送的 system
+ 完整 tools / input_schema
+ tool_choice
```

论文正文、用户问题和动态消息不参与计算。这样同一套指令合同在不同论文上得到相同指纹，能够用于跨任务聚合。

序列化使用：

- JSON key 排序；
- 固定紧凑分隔符；
- UTF-8；
- SHA-256。

因此字典插入顺序不会造成无意义的版本变化，但数组顺序和实际内容变化仍会改变指纹。

### 2. Schema 是 Prompt 的组成部分

项目使用 Pydantic Schema 约束结构化工具输出，`Field.description` 会进入模型看到的 Tool Schema。因此指纹必须计算完整 tools，而不是只计算 `_SYSTEM_PROMPT`。

下面的变化都会产生新指纹：

- System Prompt 修改；
- 工具描述修改；
- 字段 description 修改；
- enum、required 字段或嵌套结构修改；
- Tool Choice 修改；
- cache 标记等实际请求结构修改。

### 3. 每次 LLMCall 保存 Prompt 身份

`session.jsonl` 的 `LLMCall` 新增可选字段：

```json
{
  "type": "llm_call",
  "agent": "ExtractPaperTool",
  "model": "qwen3.6-flash",
  "prompt_sha256": "..."
}
```

结构化 worker、主 Agent loop 和 Composer repair 三条 LLM 路径使用同一个指纹函数。Schema retry 与多轮 Agent loop 会记录相同指纹，保留逐调用成本，同时不制造虚假的 Prompt 版本。

字段设计为可选，旧 JSONL 没有 `prompt_sha256` 时仍能正常读取。

### 4. 多组件调用聚合成 Prompt Bundle

一次 `ReadPaperTool` 可能依次调用：

```text
SkimPaperTool
-> ExtractPaperTool
-> 可选 LinkRelatedPapersTool
```

系统先按 `(component_name, prompt_sha256)` 去重和排序，再计算 `prompt_bundle_sha256`。这样：

- retry 次数不会改变 bundle；
- 组件顺序的偶然变化不会改变 bundle；
- 任意组件 Prompt 或 Schema 变化都会产生新 bundle；
- 相同 hash 被不同组件使用时仍保留组件身份。

### 5. Eval Run 保存模型与 Prompt Bundle

`RunRow` 新增：

```text
model
prompt_bundle_sha256
```

普通 smoke suite 和 research quality run 都会写入这两个字段。旧 eval JSONL 缺少字段时按 `None` 读取，保持历史兼容。

完整链路：

```text
System / Tool Schema / Tool Choice
  -> canonical JSON
  -> prompt_sha256
  -> session.jsonl / LLMCall
  -> 按组件去重聚合
  -> prompt_bundle_sha256
  -> eval/runs/<run_id>.jsonl / RunRow
```

## 为什么 Git SHA 不够

Git SHA 仍然保留，但它解决的是代码版本，不是实际 LLM 指令身份：

- dirty worktree 中 Prompt 已变，Git SHA 仍指向旧 commit；
- 同一个 commit 可以临时切换模型或运行配置；
- 一个 commit 可能同时修改 Prompt、validator、检索和 UI；
- 生成后的 Tool Schema 不容易只靠 commit 快速还原和比较；
- eval 趋势需要直接按 Prompt 版本聚合，而不是逐个阅读代码 diff。

因此二者职责不同：

```text
git_sha：代码来源与整体复现
prompt_bundle_sha256：实际指令合同与质量归因
model：推理能力与成本归因
```

## 主要取舍

### 为什么使用内容 hash，而不是只用 `v1`、`v2`？

人工版本号方便沟通，但容易漏改。内容 hash 由实际请求自动生成，是权威身份。未来可以额外增加可读 revision，但不能替代 hash。

### 为什么不 hash 论文正文和用户问题？

如果包含动态输入，每篇论文都会得到不同版本，无法观察同一 Prompt 在多篇论文上的质量趋势。动态输入属于任务实例，不属于 Prompt 合同。

### 为什么 bundle 要包含 component name？

同一段 Prompt 被不同工具复用时，其职责和下游字段可能不同。只对 hash 集合聚合会丢失组件归属，降低排查价值。

### 为什么不引入 Prompt registry？

项目规模是单用户本地论文库，Prompt 与工具代码和 Schema 紧密耦合。当前只增加一个纯函数和观测字段，不引入远程 Prompt 平台、模板引擎或新依赖。

## 实现范围

- `shared/prompt_fingerprint.py`：稳定单调用指纹与组件 bundle 指纹；
- `session/types.py`、`session/store.py`：在 `LLMCall` 中持久化指纹；
- `agents/tool_validation.py`：结构化 worker 与 Schema retry；
- `agents/loop.py`：主 Agent 多轮 loop；
- `agents/paper_copilot.py`：Composer repair；
- `agents/read_paper_tool.py`：聚合一次论文读取的 Prompt bundle；
- `eval/suite.py`、`eval/runs.py`：把模型与 bundle 写入 eval 历史。

没有新增依赖，没有增加 LLM 调用，也没有改变 Schema retry、模型选择或生成行为。

## 简历表述

推荐版本：

> 构建 LLM Prompt 可追溯与回归归因机制，对 System Prompt、Tool Schema 和 Pydantic 字段指令生成内容指纹，并贯通 JSONL session 与 eval 趋势数据，支持按实际 Prompt 版本分析模型质量、成本、延迟和缓存变化。

精简版本：

> 设计内容寻址的 Prompt 版本追踪机制，将 Prompt/Schema 指纹贯通 LLM 调用日志与离线 eval，实现模型回归的版本级归因。

英文版本：

> Built a content-addressed prompt traceability pipeline that fingerprints system instructions, tool schemas, and tool choices, linking per-call JSONL traces with offline evaluation runs for version-level quality and cost attribution.

当前不要写：

> 通过 Prompt 版本管理显著提升模型质量。

目前实现的是可追溯和可归因，尚未产生真实质量提升数据。

## STAR 面试讲述

### Situation

项目已经有 eval 趋势、Git SHA 和 LLM 成本日志，但一次模型回归可能来自 System Prompt、Pydantic 字段描述、Tool Schema 或模型切换。只看 commit 无法快速定位实际指令合同。

### Task

在不增加依赖、不改变 LLM 行为，并兼容历史 JSONL 的条件下，让每次调用和每次 eval 都能回答“用了哪一版 Prompt”。

### Action

1. 将 System、完整 Tool Schema 和 Tool Choice 做 canonical JSON 序列化；
2. 使用 SHA-256 生成稳定、内容寻址的单调用指纹；
3. 在所有持久化 LLM 调用路径记录指纹；
4. 按组件去重聚合为一次运行的 Prompt bundle；
5. 将 model 与 bundle 写入 eval RunRow；
6. 新字段保持可选，使旧 session 和 eval 历史继续可读。

### Result

完成从实际请求到 session 再到 eval 的 Prompt 身份链路，不增加 LLM 调用或依赖。现在可以区分模型切换、Prompt/Schema 变更和普通代码版本；真实 Prompt 退化实验及趋势图切换标记仍待补充，因此不宣称质量提升比例。

## 高频追问

### `Field.description` 为什么也算 Prompt？

它会进入模型看到的 Tool Schema，直接指导字段生成。只 hash System Prompt 会漏掉项目中最重要的一类 Prompt 迭代。

### SHA-256 是为了安全吗？

主要目的不是密码学安全，而是稳定的内容寻址、低碰撞身份和跨运行比较。它也避免在 eval 每一行重复保存长 Prompt。

### 指纹能完全复现一次模型输出吗？

不能。输出还受模型服务版本、动态输入、采样和随机噪声影响。指纹标识的是稳定指令合同，需与 model、原始 session、Git SHA 和多次 eval 趋势一起使用。

### 为什么不把动态 user message 一起 hash？

动态消息标识任务实例，而不是 Prompt 版本。它们已经保存在 session 中；加入版本指纹会导致跨论文无法聚合。

### 下一步如何证明价值？

使用同一模型和 smoke suite：

1. 连续运行基线 Prompt，观察自然噪声；
2. 故意退化一个 System Prompt 或 `Field.description`；
3. 确认 bundle hash 改变；
4. 在趋势报告中标出版本切换点；
5. 验证质量断崖、成本或缓存变化能够关联到该版本。

## 尚未完成与不可宣称内容

- 趋势图尚未绘制 Prompt 版本切换标记；
- 尚未执行真实 Prompt 基线与退化版本对照实验；
- 尚未量化定位回归所节省的时间；
- 当前指纹刻意不覆盖动态消息中的应用指令模板；
- 本次实现后尚未运行 Ruff、mypy 或 pytest；
- 不能宣称模型质量、正确率或稳定性已经提升。
