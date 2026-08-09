# DeepSeek V4 Flash 与 Codex/Paper Copilot 实验记录

状态：单次 T01 诊断与 Query-aligned 匿名盲评已完成；不作统计显著性结论
日期：2026-08-01 至 2026-08-04
语料：`multi-thesis-v1`，14 篇论文  
模型：`deepseek-v4-flash`，reasoning effort `max`

## 目的与证据口径

这组实验用于拆分以下因素对工具调用、token、质量和可靠性的影响：

- Codex 原生基础指令与最小基础指令；
- DeepSeek Responses API 与 Responses-to-Chat adapter；
- Codex 通用 `exec_command` 与 Paper Copilot `library_exec`；
- 原始 PDF 与 `papers/*.layout.txt` 缓存；
- research Skill 缺席与 Skill v16 指令存在；
- Codex Runtime 与 Paper Copilot Runtime。

运行状态、工具调用和 token 以持久 native rollout、session、trace、result 和
`run_metadata.json` 为准。失败尝试保留用于协议可靠性与成本审计，但不进入回答质量
分母。除 B/C 外均为描述性单次运行；跨行同时改变多个变量时不作单变量因果推断。

## 完成运行总表

| 运行 | 协议、工具与输入 | 工具调用 | total tokens | 耗时 | 旧 claim-detail 工作评分 |
|---|---|---:|---:|---:|---|
| Paper Copilot 历史 T01 repeat（未纳入新盲评） | 生产 Chat 路径；Skill v16；`library_exec`；`layout.txt` | 5 | 82,660 | 68.6 s | 11 C / 3 P；strict 78.6%，weighted 89.3% |
| Paper Copilot 新盲评候选 | 同一组合；2026-08-03 独立复跑 | 8 | 184,240 | 106.1 s | 11 C / 3 P；无逐项 scorecard |
| Codex Chat adapter v2 | Responses-to-Chat；通用命令；原始 PDF | 45 | 847,516 | 196.7 s | 未评分 |
| Codex 原生基础指令 T01 | DeepSeek Responses；通用命令；原始 PDF | 30 | 505,315 | 188 s | 未评分 |
| Codex 最小基础指令 T01 | DeepSeek Responses；通用命令；原始 PDF | 27 | 617,228 | 172.7 s | 未评分 |
| B：Codex library/no Skill | DeepSeek Responses；`library_exec`；`layout.txt` | 67 | 3,022,640 | 308 s | 6 C / 8 P；strict 42.9%，weighted 71.4% |
| C：Codex library/Skill v16 | 与 B 相同，只增加冻结 Skill developer instruction | 26 | 675,679 | 279 s | 8 C / 6 P；strict 57.1%，weighted 78.6% |
| D：Codex 原生动态 Skill | DeepSeek Responses；`exec_command`；原始 PDF；Codex 适配 Skill v16 | 34 | 1,147,975 | 263.3 s | 8 C / 6 P；strict 57.1%，weighted 78.6% |
| E：Codex + PC 式动态 Skill | DeepSeek Responses；`load_skill`；`library_exec`；`layout.txt`；原版 Skill v16 | 12 | 430,233 | 147.9 s | 7 C / 7 P；strict 50.0%，weighted 75.0% |

本表最后一列保留历史记录：分母是 Gold revision 2 的 T01 14 个 required claim
occurrence，partial 按 0.5 计。该口径主要评价具体方法细节，与 Query 1 明确要求错位，
且 PC `11 C / 3 P` 缺少逐项 scorecard；它已被下方 `query1-aligned-v1` 主任务评分取代，
不得再用于证明跨系统回答质量差距。

## Query 1-aligned 匿名盲评

2026-08-03 在打开候选答案前冻结 [评分规范](query1-rubric-v1.md)，主分为 14 篇 ×
题目、作者、唯一主要类别、监督设定、模态、判断页码，共 84 个等权原子项。方法名称、
机制细节和次要主题只做诊断，遗漏不扣主分。随后匿名随机排列 PC、B、C、D、E 和可恢复
的原生 Codex T01 答案；六份逐论文逐字段 scorecard 锁定哈希后才揭盲。

| 系统 | 匿名号 | correct / partial / incorrect / missing | strict | weighted | 覆盖 |
|---|---|---:|---:|---:|---:|
| 原生 Codex | A01 | 79 / 5 / 0 / 0 | 94.05% | 97.02% | 14/14 |
| C | A04 | 79 / 5 / 0 / 0 | 94.05% | 97.02% | 14/14 |
| B | A05 | 78 / 6 / 0 / 0 | 92.86% | 96.43% | 14/14 |
| D | A02 | 78 / 6 / 0 / 0 | 92.86% | 96.43% | 14/14 |
| E | A03 | 77 / 7 / 0 / 0 | 91.67% | 95.83% | 14/14 |
| Paper Copilot | A06 | 76 / 6 / 2 / 0 | 90.48% | 94.05% | 14/14 |

全部答案都覆盖 14 篇并提供可核验页码，weighted 最大差距只有 2.97 个百分点。PC 的
主要实质问题是把 P12 说成完全无标签、把 P14 缩窄为可见光—红外并漏掉近红外/热红外；
因此新结果不支持 PC 回答质量高于 Codex 桥接组。汇总和逐项评分合并保存在：

```text
/Users/a123/paper-copilot-eval-private/multi-thesis-v1/experiments/codex-vs-pc-v4flash/scores.yaml
```

揭盲后的 trace 合规审计确认六组都有正文/PDF 或 `layout.txt` 内容读取，未发现网络命令；
运行效率与可靠性仍按原始 trace 独立报告，不进入 84 项质量分。

## Query 2–4 当前评分口径

当前说明见
[Query 2–4 评分规范](query2-4-rubrics-v1.md)：

- Query 2：54 项，覆盖主要无监督筛选、监督类型边界、排除后问题集合及
  P02/P04/P06/P08/P11 的问题、方法、作者和页码；
- Query 3：上一轮实际纳入项按 `7 × 项数` 动态评分；项莘泽三个组件另计 15 项；两者
  不合成总分；
- Query 4：分别报告 14 项最终纳入判断、110 项内容准确度和 88 项逐单元格
  可追溯性，不把内容与证据压成一个 composite。

Query 2–4 已完成匿名盲评、scorecard 锁定和揭盲。当前汇总、逐项裁决与揭盲映射均已
合并进私有 `scores.yaml`；原始回答和 trace 由 `evidence.yaml` 索引。

| 系统 | Q2 weighted | Q3 prior review | Q3 项莘泽 | Q4 relevance | Q4 content | Q4 traceability |
|---|---:|---:|---:|---:|---:|---:|
| Paper Copilot | 87.04% | 100.00% | 96.67% | 100.00% | 99.55% | 86.36% |
| clean native Codex | 87.96% | 98.21% | 96.67% | 100.00% | 99.55% | 92.61% |

Query 3 两个评分族分开报告，Query 4 不生成正式 composite；这些结果是单语料、单链的
描述性结果。按用户要求另计算便利总分：所有原子评分项等权微平均，分母为
`84 + 54 + 43 + 212 = 393`。

| 系统 | Q1–4 weighted points / 393 | weighted | strict | completion |
|---|---:|---:|---:|---:|
| Paper Copilot | 370.5 / 393 | 94.27% | 89.57% | 98.73% |
| clean native Codex | 376.0 / 393 | 95.67% | 92.88% | 98.73% |

该便利总分包含 Q4 可追溯性；若只合并回答内容、排除 Q4 可追溯性，分母为 305，两组
weighted 均为 96.56%。

### Q1–Q4 系统级汇总

这是跨实验拼接的系统级视图：Q1 来自既有 `query1-blind-rescore-v1`，Q2–4 来自当前
`query2-4-blind-rescore-v2`；它们不是同一条连续 Q1–4 会话，因此不生成总分。

| 系统 | Q1 weighted | Q2 weighted | Q3 prior review | Q3 项莘泽 | Q4 relevance | Q4 content | Q4 traceability |
|---|---:|---:|---:|---:|---:|---:|---:|
| Paper Copilot | 94.05% | 87.04% | 100.00% | 96.67% | 100.00% | 99.55% | 86.36% |
| clean native Codex | 97.02% | 87.96% | 98.21% | 96.67% | 100.00% | 99.55% | 92.61% |

完整机器可读结果见私有实验目录中的 `scores.yaml`；冻结 Query、标签和 rubric 也位于
同一目录。

## 1. Responses-to-Chat adapter 兼容性链

实验目录前缀：

```text
/Users/a123/paper-copilot-eval-private/multi-thesis-v1/runs/codex-v4flash-chat-adapter-v2-t01-20260801T*
```

严格 adapter 逐步暴露了五类协议语义差异：

1. Codex 当前发送的 `instructions` 与 adapter 冻结的旧 base prompt 不一致；
2. Codex 请求 reasoning summaries，而 adapter 未支持；
3. Codex 请求 Responses `text` controls，而 Chat API 没有同构字段；
4. Codex 工具表面包含非 function tool，不能直接映射为 Chat `tools`；
5. Codex history 可按 `function_call -> output_text -> function_call_output` 排列，DeepSeek
   Chat 要求携带 `tool_calls` 的 assistant message 后紧邻匹配 tool message，否则返回
   HTTP 400 `insufficient tool messages`。

前四次失败都发生在首个有效回答前；第五次运行完成 2 次工具调用后在第三个模型请求失败，
没有最终答案。修复 history adjacency 后，`20260801T120405Z` 完成 T01：45 次命令工具
调用、847,516 total tokens、196.7 秒，CLI/adapter stderr 为空。

结论：Responses-to-Chat 不是 URL 或字段名替换，而是 prompt、reasoning、tool schema、
history ordering 和流式终态的语义转换。最终 Chat 运行仍有 45 次调用，因此“改用 Chat
协议”本身没有消除 V4 Flash 在 Codex 通用工具面上的高调用现象。单次 45 对 30 不能
证明 Chat 必然更差，因为 adapter 语义和随机性仍有差异。

## 2. Codex 原生基础指令与最小基础指令

原生基础指令运行：

```text
/Users/a123/paper-copilot-eval-private/multi-thesis-v1/runs/codex-deepseek-cli-v4-flash/t01-only-20260801T143253Z/
```

T01 完成，30 次工具调用、505,315 total tokens、188 秒。该 conversation 后续还执行了
T02，但本表只使用 T01 增量；T02 不进入本轮 T01 对照。

最小基础指令运行：

```text
/Users/a123/paper-copilot-eval-private/multi-thesis-v1/runs/codex-deepseek-cli-v4-flash/min-base-t01-manual-20260801/
```

base instructions 被替换为 155 characters 的最小文本，Paper Copilot `AGENTS.md` 未
注入；T01 完成，27 次工具调用、1 次非零命令、617,228 total tokens、172.7 秒。
rollout 仍包含 6,708 characters 的宿主 developer context，因此它是 base instructions
消融，不是“完全无 Codex developer context”实验。

结论：工具调用只从 30 降到 27，token 反而上升 22.1%。单次结果不支持“Codex 原生
base instructions 是 V4 Flash 高调用的主要原因”，但不能排除其与工具或模型的交互。
两次运行都保留宿主 Codex Desktop developer context，清洁度低于最终独立 Terminal
B/C；它们适合判断“只替换 base instructions 是否足够”，不适合作为完全无宿主上下文
基线。

## 3. Paper Copilot T01 复跑

```text
/Users/a123/paper-copilot-eval-private/multi-thesis-v1/runs/paper-copilot-v4-flash-current-max/t01-repeat-pc-v4flash-20260801T121327Z/
```

配置为 V4 Flash/max、纯文本输入、Skill v16 和当前 Paper Copilot Runtime。运行正常
`end_turn`：5 次 LLM 调用、5 次工具调用（1 次 `load_skill`、4 次
`library_exec`）、82,660 total tokens、68.6 秒、¥0.0516306；无 timeout、recovery、
模型失败、terminal tool failure 或输出省略。历史 T01 claim-detail 工作分为
11 correct / 3 partial，strict 78.6%、weighted 89.3%、coverage 100%；该口径现已撤销
为跨系统回答质量证据。

该运行同时拥有 Skill、prepared manifest、短路径 `layout.txt`、Paper Copilot base
instructions、工具结果协议和 Runtime orchestration，不能单独说明哪一层造成 5 次调用。
它证明的是组合系统在该次 T01 上取得了更少调用和更低 token；低价格只解释金额。由于
该次旧答案没有纳入新盲评，且旧工作分口径已经撤销，不能继续用它证明回答质量更高。

## 4. B/C library 与 Skill 成对诊断

B：

```text
/Users/a123/paper-copilot-eval-private/multi-thesis-v1/runs/codex-v4flash-responses-library-b-query1/20260801T155947Z-lane-b-bf148301-27f9-42d0-8fbf-16cc7868d077/
```

C：

```text
/Users/a123/paper-copilot-eval-private/multi-thesis-v1/runs/codex-v4flash-responses-library-c-query1/20260801T161359Z-lane-c-671ee6bf-e2a7-4d2b-b9c2-829b7869a598/
```

两组都由独立 Terminal 启动，使用 fresh `CODEX_HOME`，设置
`project_doc_max_bytes = 0`，并拒绝从父 Codex task 内启动。DeepSeek Responses、V4
Flash/max、Codex 原生基础指令、顶层 `library_exec/library_write_stdin` schema、论文
集合和 `layout.txt` 缓存保持一致；C 只额外加入冻结并明确标记的 Skill v16 developer
instruction。这里没有声称 Codex 使用了 Paper Copilot 原生 `load_skill` 生命周期。

C 相对 B：

- 工具调用 67 -> 26（-61.2%）；
- total tokens 3,022,640 -> 675,679（-77.7%）；
- 工具输出字符 198,259 -> 63,200（-68.1%）；
- 旧 claim-detail strict 42.9% -> 57.1%，weighted 71.4% -> 78.6%；
- 0 个可点击论文引用 -> 41 个 `paper-copilot://` 引用；
- wall time 308 秒 -> 279 秒（仅 -9.6%）。

C 仍发生 4 个失败后自行修正的命令和一次约 10 秒的全局查找，26 次不是优化下限。该
成对单次结果强烈支持 Skill instruction 抑制碎片化探索。新 Query-aligned 盲评中 B 为
96.43%、C 为 97.02%，只差 0.59 个 weighted 百分点；当前不再声称 Skill 显著改善 T01
回答质量，且仍需重复运行才能估计方差。

## 5. Codex 原生动态 Skill 桥接诊断

```text
/Users/a123/paper-copilot-eval-private/multi-thesis-v1/runs/codex-v4flash-native-skill-query1/20260803T102855Z-8c451575-0b8c-4321-bc04-7fc9dc583e4f/
```

D 使用全新 Codex thread、V4 Flash/max、纯文本输入、原始 14 篇 PDF、通用
`exec_command` 和 Codex 原生渐进式 Skill 交付。为了不引入 PC 工具和缓存，实验
Skill 从 PC v16 删除了 `library_exec`、prepared manifest、`layout.txt`、
`paper-copilot://`、`inspect_page` 和 `library_edit` 依赖，改用 `exec_command`、
`pdftotext -layout`、`pdfinfo` 和普通 PDF 页码证据。Skill SHA-256 为
`8291d592cddba5b984b26f70f227610b9a5043d6c670427677652d5d4d1a1c74`。

native rollout 确认模型先在 catalog 中选择 `research-papers`，再读取完整
`SKILL.md`，不是静态 developer instruction。运行正常 `turn.completed`：34 次命令调用，
1 次无匹配批量搜索返回非零，1,147,975 total tokens，263.3 秒，估算 ¥0.13108412。
历史 T01 claim-detail 工作分为 8 correct / 6 partial，strict 57.1%、weighted 78.6%、
coverage 100%。

新 Query-aligned 分数为 D 96.43%、C 97.02%，仅差 0.59 个百分点。该单次结果不支持
Codex 原生动态 Skill 产生可辨识的主任务质量优势。D 同时使用了为 Codex 原生工具改写的
Skill，且与 A/C 不是同时重复，不能将近似分数解释为交付机制完全无效。

E 进一步把 PC 的 catalog + `load_skill` 交付方式接入 C 的 Codex Runtime、Responses、
`world_state`、`library_exec`、prepared manifest 和 `layout.txt`，并在首次调用时原样返回
当前 Paper Copilot Skill v16；同一 MCP 进程只允许首次加载返回完整指令。正式运行目录：

```text
/Users/a123/paper-copilot-eval-private/multi-thesis-v1/runs/codex-v4flash-responses-library-e-query1/20260803T144642Z-lane-e-c7657487-e8c8-4547-b8b2-b5245556acb8/
```

fresh `CODEX_HOME`、唯一 UTC 目录、无 smoke、无自动重试。native rollout 确认
`load_skill` 恰好 1 次，之后 11 次 `library_exec`，共 13 次模型调用；最终用量为
414,207 input、16,026 output，即 430,233 total tokens，其中 cached input 364,160。
运行正常退出，耗时 147.9 秒，12 次工具调用全部成功。MCP stderr 记录 22 条
`Internal Server Error` 日志，但没有对应终态工具失败，作为可靠性异常单独保留。

历史 claim-detail 分为 7 correct / 7 partial，strict 50.0%、weighted 75.0%。新
Query-aligned 分数为 E 95.83%、C 97.02%、PC 94.05%。相对 C，E 的工具调用
26 -> 12、token -36.3%、耗时 -47.0%，但主任务质量只低 1.19 个百分点；E 反而比 PC
高 1.78 个百分点。因此该单次结果只对效率有正向信号，不支持“PC 式动态 Skill 交付是
PC 质量优势的原因”。

## 6. 上下文污染复核

旧四轮 direct run：

```text
/Users/a123/paper-copilot-eval-private/multi-thesis-v1/runs/codex-deepseek-cli-v4-flash/formal-single-20260731T163926Z/
```

它完成了 T01-T04，并保留 144 次 `exec_command`、10,617,376 formal total tokens 和
Gold revision 2 工作评分。但 native rollout 显示该 session 来自 Codex Desktop；T03
前出现 `thread_settings_applied`，cwd 切换为 `/Users/a123/code/paper-copilot`，随后完整
Paper Copilot `AGENTS.md` 进入用户上下文。因此：

- 这不是 V4 Flash 凭空猜出本地路径，也不是 Paper Copilot Skill 被 Codex 正常加载；
- 该四轮 run 可用于运行可靠性、成本和污染机制审计，不能作为干净的 Codex 四轮质量/
  调用基线；
- metadata 中存在 Skill v16 SHA-256 也不能证明 Skill 已加载，trace 没有 `load_skill`；
- 最终 B/C 通过独立 Terminal、fresh home、禁止父 task 和禁用项目文档消除了已识别污染。

## 7. 当前可支持的总判断

1. **不是单纯协议问题。** Responses 通用工具运行为 30 次，修复后的 Chat adapter 为
   45 次；两者都高。协议会影响可靠性和 history 语义，但切换 Chat 没有自动恢复低调用。
2. **不是单纯 Codex base instructions 问题。** 最小 base 仍为 27 次，且 token 高于
   原生 base 单次运行。
3. **Skill 对 V4 Flash 的工具行为影响很大，但质量信号很小。** 在 B/C 受控条件下，
   Skill 把调用和 token 分别降低 61.2% 和 77.7%；新盲评只提高 0.59 个 weighted
   百分点，不能据此声称稳定质量提升。
4. **Paper Copilot 的效率信号与回答质量必须分开。** 历史 PC 运行的低调用、低 token
   仍然有效；新盲评中 PC 为 94.05%，低于其余五组，旧 `11 C / 3 P` 不再是质量优势
   证据。
5. **V4 Flash 不是在所有 Agent 上都必然高调用。** 它在 PC 组合中只调用 5 次；历史
   V4 Pro/max Chat adapter 又能在 19 次 native function call 内完成四轮。跨模型历史
   对照不能证明模型因果，但共同指向“模型与 Agent context/tool loop 的交互”，而不是
   adapter 根本不能工作或 V4 Flash 单独决定一切。
6. **仍不能把优势归到某一个 PC 组件。** PC 对比 C 仍同时改变 Runtime、base
   instructions、工具反馈、上下文组织和引用合成；需要继续做 PC 内部成对消融才可分配
   功劳。
7. **PDF 证据能力必须单独表述。** B、C 和 PC 复跑都读取 `layout.txt`，不是直接读取
   PDF 视觉原文；它们的 T01 分类结果不能证明公式和复杂表格解析能力。
8. **Codex 原生动态 Skill 没有产生可辨识的主任务优势。** D 为 96.43%、C 为 97.02%；
   不过单次近似分数不能单独否定交付机制与 Runtime 的交互。
9. **PC 式 catalog + `load_skill` 的主要信号是效率。** E 比 C 更少调用、更少 token、
   更快，质量只低 1.19 个百分点；E 又高于 PC 1.78 个百分点，不能把交付机制解释为
   PC 质量优势。
10. **旧跨系统质量结论已撤销。** 新评分下六组 weighted 范围为 94.05%–97.02%，原生
    Codex/C 并列最高、PC 最低；这是单语料单次描述，不是稳定排名或因果证据。

## 8. 下一步与停止条件

当前评分修复任务已经完成，不需要发起新模型调用。若未来获得新的付费执行授权，优先级为：

1. 若需要估计稳定性，对关键 B/C 或 PC 对照至少重复 3 次，并统一使用
   `query1-aligned-v1`；
2. 在 Paper Copilot 同一提交内做 Skill on/off 成对运行，只把调用、token 和质量分别
   作为独立指标；
3. 将公式/复杂表格质量放入独立 PDF 结构化证据评测，不与当前 T01 分类分数混为一项。

## 9. 实验实现与原始证据

本目录同时保存 B/C 桥接实验的 runner、配置和 Codex 补丁。准备与付费执行分离：

```bash
eval/experiments/codex-vs-pc-v4flash/prepare_codex.sh
eval/experiments/codex-vs-pc-v4flash/launch.sh b /absolute/private/runs
```

将 `b` 改为 `c` 可运行静态 Skill 指令组。当前评分与原始证据索引通过以下私有入口访问：

`/Users/a123/paper-copilot-eval-private/multi-thesis-v1/experiments/codex-vs-pc-v4flash/`
