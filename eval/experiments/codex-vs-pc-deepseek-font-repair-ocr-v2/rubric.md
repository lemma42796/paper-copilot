# Scoring rubric v1

状态：冻结
适用范围：`codex-vs-pc-deepseek-font-repair-ocr-v2` Query 1–3

## 回答质量

私有 `labels.yaml` 中每个原子标签独立判定：

- `correct=1`：关键符号、约束、索引和语义完整，且与原 PDF 视觉页面一致；
- `partial=0.5`：主体正确，但遗漏一个不改变核心关系的约束、上下标或解释；
- `incorrect=0`：给出与原 PDF 冲突的可判定内容；
- `missing=0`：未回答，或按要求明确写“未确认”。

LaTeX 空格、括号尺寸、等价字体和无歧义的排版差异不扣分。交换锚点/候选索引、遗漏摄像头
或邻域条件、改变分段条件、补造原页不存在的结构，均为实质错误。

每个 query 单独报告：

- `strict = correct / label_count`；
- `weighted = (correct + 0.5 * partial) / label_count`；
- `completion = (correct + partial + incorrect) / label_count`。

Query 3 与 Query 2 共用内容 Gold，但必须独立评分。不得用 Query 2 的答案替 Query 3 打分。

## Agent 专用指标

以下指标不并入回答质量分：

- `task_completed`：是否产出满足格式和范围要求的最终回答；
- `grounded_claim_rate`：可追溯到目标 PDF 的已评分事实占全部已评分事实的比例；
- `unsupported_claim_count`：无法由目标 PDF 或权威工具证据支持的确定性主张数；
- `honest_uncertainty_count`：无法确认时按要求明确降级的原子项数；
- `effective_tool_calls`：直接贡献目标证据的成功工具调用数；
- `failed_tool_calls`：失败、超时或返回不可用证据的工具调用数；
- `recovery_success`：工具失败后是否在同一任务中恢复并完成；
- `human_interventions`：除启动、授权和发送冻结 query 外的人工操作次数；
- `terminal_state`：权威运行产物记录的终态；
- `evidence_path`：实际使用的文本缓存、字体修复、页面几何、OCR 或其他证据路径。

Query 2/3 另报：

- `formula_recognize_calls` 和 `formula_accept_calls`；
- `accepted_formula_matches_gold`；
- `accepted_cache_visible`；
- `warm_reuse_without_ocr`：Query 3 是否在新会话中零 OCR 复用已核验缓存；
- `warm_quality_delta`：Query 3 相对同系统 Query 2 的 weighted 变化。

不得根据最终答案的文风或 LaTeX 外观推断调用过工具、修复过字体或命中过缓存。

## 经营与资源指标

经营指标按 [metrics.yaml](metrics.yaml) 采集，与回答质量分开报告。至少展示：

- 墙钟耗时、首个有效答案时间和本地 OCR 耗时；
- 模型调用、工具调用和 OCR 调用次数；
- 输入、输出、推理、缓存读取、缓存写入及总 Token；
- 模型成本、OCR 可归属成本、总可归属成本；
- 每个成功任务成本、每个 weighted 百分点成本和每千 Token 成本。

只有供应商账单、客户端 usage 或权威 trace 中存在的值才能记为实测。无法拆分的本地 CPU、
内存、电力和人工时间写 `null`，不得填 0。

## 正式评分边界

先冻结本文件、`metrics.yaml`、`queries.md` 和私有 `labels.yaml` 的哈希，再读取待评分答案。
失效运行保留其调用、Token、成本、耗时、失败和恢复数据，但从回答质量分母中排除。不得因
某系统更便宜或更快而修改回答质量，也不得因回答正确而忽略失败重试和额外成本。
