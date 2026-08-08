# Formula OCR comparison rubric v1

状态：冻结  
适用范围：`codex-vs-pc-deepseek-formula-ocr` Query 1–2

## 内容评分

两个 query 使用同一组 12 个等权原子项，分别评分：

1. `page_identity`：明确定位 PDF 物理第 34 页；
2. `eq310_lhs`：公式（3-10）左侧及摄像头条件上标正确；
3. `eq310_branch1_value`：第一分支的比值、分子和带约束的 `max` 分母正确；
4. `eq310_branch1_condition`：第一分支的 `j != i` 与 `j in N(i)` 条件正确；
5. `eq310_branch2`：第二分支的值与 `j != i`、`j notin N(i)` 条件正确；
6. `eq310_branch3`：第三分支 `j = i` 时取 1；
7. `eq311_lhs`：条件概率左侧的 `c/i/j/t/theta` 角色和条件方向正确；
8. `eq311_numerator`：指数、候选与锚点特征点积、温度参数位置正确；
9. `eq311_denominator_domain`：求和域同时包含 `k in N(i)` 和 `C_k = c`；
10. `eq311_denominator_term`：分母项使用候选 `k` 与固定锚点 `i`，并与分子使用同一温度缩放；
11. `semantics`：说明式（3-10）是按摄像头分组的亲和度，式（3-11）在同摄像头邻域内归一化同一行人条件概率；
12. `relation_to_eq39`：说明式（3-10）的权重与式（3-11）的对数概率进入式（3-9）的负交叉熵求和。

每项：

- `correct=1`：语义和结构完整；
- `partial=0.5`：核心正确但遗漏一个不改变主体的约束、上下标或解释；
- `incorrect=0`：给出与原 PDF 冲突的可判定内容；
- `missing=0`：未提供或明确写“未确认”。

LaTeX 空格、括号大小、`·` 与 `\cdot`、`\mathbb{N}` 与无歧义的等价字体不扣分。交换
锚点/候选索引、漏掉摄像头过滤、把分段条件改写为另一集合，属于实质错误。

主要报告：

- strict：`correct / 12`；
- weighted：`(correct + 0.5 * partial) / 12`；
- completion：`(correct + partial + incorrect) / 12`。

## 证据与可靠性诊断

以下不并入 12 项内容分：

- 是否给出正确物理页码；
- 是否在符号无法核验时明确降级；
- 是否在公式错误时仍声称“已从 PDF/OCR 核验”；
- 最终回答是否引用网络、其他论文、历史答案或不可追溯来源。

不得因为文风自信而判定调用过 OCR，也不得因为出现 LaTeX 就推断公式来自 PDF。工具路径只
根据权威 session/rollout/trace 判定。

## 机制指标

### Query 1

- `cold_target_clean`：运行前目标页没有 accepted OCR record；
- `formula_recognize_calls`：实际 formula recognize 次数；
- `formula_accept_calls`：实际 accept 次数；
- `accepted_formula_matches_gold`：发布内容是否与 Gold 等价；
- `text_only_visual_attempt`：是否尝试了当前模型不支持的视觉路径；
- `terminal_state`、失败、恢复、token、耗时。

### Query 2

- `fresh_conversation`：没有携带 Query 1 对话历史；
- `accepted_cache_visible`：读取层是否出现已识别公式记录；
- `formula_recognize_calls`：理想的 Paper Copilot warm path 为 0；
- `formula_accept_calls`：理想 warm path 为 0；
- `warm_answer_quality_delta`：相对本系统 Query 1 的 weighted 变化；
- `terminal_state`、失败、恢复、token、耗时。

机制指标与回答质量分开报告。OCR 调用多不自动扣内容分；未调用 OCR 但公式完全正确也不自动
加分。跨系统结论需要同时展示 answer quality、工具路径和运行成本。

