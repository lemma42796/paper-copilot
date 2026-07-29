# Codex × DeepSeek 模型、Agent 与工具表面消融实验计划

状态：实验范围已确认；本地 adapter 已实现并通过离线测试，尚未接入真实 Key

日期：2026-07-30

性质：`multi-thesis-v1` 四轮盲测的后续因果消融，不修改原冻结实验

## 1. 目的

现有结果同时改变了模型、Agent loop 和工具表面：

- Codex CLI 使用 `gpt-5.6-sol` 与 Codex 自身工具；
- Paper Copilot 使用 DeepSeek V4 Pro 与项目内部 Agent 工具。

因此，现有差距不能单独归因为“模型问题”或“Agent 设计问题”。本计划通过受控对照回答：

1. 在尽量保持 Codex Agent、提示与原始 PDF 工具不变时，仅把模型换为
   DeepSeek V4 Pro，质量是否显著下降？
2. 在保持 Codex Agent 与 `gpt-5.6-sol` 不变时，改用 Paper Copilot MCP
   暴露的本地论文能力，质量是否仍能保持？

本实验不预设结论。“证明是模型的问题”在这里改写为可证伪命题：

> 若 DeepSeek V4 Pro 在 Codex Agent 下仍显著落后于 `gpt-5.6-sol`，且
> `gpt-5.6-sol` 通过 Paper Copilot MCP 仍能取得较高质量，则证据支持
> “模型能力可能是主要差异来源，Paper Copilot 的 MCP/Python Core 能够支持该任务”。

该结论仍仅适用于冻结语料与四轮任务，不能推广为模型的普遍能力证明。

## 2. 既有参照结果

以下仅作为待复核的工作参照，不在本计划中冻结为正式结论：

| 参照 | 模型与执行系统 | Strict | Weighted | Coverage |
| --- | --- | ---: | ---: | ---: |
| R0 | Codex CLI + `gpt-5.6-sol` + Codex 原始 PDF 工具 | 76.1% | 83.1% | 90.1% |
| R1 | Paper Copilot 内部 Agent + DeepSeek V4 Pro | 57.7% | 72.5% | 90.1% |
| R2 | Paper Copilot 内部 Agent + DeepSeek V4 Flash | 57.7% | 66.2% | 76.1% |

新实验沿用 Gold revision 2 的 71 个 required claim occurrence 和既有评分口径。
所有既有分数在最终报告中继续标记为“独立工作评分，尚未冻结”。

## 3. 因果边界

### 3.1 可以检验的命题

- A 组近似检验“在 Codex Agent 下更换模型”的效果。
- B 组检验 Codex Desktop 与 `gpt-5.6-sol` 能否通过 Paper Copilot MCP 完成任务。
- B 若表现良好，可以说明 Paper Copilot 的 MCP、索引、证据引用和 Python Core
  足以支持该任务。

### 3.2 不能直接声称的结论

`Codex Desktop + gpt-5.6-sol + Paper Copilot MCP` 使用的是 Codex Agent，
绕过了 Paper Copilot 内部的 planner、预算、历史压缩和工具选择 loop。因此 B
**不能单独证明 Paper Copilot 内部 Agent 设计没有问题**。

本计划不设置 Paper Copilot 内部 Agent 的模型消融，因此最终报告不得把 B 的结果
表述为对内部 Agent loop 的直接因果结论。

### 3.3 本地协议 adapter 的混杂因素

A 组需要一个本地 adapter，把 Codex Responses 请求转换为 DeepSeek Chat
Completions。它不是绝对的“只换模型”：adapter 对 typed SSE、reasoning、工具调用
和多轮累计输入的转换也是变量。必须先通过第 7 节兼容性门槛；正式报告仍需把
adapter 源码摘要、版本和转换风险列为限制。

不使用第三方 `codex-bridge`。实验采用为本任务编写的无第三方依赖、单用途 adapter，
源码位于私有 eval 目录：

```text
multi-thesis-v1/harness/codex-deepseek-adapter/
```

它不是 Paper Copilot 产品组件，也不进入产品运行时或公开包。

## 4. 冻结输入与共同约束

所有新运行必须继续使用：

- `multi-thesis-v1` 的同一批 14 份 PDF、相同文件 SHA-256 与 1169 页计数；
- `queries.md` 中 T01–T04 的原文与顺序；
- Gold revision 2 的 `papers.yaml`、`turns.yaml`、`claims.yaml`、
  `evidence.yaml` 与 adjudication；
- 四轮连续会话语义：T02–T04 必须继承上一轮的最终论文集合与持续排除；
- 不向被测 Agent 暴露 Gold、评分报告、其他系统答案或人工质检结论；
- 不在轮间给予纠错、补充提示或结果导向反馈；
- 除模型端点外禁用联网搜索、浏览器、Apps、插件和子 Agent；
- 每条 lane 使用全新会话，并保存失败 attempt，不覆盖历史。

任何 corpus、query、Gold 或执行规则变化都会创建新版本，不得继续使用
`multi-thesis-v1` 的可比性标签。

## 5. 实验矩阵

| Lane | 执行表面 | Agent loop | 模型 | 论文工具/数据表面 | 作用 |
| --- | --- | --- | --- | --- | --- |
| R0 | Codex CLI | Codex | `gpt-5.6-sol` | 原始 PDF / Codex 工具 | 既有模型基线 |
| R1 | Paper Copilot | Paper Copilot | DeepSeek V4 Pro | 内部四工具 | 既有系统基线 |
| A | Codex CLI | Codex | DeepSeek V4 Pro | 与 R0 相同的原始 PDF / Codex 工具 | 近似模型消融 |
| B | Codex Desktop | Codex | `gpt-5.6-sol` | 仅 Paper Copilot MCP 论文工具 | MCP/Python Core 能力验证 |

R0 与 B 同时改变执行表面和工具表面，因此二者只能作描述性并列，不能把分数差异
严格归因于 Paper Copilot MCP。

## 6. 分阶段执行

### Phase 0：文档确认（已完成）

- 只确认本计划；
- 不安装第三方代码；
- 不修改 Codex、Paper Copilot 或用户级配置；
- 不运行模型实验。

### Phase 1：adapter 固定与无评分验证（进行中）

已完成：

- 对照 Codex CLI 0.146.0 源码和 DeepSeek 官方 API 设计最小转换面；
- 使用 Python 3.12 标准库实现 adapter，没有引入第三方依赖；
- 固定上游为 `https://api.deepseek.com/chat/completions`，模型为
  `deepseek-v4-pro`，只允许 loopback 监听；
- 支持文本、Responses function tools、tool result、并行 tool call、
  DeepSeek `reasoning_content` 的内存续接，以及 Codex typed SSE 终态；
- 模型 profile 固定为 text-only、`shell_command`、direct tool mode，
  不暴露 freeform apply-patch、web search、custom tool 或 hosted tool；
- 未知 Responses 字段和不支持的工具类型 fail closed；
- 离线语法检查和 6 项转换测试通过；
- 未读取、迁移或写入真实 DeepSeek Key，未运行模型请求。

待完成：

- 配置独立 Codex provider/profile 和进程级凭据；
- 完成第 7 节无评分兼容性 smoke；
- 固定 adapter 源码 SHA-256 和运行配置摘要。

smoke 输入不得使用四个正式 query，不计入分数。

### Phase 2：A 组

- 使用独立 Codex profile/config，避免覆盖默认 OpenAI 配置；
- 在与 R0 相同的仓库快照、PDF 可见范围、初始提示和工具权限下运行；
- 除必要的本地 adapter 外，不启用 Paper Copilot MCP；
- 连续运行 T01–T04，保存 Codex 权威 rollout、adapter 元数据和所有失败 attempt。

### Phase 3：B 组

- 在同一 Codex Desktop build、同一 `gpt-5.6-sol` 版本与推理档位下运行；
- B 只允许以下只读 MCP 工具：
  `library_status`、`list_papers`、`search_papers`、`get_paper`、
  `inspect_evidence`、`compare_papers`；
- B 禁用 `start_read_paper`、`get_job_status`、`get_job_result`、
  `cancel_job`，避免再嵌套一个 Paper Copilot 模型 Agent 或写入索引状态；
- B 不允许再直接读取原始 PDF；
- 以全新 Codex task 连续运行 T01–T04。

### Phase 4：独立评分

- 隐去 lane 名称并按随机编号交给评分者；
- 评分者只看 Gold revision 2、最终回答和必要的权威 trace；
- 先完成 claim occurrence 评分，再解盲比较；
- 输出工作评分报告，不修改 Gold 和既有报告。

## 7. 本地 adapter 验证门槛

正式运行前必须全部通过：

1. 使用明确记录的 Python 3.12 解释器，adapter 仅绑定 `127.0.0.1` 或 `::1`。
2. DeepSeek Key 只进入进程环境或安全凭据存储，不写入仓库、Codex task、
   session、trace、命令历史或评分报告。
3. Codex 使用独立 provider/profile，明确记录：
   - Codex CLI 版本与 commit/build；
   - adapter 文件 SHA-256；
   - provider `base_url`；
   - `wire_api = "responses"`；
   - DeepSeek 精确模型 ID；
   - reasoning 配置和所有非默认参数。
4. 以下无评分 smoke 均成功：
   - 单轮纯文本；
   - streaming 文本；
   - 单次工具调用及 tool-result 回传；
   - 连续多次工具调用；
   - 并行工具调用（若正式 Codex 配置可能发出）；
   - reasoning 内容不会被错误注入用户可见回答；
   - `previous_response_id` 或等价多轮延续；
   - usage/token 字段可解释；
   - endpoint 中断能够形成显式失败，而非成功形状的截断回答。
5. adapter 不得静默删除未知 Responses 字段。发现不支持字段时必须失败，不做隐式降级。
6. adapter 日志只保留时间、状态码、事件种类、token/usage 和有界错误，
   不记录完整 prompt、PDF 内容、工具结果或 API Key。

任何一项失败都停止 A 组，不用正式 query 调试适配器。

## 8. Paper Copilot MCP 验证门槛

B 组运行前必须以只读方式确认：

- 启动命令固定为：

  ```bash
  uv --directory /absolute/path/to/paper-copilot run paper-copilot-mcp
  ```

- 仓库 commit、Python/uv 版本与依赖锁文件已记录；
- `PAPER_COPILOT_HOME`、`PAPER_COPILOT_PDF_DIR` 指向冻结实验副本；
- `library_status` 返回只读状态，且 PDF 数、索引论文数、chunk 数与冻结清单匹配；
- 14 个 paper ID 能映射到同一 PDF SHA-256；
- 索引构建时间早于实验，运行中不得重建或更新；
- 明确固定检索模式为 lexical 或 hybrid；若 hybrid 会向 embedding provider
  发送 query，必须记录并在所有 B 组重复中保持一致；
- 每个关键 claim 能通过 `inspect_evidence` 回溯到 paper、section 与 page；
- MCP tool schema 和有界输出没有在重复间变化；
- Codex task 的权威 trace 能导出 tool name、arguments、result/error、终态、
  token、费用和耗时。无法取得这些字段时，B 只能记为 pilot，不进入正式比较。

MCP 索引是预处理后的结构化数据，不等同于原始 PDF。B 因此衡量的是整个
“Paper Copilot MCP + 已冻结索引/证据表面”，不能把结果归因到单一函数。

## 9. 重复、失败与预算

### 9.1 两阶段重复策略

- 每个新 lane 先做 1 次不计分的端到端 pilot，确认 trace 与协议完整；
- 正式阶段每个 lane 做 3 次独立重复；
- 每次重复均是四轮连续会话，随机化 lane 的执行顺序；
- 不因结果不好而选择性重跑。

单次结果可与既有工作评分并列展示，但“主要原因”的结论以三次重复的分布为依据。

### 9.2 失败规则

- 网络、adapter、模型 endpoint、MCP 或 host 中断均保留为失败 attempt；
- 失败后可按预注册规则从全新四轮会话重跑，不从中途答案人工续接；
- 所有失败的 token、费用和耗时计入系统成本；
- 若供应商没有返回失败请求的 usage，标记“成本下界”，不得填零；
- protocol failure 与模型内容错误分开统计。

### 9.3 预算

- 同一对照中的上下文、工具调用和输出上限尽量一致；
- 不通过显著提高某一 lane 的预算来补偿模型差异；
- 若供应商或产品不能设置完全相同的 reasoning budget，记录实际参数并列为限制；
- 不以模型自报 token、费用或耗时为权威依据，只使用 host、trace 与供应商可核验数据。

## 10. 评分与协议审计

每次正式四轮运行分别计算：

- strict correctness；
- weighted correctness；
- claim coverage；
- correct / partial / wrong / omitted 的 claim occurrence 数量；
- 错误、部分正确、遗漏 claim ID 与简短理由。

同时审计：

- T01 最终论文集合是否精确；
- T02–T04 是否持续排除不合格论文；
- 引用和页码是否可回溯到权威 evidence；
- 每个关键表格单元格是否包含独立证据；
- 是否把模型推断写成论文事实；
- 是否出现集合漂移、跨轮遗忘或错误继承；
- 工具调用数、失败数、终态、输入/缓存/输出 token、费用和墙钟耗时；
- 所有失败 attempt 是否计入成本。

评分结构与 `codex-vs-paper-copilot-working-score-2026-07-29.md` 对齐，但不得复制其中
对任何新 lane 的主观判断。

## 11. 预注册判定规则

“显著”在本实验中定义为：

- 三次重复的 weighted correctness 中位数相差至少 5 个百分点；且
- 优势方向在至少 2/3 次重复中一致；且
- 没有用新增 critical protocol failure 换取表面分数。

判读如下：

| 观察 | 支持的解释 | 仍不能说明 |
| --- | --- | --- |
| A 接近 R1，且显著低于 R0 | DeepSeek 模型能力是主要差异来源 | adapter 完全无影响 |
| A 接近 R0，显著高于 R1 | Paper Copilot 内部 Agent/工具/上下文设计可能是主要来源 | 具体是哪一个内部组件 |
| B 取得接近 R0 的高质量结果 | Paper Copilot MCP/Python Core 能够支持 Codex 完成任务 | 内部 Agent loop 没有问题 |
| B 显著低于 R0 | MCP、索引或 Desktop 执行表面可能存在瓶颈 | 具体是哪一个变量 |
| A 低于 R0，且 B 质量较高 | 共同支持“模型差异可能是主要来源” | 对内部 Agent 设计的直接排除 |

若结果处于阈值内或重复方向不一致，结论必须写为“不确定”，不能选择性使用单次最好结果。

## 12. 预期产物

经用户批准执行后，建议把新产物写到私有 eval 目录，不写入公开仓库：

```text
multi-thesis-v1/
  runs/
    ablation-a-codex-cli-deepseek-v4-pro/
    ablation-b-codex-desktop-sol-paper-mcp/
  reports/
    model-agent-tool-ablation-working-score-YYYY-MM-DD.md
```

每个 run 至少保存：

- 精确输入 query；
- 模型、host、adapter/MCP、仓库版本和配置摘要；
- 权威 session/rollout/trace；
- 最终回答；
- attempt 终态；
- token、费用、耗时；
- corpus manifest 与 SHA-256；
- 去标识化评分表。

API Key、完整环境变量和用户级配置文件不得复制到产物中。

## 13. Definition of Done

本后续实验只有在以下条件全部满足时才可对外给出工作结论：

- A、B 的兼容性门槛通过；
- 每个正式 lane 完成三次四轮连续运行，失败 attempt 全部保留；
- corpus、query、Gold revision 和工具权限没有漂移；
- 独立评分在解盲前完成；
- trace 成本统计包含失败 attempt，未知成本明确标为下界；
- 报告严格区分“模型”“Codex Agent”“Paper Copilot MCP/Python Core”
  与“Paper Copilot 内部 Agent loop”；
- 不声称已直接证明 Paper Copilot 内部 Agent 设计无问题；
- 所有新结果标记为“独立工作评分，尚未冻结为正式结果”。

## 14. 当前停止点

实验范围已确认，本地 adapter 已实现且离线测试通过。当前停止在真实凭据接入之前。
下一步按顺序执行：

1. 生成独立的 adapter 入站 bearer token；
2. 经用户授权，仅以进程环境变量向 adapter 提供已轮换的 DeepSeek Key；
3. 写入隔离的 Codex provider/profile，不覆盖默认 OpenAI 配置；
4. 使用非正式 query 完成第 7 节 smoke，并保存权威 trace；
5. smoke 全部通过后，再单独确认 A 组正式三次重复的成本并开始实验。

在第 7 节全部通过前，不使用 T01–T04 调试 adapter，不开始计分运行。
