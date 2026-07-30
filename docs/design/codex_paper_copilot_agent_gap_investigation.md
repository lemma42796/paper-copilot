# Codex CLI 与 Paper Copilot 同模型 Agent 差距根因研究

状态：只读根因分析已完成；固定 900 词上限、固定报告标题和模型可见的页面文本专用读取工具已删除，
尚未重跑模型验证
日期：2026-07-30
文档职责：定义根因研究的问题、证据、分层方法、停止条件和 Definition of Done；不在
本阶段设计或实施修复。

## 1. 研究问题

在相同 DeepSeek V4 Pro、相同 14 篇论文、相同连续四轮 Query 下：

| 系统 | Strict | Weighted | Coverage | 墙钟时间 |
|---|---:|---:|---:|---:|
| Codex CLI Agent | 74.6% | 81.0% | 90.1% | 约 538 秒 |
| Paper Copilot Agent | 57.7% | 72.5% | 90.1% | 约 537 秒 |

本研究解释 16.9 个百分点 strict 和 8.5 个百分点 weighted 差距在哪里首次出现、如何
传播到最终答案，以及哪些差异有源码和 trace 支持。工作评分未经独立复核，只能用于定位
候选问题，不能用于显著性或总体能力推断。

## 2. 固定输入

不产生新的模型运行。只使用：

- Codex CLI + DeepSeek V4 Pro 正式单次四轮原生 JSONL、rollout、配置和 adapter 记录；
- Paper Copilot conversation `conversation-20260729T141953-65092f325e` 的四个 job、
  session、payload 和 trace；
- Gold revision 2、冻结 Query、语料 manifest 和既有逐项工作评分；
- Codex 源码 `fe01054a28fa4bd04716d9ceadb410f2443a50ce`；
- Paper Copilot 源码 `e79f64e69d4cd2524c2cd23ebbe4caa92718a8cd`。

模型自报、最终答案中的工具清单和事后概括不能代替 payload、session 或 trace。

## 3. 分层对照

按以下顺序比较，避免先看到最终错误就反推单一原因：

| 层 | 需要回答的问题 | 权威证据 |
|---|---|---|
| 模型请求配置 | 模型标识、thinking 参数、流式协议和 provider payload 是否等价 | 实际请求 payload、adapter 记录 |
| 指令 | system/developer/Skill 内容、优先级和重复注入是否不同 | 模型可见请求、Codex/Paper Copilot 源码 |
| 上下文 | 历史轮次、工具结果、cache index、token 预算和裁剪方式是否不同 | 每次 LLM payload、session |
| 工具表面 | schema、命令能力、页面读取粒度、输出预算和错误反馈是否不同 | tool schema、trace、源码 |
| Agent loop | 工具选择、并行/串行、重复抑制、继续条件、停止和恢复是否不同 | lifecycle trace、loop 源码 |
| 综合输出 | 已获得证据如何被保留、引用、纠错并写入最终表 | 最终回答、前序 payload、Gold |

“Agent 系统”是上述各层的总称。只有排除其他层后，才能把问题进一步归因到狭义
`Agent loop`。

## 4. 错误反向追踪

先追踪三个已有高判别力事件：

1. **T02 UDA taxonomy**：两套系统何时首次读取或错过张耀斌 PDF 第 37–38 页，错误结论
   首次进入哪次模型上下文，后续是否得到纠正机会；
2. **T03 复核遗漏**：用户要求回查 P12/P13 后，计划、搜索、页读取和最终回答在哪一步
   丢失这两个对象；
3. **T04 单元格追溯**：模型已经获得哪些深页证据，这些证据在最终请求中是否仍可见，
   以及为什么没有形成逐单元格引用。

每个事件生成一条因果链：

```text
用户约束
→ 模型可见上下文
→ 工具选择
→ 工具结果
→ 下一轮上下文
→ 中间判断
→ 最终答案
```

在没有直接证据时标记 `undetermined`，不得用合理猜测填补。

## 5. 假设与判定标准

初始假设只用于组织证据，不预设结论：

- H1：Paper Copilot 的 system/Skill 指令降低了研究规划或复核优先级；
- H2：完整 `research_cache_index` 和长工具历史稀释了当前轮约束；
- H3：Paper Copilot 的工具 schema 或结果格式增加了模型协调负担；
- H4：Agent loop 的调用—反馈—继续语义没有充分支持迭代纠错；
- H5：上下文保留或 compaction 使关键证据在综合阶段不可见；
- H6：两套调用的 thinking/provider 参数并不真正等价，模型配置仍是混杂变量。

每个假设最终只能标为：

- `supported`：有模型可见输入、trace 与源码的相互支持；
- `weakened`：观察结果与假设不一致；
- `undetermined`：现有产物不足以裁决。

## 6. 输出与 Definition of Done

交付一份根因报告，包含：

- 两套系统逐层差异表；
- 三个错误事件的首个可观察分叉点和传播链；
- 假设的 `supported/weakened/undetermined` 状态及证据路径；
- 将“基础模型问题”“模型请求配置”“提示/上下文”“工具协议”和“Agent loop”分开；
- 最多三个按预期收益和验证成本排序的修复候选；
- 每个候选对应一个只改变单一变量的最小消融方案。

本 slice 在报告和消融方案完成时结束。未经用户另行确认，不实施修复、不运行消融、不
新增测试、不修改 Gold，也不删除旧实现。

## 7. 证据清单与可审计性限制

本次实际使用的冻结产物如下：

- Codex CLI + DeepSeek V4 Pro：
  `runs/ablation-a-codex-cli-deepseek-v4-pro/formal-single-2026-07-30/`
  下的四轮 JSONL、`native-rollout.jsonl`、`config.toml` 和 `run-metadata.txt`；
- Paper Copilot：conversation
  `conversation-20260729T141953-65092f325e` 的 T01、T02、T03、T04 job 分别为
  `job-20260729T141953-5cc6f588ba`、
  `job-20260729T142705-4320055097`、
  `job-20260729T143322-8005eeaac1` 和
  `job-20260729T143710-7bce601c65`；
- T03 前另有失败 job `job-20260729T143102-cac4827507`。它因
  `Server disconnected without sending a response` 失败；`chat/jobs.py` 只把
  completed job 纳入 conversation context，因此失败 job 的部分读取没有进入正式 T03；
- Gold revision 2 与逐项工作评分来自私有实验目录的 `gold/` 和
  `reports/codex-vs-paper-copilot-v4-pro-working-score-2026-07-30.md`。

Paper Copilot observability 使用 `local_safe_v1`，单 payload 最大 262144 bytes、字符串
预览最大 2000 字符；长消息数组以 `truncated_items` 截断。因此 trace 足以确认请求
配置、调用顺序、工具参数、页码和终态，但不足以逐字重建每一次完整模型请求。跨轮历史
由新 session 中持久化的 `recovery_base` 直接记录，可与固定提交源码相互核对。

## 8. 逐层差异

| 层 | Codex CLI + DeepSeek V4 Pro | Paper Copilot + DeepSeek V4 Pro | 判定 |
|---|---|---|---|
| 模型请求配置 | adapter 固定 `deepseek-v4-pro`、thinking enabled、reasoning effort `max`；上游非流式 | 直接 Chat Completions，`deepseek-v4-pro`、thinking enabled、reasoning effort `max`；上游流式 | 核心 thinking 配置一致；流式与 adapter 转换仍是未控制变量 |
| 指令 | Codex 通用 developer、权限和环境上下文；无论文专用输出字数上限 | Paper Copilot system + research Skill；要求页级证据，同时要求研究报告少于 900 词并使用固定报告结构 | T04 的逐单元格追溯与 900 词上限直接竞争 |
| 跨轮上下文 | 同一 Codex session 连续 T01–T04，保留用户消息、命令、工具输出和模型中间历史 | 每轮新建 session，但从上一成功 job 的 session 重建完整模型历史，再追加当前 Runtime、Skill、cache index 和请求 | 两者都保留模型可见工具历史；Paper Copilot 没有在轮次边界丢失原始页证据 |
| 当前轮上下文 | 命令输出直接作为 tool output 留在同一历史 | tool-result batch 后追加一条新的 `<runtime_context>` 用户消息；完整 `research_cache_index` 每个 job 重新注入 | Paper Copilot 有更多非研究状态文本和重复库存文本 |
| 工具表面 | shell 可直接用 Python/pdfplumber 批量读多篇、多页；一次调用可返回数万字符 | `library_exec` 用于搜索，`read_page` 每次只读一页；通用命令输出不得作为 citation-grade evidence | Paper Copilot 的证据取得需“搜索→定位→逐页读取”，协调步骤更多、单位调用证据带宽更低 |
| Agent loop | 原生命令调用与结果持续写入同一 conversation history | 同一 job 内正确执行 tool-use→result→continue，批量工具结果后更新 Runtime；默认不阻断 `end_turn` | 未发现 loop 丢调用、错配 call ID 或异常提前停止；差异主要不在狭义 dispatch loop |
| compaction/recovery | 四轮 rollout 未出现 compaction | 四个完成 job 的 `conversation_compaction` 均为空 | 已排除 compaction 触发导致的本次分差 |
| 综合输出 | T03 深读方法章节；T04 再读多篇结论/展望，输出 token 78147、reasoning 46959 | T03/T04 也读取部分深页，但输出 token 35949、reasoning 13363；T04 多数行仍以摘要页或行级页码汇总 | Codex 为复核与综合投入了更高的证据和推理带宽；token 口径不同，不作效率结论 |

### 8.1 源码支持

Paper Copilot 固定提交中：

- `chat/jobs.py::_build_conversation_context` 会定位上一 completed conversation job；
  `_run_job` 随后读取该 job 的 session，并调用
  `session/recovery.py::reconstruct_rollout` 重建完整模型历史；
- 新 session 的 `recovery_base` 持久化重建后的 history。T02、T03、T04 分别记录
  35、45、65 条恢复消息，包含 assistant tool use 与匹配的 user tool result；
- `agents/paper_copilot.py::_build_initial_messages` 将 Runtime、Skill、完整 cache
  index、conversation context 和当前请求合并为新的 user message；跨 job 路径则使用
  `_append_resume_turn`，在恢复历史后追加当前可信上下文和当前请求；
- `agents/loop.py::run_agent_loop` 在每个完整 tool-result batch 后追加最新
  `<runtime_context>`，然后继续模型循环；
- `read_page` 的 schema 固定为一个完整 SHA-256 加一个正整数页码；
- system prompt 同时要求“每个具体研究 claim 精确页码”与“研究报告少于 900 词”。

Codex 固定提交中，`session/mod.rs::record_conversation_items` 将 conversation item
追加到模型历史和 rollout；本次 native rollout 也实际保存了跨轮命令及
`function_call_output`。Paper Copilot 采用不同的 job/session 生命周期，但通过
`reconstruct_rollout` 和 `recovery_base` 达到相同的模型历史保留效果。跨轮工具历史
丢失因此被排除为本次根因。

## 9. 三个错误事件的因果链

### 9.1 T02 UDA taxonomy

两套系统都把张耀斌判为完全无监督，都没有在 T02 读取 Gold 依据的 PDF 第 37–38 页：

- Codex T02 的唯一命令批量读取五篇论文前 8 页；
- Paper Copilot T02 搜索全库后，仅对张耀斌读取 PDF 第 2 页；T01 曾读取其第 4 页
  摘要；
- 两边均由标题、摘要和“无监督”表述推出“无有标签源域”，随后高置信排除 UDA。

首个可观察分叉点不是两系统之间的分叉，而是两者共同的证据规划缺口：

```text
用户要求区分 UDA
→ 搜索/摘要显示“无监督”
→ 未定位并读取训练设定深页
→ 从缺少有标签源域的显式证据推断“完全无监督”
→ T04 沿用错误 taxonomy
```

因此 C044 的两次 incorrect 不能解释系统间 16.9/8.5 个百分点差距；它是共同失败。

### 9.2 T03 复核遗漏

工作评分要求复核张耀斌、刘章平及上一轮纳入的三篇问题论文。两套最终回答都遗漏前两
篇，因此相关 7 个 required occurrence 均为 missing。

Paper Copilot 的成功 T03 实际读取了刘章平第 7–8 页、张耀斌第 5、7、10 页，说明失败
发生在“已获得证据→最终复核清单”之间，而不是未调用工具。失败的 T03 job 还读取了
两篇第 4 页，但该 job 未进入 completed conversation context。Codex T03 则没有再次
读取这两篇。两边最终都把“上一轮纳入的结论”收窄为模态缺失/遮挡的三篇，而未把前半段
无监督 taxonomy 当作待复核项。

首个共同分叉点是复核范围解释：

```text
T02 同时产生无监督分类与问题论文筛选
→ T03 “上一轮纳入的结论”存在指代范围
→ 两边规划都只输出后三篇
→ Paper Copilot 即使读到前两篇，也未将其加入最终 checklist
```

这同样主要是共同失败，不能单独解释系统间分差；但 Paper Copilot 暴露了“工具读取不
等于综合阶段使用”的问题。

### 9.3 T04 单元格可追溯

两套系统都未满足逐关键单元格追溯，因此不存在“Codex 完全成功、Paper Copilot 完全
失败”的二元分叉。差异是正确 claim 的深度：

- Codex T03 用 10 个命令深读何子玲、张兴帅和项莘泽的方法章节，单轮命令输出约
  9 万字符；T04 再用 3 个命令检查 10 篇论文的结论、展望和局限；
- Paper Copilot T03 读取 19 页，重点仍在四篇边界论文和项莘泽；T04 用搜索加 7 次
  `read_page`，只对少数论文读取结论附近页面；
- Paper Copilot T04 的 `recovery_base` 包含 T01–T03 的模型可见工具调用和结果；
  Codex T04 也仍处于保存这些 tool output 的同一 session；
- Paper Copilot 最终表大量关键字段共用每行一个摘要页，且明确列出多个“基于摘要
  推断”的位置；Codex 虽同样未逐格绑定，更多方法限定得到深页支持，因此 partial
  occurrence 更少。

首个系统间分叉在 T03 的深证据规划处已经出现，并在 T04 放大：

```text
T03 深页复核
→ Codex 批量读取并跨轮保留原始输出
→ Paper Copilot 较少深读，但同样跨轮保留其模型可见工具输出
→ T04 Codex 可复用前轮证据并补读结论页
→ Paper Copilot 在 900 词导向下补搜少量页面并压成行级汇总引用
→ 更多关键机制只能判 partial
```

## 10. 假设判定

| 假设 | 状态 | 依据 |
|---|---|---|
| H1：Paper Copilot 指令降低规划/复核优先级 | `supported`（部分） | 页级证据指令本身正确，但固定报告结构和 900 词上限与 T04 高密度逐格证据冲突；不能证明这是唯一原因 |
| H2：cache index 和长历史稀释当前约束 | `supported`（部分） | 完整 cache index 每 job 重注入、每工具轮次注入 Runtime；但本次没有达到 compaction 门槛，无法量化其质量影响 |
| H3：工具 schema/结果格式增加协调负担 | `supported` | 单页 `read_page` 与 citation-grade 二阶段合同要求更多规划和调用；运行中 Paper Copilot 用 57 次逐页读取仍获得较少深章节覆盖 |
| H4：狭义 loop 的反馈/继续语义不足 | `weakened` | 75 次公开工具调用均完成，call/result 正常反馈，四轮正常 `end_turn`；未观察 dispatch 丢失或异常终止 |
| H5：上下文保留或 compaction 丢关键证据 | `weakened` | `recovery_base` 证明跨 job 保留完整模型历史；两边本次都未触发 compaction |
| H6：模型请求参数不等价 | `undetermined` | 模型、thinking 和 max effort 对齐；Codex 经 Responses→Chat adapter 且上游非流式，Paper Copilot 直接流式，仍有未控制协议差异 |

## 11. 按证据强度排序的根因

1. **高强度：证据获取表面的单位带宽与协调成本不同。** Codex 可一次批量读取多篇多页；
   Paper Copilot 必须先搜索再逐页绑定，实际深页覆盖显著更少。该差异解释“coverage
   相同但 partial 更多”比“狭义 loop 提前停止”更符合证据。
2. **中强度：输出合同内部竞争。** 冻结运行时的“少于 900 词”与 11 篇、10 个关键
   字段、逐格可追溯同时存在，强迫模型在完整性、紧凑度和引用密度间取舍。该固定上限
   已删除，但尚未重跑模型，不能量化其历史贡献。

已排除或显著削弱：

- 基础模型不同：主对照使用同一 `deepseek-v4-pro`；
- 墙钟时间不足：两边都约 538 秒；
- 工具失败或 stop hook 拦截：正式四轮工具调用均成功，均正常 `end_turn`；
- 跨轮工具历史丢失：Paper Copilot 的 `recovery_base` 保留完整模型历史；
- 本次 compaction：两边都没有触发；
- UDA 与 T03 missing 是 Paper Copilot 独有问题：两边都失败。

## 12. 最小消融建议

未经用户确认不执行。按预期信息增益与改动范围排序：

1. **输出合同消融。** system prompt 的固定 900 词上限和固定报告标题已经删除；
   Prompt 与 Skill 改为优先用户指定输出形态、按请求字段维护工作清单，并在安全且相关
   的读取仍可补全关键结论时继续调查。若获确认，只重跑 T04，统计逐关键单元格证据
   绑定率与答案长度；不同时修改工具或上下文。
2. **Codex 式文本读取表面消融。** 已删除模型可见的 `read_page`/`read_pages`，改为
   仅由 `library_exec` 批量搜索和读取带 PDF 页边界的缓存文本；实际命令输出随完整会话
   历史保留，不另设文本页面登记或最终引用校验。尚未运行工具协议验证或重跑 T03/T04，
   因此不能判断深页覆盖和 correct/partial 是否改善。

两个实验都必须使用全新隔离会话、同一 Gold revision 2，并分别只改变一个变量。由于
当前结果是单次工作评分，任何一次改善仍只能作为机制证据，不能宣称统计显著。

## 13. 后续工程 Slice E1：Conversation-owned Session

用户已在根因研究完成后确认开始工程改造。E1 只消除 conversation/session 生命周期
差异，不与 Prompt、工具、World State、Exec、provider 协议或 Skill 生命周期改造混合。
第 8–12 节描述的是固定基线 `e79f64e...` 的历史事实，不因本节实现而回写。

固定 Codex 源码依据：

- `core/src/session/mod.rs::record_conversation_items` 在同一 `Session` 中同时追加模型
  history、持久 rollout 和 raw item 事件；
- `core/src/session/turn.rs::run_hooks_and_record_inputs` 将真实用户输入直接记录到该
  session；
- `core/src/session/turn_context.rs::TurnContext` 将单 turn 配置与长生命周期 history
  分离；
- `core/src/tasks/regular.rs` 让一次 task/turn 在相同 session 上执行，attempt/retry
  不产生新的 conversation；
- `core/src/context/turn_aborted.rs` 以模型可见追加标记表达中断，不改写既有历史。

Paper Copilot 的领域适配：

```text
conversation_id
└── papers/<conversation_id>/session.jsonl
    ├── turn_started(job T01, attempt 1)
    ├── T01 conversation items
    ├── turn_completed
    ├── turn_started(job T02, attempt 1)
    └── ...

job
└── attempts/<n>/ observability bundle
```

- job 仍负责排队、审批、中断、客户端事件和最终结果，但不再拥有模型 session；
- 同一 conversation 同时只运行一个 turn，保证 append-only 顺序；
- completed turn 和当前重试 turn 进入恢复 history；其他 aborted/incomplete turn 保留
  在 session 中但不进入新的不同 turn；
- 同一 job resume 使用相同 turn ID 和 session，只创建新的 attempt trace；
- 旧 `paper-copilot-<job>-attempt-<n>` session 保持不变。首次继续旧 conversation
  时，新 conversation session 在 turn 边界之前追加一个 `recovery_base`，后续不再复制
  完整 history；
- research quality 从共享 session 按 turn 读取 FinalOutput、LLMCall 和页面证据，避免
  把前轮计数累计到当前 run。

这里有一个用户已确认的产品域差异：Codex 可把 interrupted marker 和部分历史继续暴露
给后续 turn；Paper Copilot 对“另起的新 job/turn”排除从未完成的旧 turn，避免失败研究
污染新请求，但对同一 job 的 resume 保留其部分历史和 aborted tool result。

E1 不改变：

- PDF 授权根、Seatbelt、网络和写入策略；
- `library_exec` / `inspect_page` / `library_edit` 工具协议；
- Prompt、`research-papers` v10、cache index 和页码引用格式；
- Chat Completions provider、模型、token 预算和 compaction 算法。

## 14. 后续工程 Slice E2：World State 与 Context Engine

E2 只消除重复 Runtime 文本与不可恢复 baseline 的上下文差异，不改工具执行器、工具
协议、provider wire 或按需 Skill 生命周期。

固定 Codex 源码依据：

- `core/src/context/world_state/mod.rs::WorldState` 以稳定 section ID 生成 snapshot，
  `WorldStateSnapshot::merge_patch_from` 使用 RFC 7386 patch；
- `core/src/session/world_state.rs::build_world_state_for_step` 从同一个 step view 构造
  模型可见状态；
- `core/src/session/mod.rs::record_step_world_state_if_changed` 从同一对 snapshot 同时
  生成模型 diff 与持久 patch；
- `record_context_updates_and_set_reference_context_item` 在缺少 reference baseline 时
  注入 full，steady-state 只注入 diff；
- `replace_compacted_history` 在新 context window 后持久化 full baseline。

Paper Copilot 领域适配：

- `agents/context/world_state.py` 实现 root-object snapshot、RFC 7386 create/apply、
  full/patch render 和 session baseline reconstruction；
- section 为 authorization、paper library、cache inventory、model、budgets、tools、
  skill catalog，以及仅在启用时出现的 Composer state；
- `world_state` 作为 append-only session entry 持久化 `mode/state/rendered`，恢复 history
  使用当时实际给模型的 rendered fragment；
- 首次进入旧 session 若没有 world-state baseline，追加 full；之后只有真实变化才追加
  patch；
- 每次工具 batch 不再重复完整 Runtime 文本。已用费用不进入动态 patch，预算、deadline
  和权限仍由 Runtime 强制；
- compaction replacement history 注入 full，并在 compaction entry 后追加新的 full
  baseline；该持久 full 标记为非重复模型项，因为 replacement history 已含同一
  fragment。

E2 不改变：

- `library_exec`、`inspect_page`、`library_edit` 的 schema、dispatch、sandbox 或输出；
- Chat Completions provider、模型和 token 阈值；
- research Skill 的自动加载策略；本 slice 只把其当前 metadata/body 纳入 World State，
  按需 catalog/load 留给后续 Skill lifecycle slice；
- PDF 引用链接和 macOS 授权校验。

## 15. 后续工程 Slice E3：Unified Library Environment

E3 将 `library_exec` 从 call-local 临时目录改为 conversation 级持久执行环境，并增加
Codex 式 process store、yield 和 stdin/poll 工具。

固定 Codex 源码依据：

- `tools/handlers/unified_exec/exec_command.rs` 负责模型参数、环境选择和 process ID；
- `unified_exec/process_manager.rs::exec_command` 在初始 yield 前保存存活进程，并返回
  chunk ID、可选 process ID 与 exit code；
- `process_manager.rs::write_stdin` 对同一 process 串行交互、drain 增量输出并在退出后
  移除；
- `tools/handlers/unified_exec/write_stdin.rs` 把空输入作为 poll，非空输入作为原进程
  transport。

领域适配：

- session 目录下的 `library-environment/` 保存 fixed workspace 与 persistent scratch；
- `library/`、`cache/` 和受控命令仍由同一 Seatbelt profile 限制，无网络和权限升级；
- Python `subprocess.Popen` 加 reader thread 使 process store 不绑定单个 asyncio loop，
  因而可跨 chat attempt/turn 使用；
- 模型新增 `library_write_stdin`；completed 和 yielded 调用共享
  `output/exit_code/wall_time_seconds/session_id/chunk_id` 输出；
- Agent 取消和 conversation 删除终止环境内全部 process group。

E3 不包含 PTY、任意 shell/workdir、受控 Python、provider Responses 或 Skill 按需加载。

## 16. 工程 Slice E4–E7 实施与边界记录

以下四个 slice 已按用户授权顺序实施，均以固定 Codex 源码
`fe01054a28fa4bd04716d9ceadb410f2443a50ce` 为结构真源；尚未运行测试、真实 provider
smoke 或模型评测。

### E4 Controlled Python

- 参考 unified exec 的单一 runtime/sandbox 路径，不建立 Python 旁路；
- Paper Copilot 将当前解释器注册为固定命令，沿用 LibraryEnvironment process store；
- Seatbelt 只增加标准库读取，并显式拒绝 purelib/platlib；`PYTHONNOUSERSITE` 与
  `PYTHONDONTWRITEBYTECODE` 固定开启；
- library/cache 只读、scratch 可写、网络拒绝和输出上限保持不变。

### E5 Tool Registry

- 参考 `core/src/tools/registry.rs` 与
  `core/src/tools/spec_plan.rs::build_model_visible_specs_and_registry`；
- `RegisteredTool` 同时拥有 definition、handler 与 exposure predicate；
- 同一 registry 生成模型 schema、解析调用并执行，隐藏旧工具无法绕过公开表面；
- exposure 由 PDF library、持久执行环境和模型 input modality 决定。

### E6 Provider 路径：不实施

- Codex CLI 原生只走 Responses，实验 adapter 的职责是把 Codex 请求转换为 DeepSeek
  Chat Completions；
- Paper Copilot 已原生调用 DeepSeek Chat Completions，不需要反向增加 Responses
  transport；
- 2026-07-30 的最小 smoke 也确认直连 provider 的 `/responses` 返回 HTTP 404；
- PC 侧曾加入的 Responses payload/SSE、wire selector 和 provider-item session
  持久化已全部清理。H6 若需复核，只在隔离实验 harness 中控制 adapter 差异。

### E7 Skill Registry / On-demand Loading

- 参考 `core-skills/src/loader.rs`、`core-skills/src/injection.rs` 与 Skill metadata；
- World State 只发布可信 catalog metadata，不再在每个新 job 自动注入正文；
- `load_skill` 首次返回 conversation 固定版本正文，同时追加
  `agent.skill.loaded` lifecycle event；相同版本后续只返回 metadata；
- compaction replacement history 保留已加载 Skill fragment，但不制造第二次加载；
- Skill 不扩大 registry、sandbox、网络、路径、安装或写入授权。
