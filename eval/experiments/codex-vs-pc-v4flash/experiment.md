# DeepSeek V4 Flash 与 Codex/Paper Copilot 实验记录

状态：单次 T01 诊断已完成；不作统计显著性结论  
日期：2026-08-01 至 2026-08-02  
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

| 运行 | 协议、工具与输入 | 工具调用 | total tokens | 耗时 | T01 工作评分 |
|---|---|---:|---:|---:|---|
| Paper Copilot T01 复跑 | 生产 Chat 路径；Skill v16；`library_exec`；`layout.txt` | 5 | 82,660 | 68.6 s | 11 C / 3 P；strict 78.6%，weighted 89.3% |
| Codex Chat adapter v2 | Responses-to-Chat；通用命令；原始 PDF | 45 | 847,516 | 196.7 s | 未评分 |
| Codex 原生基础指令 T01 | DeepSeek Responses；通用命令；原始 PDF | 30 | 505,315 | 188 s | 未评分 |
| Codex 最小基础指令 T01 | DeepSeek Responses；通用命令；原始 PDF | 27 | 617,228 | 172.7 s | 未评分 |
| B：Codex library/no Skill | DeepSeek Responses；`library_exec`；`layout.txt` | 67 | 3,022,640 | 308 s | 6 C / 8 P；strict 42.9%，weighted 71.4% |
| C：Codex library/Skill v16 | 与 B 相同，只增加冻结 Skill developer instruction | 26 | 675,679 | 279 s | 8 C / 6 P；strict 57.1%，weighted 78.6% |

所有评分分母均为 Gold revision 2 的 T01 14 个 required claim occurrence，partial
按 0.5 计；三个已评分运行 coverage 均为 100%。这些分数是本轮统一复核后的单次工作
评分，不是独立复核或统计重复结果。

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
模型失败、terminal tool failure 或输出省略。统一 T01 评分为 11 correct / 3 partial，
strict 78.6%、weighted 89.3%、coverage 100%。

该运行同时拥有 Skill、prepared manifest、短路径 `layout.txt`、Paper Copilot base
instructions、工具结果协议和 Runtime orchestration，不能单独说明哪一层造成 5 次调用。
它证明的是组合系统在该次 T01 上确实同时取得了更少调用、更低 token 和更高工作评分；
低价格只解释金额，不解释工具调用、token 或正确率优势。

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
- strict 42.9% -> 57.1%，weighted 71.4% -> 78.6%；
- 0 个可点击论文引用 -> 41 个 `paper-copilot://` 引用；
- wall time 308 秒 -> 279 秒（仅 -9.6%）。

C 仍发生 4 个失败后自行修正的命令和一次约 10 秒的全局查找，26 次不是优化下限。该
成对单次结果强烈支持 Skill instruction 抑制碎片化探索并改善 T01 回答，但仍需重复运行
才能估计方差。

## 5. 上下文污染复核

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

## 6. 当前可支持的总判断

1. **不是单纯协议问题。** Responses 通用工具运行为 30 次，修复后的 Chat adapter 为
   45 次；两者都高。协议会影响可靠性和 history 语义，但切换 Chat 没有自动恢复低调用。
2. **不是单纯 Codex base instructions 问题。** 最小 base 仍为 27 次，且 token 高于
   原生 base 单次运行。
3. **Skill 对 V4 Flash 行为影响很大。** 在 B/C 受控条件下，Skill 把调用和 token
   分别降低 61.2% 和 77.7%，同时提高工作评分。
4. **Paper Copilot 的优势不能只记到低价模型。** 同一 V4 Flash 的 PC 复跑为 5 次调用、
   82,660 tokens 和更高 T01 工作评分；价格只影响账单，不能解释这些机制指标。
5. **V4 Flash 不是在所有 Agent 上都必然高调用。** 它在 PC 组合中只调用 5 次；历史
   V4 Pro/max Chat adapter 又能在 19 次 native function call 内完成四轮。跨模型历史
   对照不能证明模型因果，但共同指向“模型与 Agent context/tool loop 的交互”，而不是
   adapter 根本不能工作或 V4 Flash 单独决定一切。
6. **仍不能把优势归到某一个 PC 组件。** PC 对比 C 仍同时改变 Runtime、base
   instructions、工具反馈、上下文组织和引用合成；需要继续做 PC 内部成对消融才可分配
   功劳。
7. **PDF 证据能力必须单独表述。** B、C 和 PC 复跑都读取 `layout.txt`，不是直接读取
   PDF 视觉原文；它们的 T01 分类结果不能证明公式和复杂表格解析能力。

## 7. 下一步与停止条件

当前不需要继续重复已经明显失败的 adapter 请求，也不需要为了判断乱码机制全量扫描
14 篇 PDF。若继续实验，优先级为：

1. 在 Paper Copilot 当前同一提交内做 Skill on/off T01 成对运行，隔离 PC Runtime 内部
   的 Skill 贡献；
2. 若需要估计稳定性，再对关键 B/C 或 PC 对照重复至少 3 次；
3. 将公式/复杂表格质量放入独立 PDF 结构化证据评测，不与当前 T01 分类分数混为一项。

## 8. 实验实现与原始证据

本目录同时保存 B/C 桥接实验的 runner、配置和 Codex 补丁。准备与付费执行分离：

```bash
eval/experiments/codex-vs-pc-v4flash/prepare_codex.sh
eval/experiments/codex-vs-pc-v4flash/launch.sh b /absolute/private/runs
```

将 `b` 改为 `c` 可运行静态 Skill 指令组。完整原始证据通过以下统一私有入口访问：

`/Users/a123/paper-copilot-eval-private/multi-thesis-v1/experiments/codex-vs-pc-v4flash/raw/`

该 `raw/` 目录保留 Codex direct、Chat adapter、B、C、PC current 和 PC no-Skill
运行入口；旧 `runs/` 路径继续保留，不移动原始产物。
