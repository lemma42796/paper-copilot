# Codex CLI/GPT、Codex CLI/DeepSeek 与 Paper Copilot/DeepSeek 三方评测

日期：2026-07-30  
语料：`multi-thesis-v1`，14 篇硕士论文，1169 页  
主对照：Codex CLI + `gpt-5.6-sol`、Codex CLI + DeepSeek V4 Pro、Paper Copilot +
DeepSeek V4 Pro  
运行：每套系统单次、同一会话连续 T01–T04、无中途人工纠正

## 1. 结论

三套系统的 claim coverage 均为 90.1%，但严格和加权正确率存在明显差异。Codex CLI
更换为 DeepSeek V4 Pro 后仍接近原生 `gpt-5.6-sol`；Paper Copilot 使用同一
DeepSeek V4 Pro 时严格正确率和加权正确率更低。描述性结果支持执行系统、Agent
编排、提示与工具表面会显著影响同一模型的任务表现，但不能把差异单独归因于其中一个
组件。

Codex CLI + DeepSeek V4 Pro 的主要扣分来自：

- T02 将张耀斌论文错误判为完全无监督，而不是 Gold 裁决的无监督域适应；
- T03 没有按要求回查张耀斌、刘章平两篇论文的无监督属性；
- T04 再次把张耀斌标为完全无监督；
- T01 的“判断页码”列实际填写了 PDF 总页数；
- T04 虽给出每行汇总页码，但没有做到每个关键单元格逐项可追溯。

## 2. Required claims 工作评分

评分单位是 `gold/turns.yaml` 中 `expected_claims.required` 的 claim occurrence，共 71 项。
`partial` 按 0.5 计入加权分；错误 taxonomy 记为 `incorrect`；未明确断言记为
`missing`。

| 系统 | correct | partial | incorrect | missing | 严格正确率 | 加权正确率 | claim coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| Codex CLI + `gpt-5.6-sol` low | 54 | 10 | 0 | 7 | 76.1% | 83.1% | 90.1% |
| Codex CLI + DeepSeek V4 Pro max | 53 | 9 | 2 | 7 | 74.6% | 81.0% | 90.1% |
| Paper Copilot + DeepSeek V4 Pro | 41 | 21 | 2 | 7 | 57.7% | 72.5% | 90.1% |

相对已有工作评分：

- Codex CLI + V4 Pro 比 Codex CLI + GPT：严格正确率低 1.5 个百分点，加权正确率
  低 2.1 个百分点，claim coverage 持平；
- Codex CLI + V4 Pro 比 Paper Copilot + V4 Pro：严格正确率高 16.9 个百分点，
  加权正确率高 8.5 个百分点，claim coverage 持平；
- Paper Copilot + V4 Flash 的 57.7% / 66.2% / 76.1% 只保留为历史辅助参照，不进入
  当前三方主表。

## 3. Codex CLI + DeepSeek V4 Pro 分轮与逐项裁决

| 轮次 | C/P/I/M | correct | partial | incorrect | missing |
|---|---:|---|---|---|---|
| T01 | 11 / 3 / 0 / 0 | C002, C004, C007, C010, C014, C020, C026, C032, C035, C038, C041 | C017, C023, C029 | — | — |
| T02 | 12 / 1 / 1 / 0 | C006, C011, C023, C024, C032, C033, C034, C035, C037, C038, C039, C040 | C036 | C044 | — |
| T03 | 9 / 1 / 0 / 7 | C006, C010, C011, C012, C013, C023, C032, C033, C034 | C024 | — | C035, C036, C037, C038, C039, C040, C044 |
| T04 | 21 / 4 / 1 / 0 | C002, C004, C006, C007, C010, C011, C014, C016, C017, C018, C020, C022, C023, C024, C026, C027, C030, C031, C041, C042, C043 | C015, C021, C028, C029 | C044 | — |

主要裁决：

- T01 的 C017 只提到双向掩码重建，没有完整锚定“文本到可见光图像”；C023 没有明确
  “任意模态缺失”；C029 没有说明 SAM 分割结果与原图融合，因此计 partial。
- T02 的 C036 覆盖 GraphSAGE，但遗漏迁移时间集合过滤视觉信息，计 partial。
- T02 的 C044 明确声称张耀斌“完全无监督、非 UDA”，与 PDF 第 37–38 页和 Gold
  revision 2 相反，计 incorrect。
- T03 对张兴帅只复核到缺失模态特征补偿，没有重新给出“注意力 + 可学习模态原型”
  的完整机制，C024 计 partial；张耀斌和刘章平相关 7 项没有复核，计 missing。
- T04 的 C015、C021、C028、C029 各覆盖了主要方向，但缺少 Gold 中的一个或多个
  关键机制限定，计 partial；C044 再次把张耀斌写成完全无监督，计 incorrect。

## 4. Codex CLI + DeepSeek V4 Pro 范围与指令遵循

| 指标 | V4 Pro |
|---|---:|
| T01 论文覆盖 | 14/14 |
| T02 required paper coverage | 6/6 |
| T03 required paper coverage | 4/6 |
| T04 最终 required set | 11/11 |
| T04 forbidden set 泄漏 | 0/3 |
| T04 每篇一行 | 满足 |
| 不跨协议强行排序 | 满足 |
| P04 仅保留 ReID 内容 | 满足 |
| 每个关键单元格可追溯 | 不满足 |

T03 正确拆分项莘泽论文：LIF-ClipReid 纳入，轨迹补全和可视化系统排除。T04 也正确
保持了累积排除条件和最终 11 篇集合。

## 5. Codex CLI + DeepSeek V4 Pro 引用与证据质量

- T01 表格“页码”列的 66、65、82 等数字对应 PDF 总页数，不是判断页码，不能作为
  可复核证据。
- T02 对关键边界主要引用摘要页和目录页，能支持主题判断，但不足以支持张耀斌的监督
  taxonomy；该轮没有读取 Gold 所依据的 PDF 第 37–38 页。
- T03 对何子玲、张兴帅、刘昕宇和项莘泽提供了章节、物理页码和短原文，证据深度较好；
  但完全遗漏两篇无监督论文的复核。
- T04 多数行只有摘要页或宽泛章节页段，具体方法、注意力位置、指标和局限性无法逐单元格
  对应；因此“每个关键单元格必须可追溯”不成立。

## 6. 工具行为与运行量

### Codex CLI + DeepSeek V4 Pro

- 17 次原生命令调用，全部 `exit_code=0`；
- T01/T02/T03/T04 分别为 3/1/10/3 次；
- 四轮均正常完成，无模型或适配器协议错误；
- 墙钟时间约 538 秒；
- input tokens 2,947,977，其中 cached input 2,656,768；
- output tokens 78,147，其中 reasoning output 46,959；
- 供应商金额未写入权威 trace，费用标记为 `unverifiable`。

### Paper Copilot + DeepSeek V4 Pro

- conversation：`conversation-20260729T141953-65092f325e`；
- 四轮 job 均正常 `end_turn`；
- 18 次 `library_exec`、57 次 `read_page`，权威 trace 中全部完成；
- 42 次模型调用；
- 墙钟时间合计约 537 秒；
- uncached input 142,044、cache read 2,411,008、output 35,949 tokens，其中
  reasoning 13,363；
- 总费用 0.7021012 元。

不同运行表面和供应商的 token 记账口径不可直接用来做效率排名。两套 DeepSeek V4 Pro
运行的墙钟时间接近，但 Codex CLI 的输出与 reasoning token 明显更多；不能只据此判断
Agent 效率。

## 7. 当前判断

本冻结案例中，Codex CLI + DeepSeek V4 Pro 的 required-claim coverage 与原生 Codex
持平，严格和加权正确率接近但略低。Paper Copilot + 同一 DeepSeek V4 Pro 的 coverage
同样为 90.1%，但更多 claim 只能判为 partial。三个系统共同暴露的关键风险不是简单的
“没读到论文”，而是：

1. 对监督 taxonomy 的高置信错误；
2. 复核规划和证据深度不足；
3. 证据页码和关键表格单元格没有形成稳定的一一对应。

同一模型在 Codex CLI 与 Paper Copilot 间的 8.5 个百分点加权差距，说明不能把既有
系统差距只归因于模型。但两套系统同时改变 Agent loop、system/developer instructions、
上下文构造、工具 schema、缓存与证据表面，因此也不能进一步声称差距已被严格定位到
Paper Copilot Agent loop。

## 8. 有效性限制

- 同一语料只运行一次，不能估计方差或显著性；
- Codex CLI + DeepSeek V4 Pro 的新增裁决在生成运行后的同一 Codex 任务内完成，
  属于人工工作评分；三方结果仍需强隔离复核后才能冻结；
- 三套系统的模型、reasoning 设置、Agent loop、提示、上下文和工具表面并未全部受控，
  分数差异不能归因于单一变量；
- 原始四轮回答、原生 rollout、冻结 Query、配置和语料哈希均保留在正式运行目录中。

## 9. 私有评分与证据索引

统一私有入口中的 `scores.yaml` 保存当前评分，`evidence.yaml` 指向原始运行：

`/Users/a123/paper-copilot-eval-private/multi-thesis-v1/experiments/codex-vs-pc-v4pro/`
