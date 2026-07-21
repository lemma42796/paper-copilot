# TASKS

> 状态：活文档。只记录当前状态、仍有效的决策、已完成阶段摘要和延期候选项。
> 逐次试跑日志和已结束 milestone 的完整讨论由 Git 历史保留。

## Current Status

更新于 2026-07-21。新会话先读本节，再看 `git log -n 10`。

### 产品与架构

- Paper Copilot 是唯一具有自主 tool loop 的 Agent；`ReadPaperTool`、
  `SkimPaperTool`、`ExtractPaperTool`、`LinkRelatedPapersTool` 是有界工具。
- 用户从 Next.js Web UI 的单输入框提交原始 prompt。关键词 router、`route`、
  `task_profile` 和终端 CLI 已删除。
- 本地 Python API 提供 chat、报告、证据反查和 Composer library preview；
  session、报告和索引继续 local-first 落盘。
- 默认模型是 `qwen3.6-flash`；所有 LLM 调用统一经过
  `agents/llm_client.py`。模型分配的单一真源是 `ARCHITECTURE.md`。
- 跨论文检索使用 `text-embedding-v4`（1024 维）、sqlite-vec、FTS5/BM25、
  RRF 和每篇论文内部的 deterministic evidence chunk selector。

### 已完成基线

- M1-M15 已完成：项目骨架、结构化读取、JSONL session、真实使用回归、
  prompt/cache 观测、字段和向量索引、跨论文关联、确定性对比、eval suite、
  趋势报告与模型选型实验均已落地。
- M16 已完成门禁全绿和 schema validation 最小恢复；GitHub Actions 与可复现
  smoke eval 按当时用户决策跳过。
- 原 M17 的 bounded research loop、session trace 和本地工具面已经演化为当前
  单 Agent chat runtime。历史 CLI 入口和多 Agent 命名不再代表现状。
- M18 paper-level RAG gate 和 chunk/evidence baseline 已完成。当前不再针对
  seed eval 盲调 ranking。
- Web shell 已落地：历史报告、Markdown 表格、Composer 摘要、chunk/field
  evidence ref 点击反查和 4K README 截图均已接入。
- 指令遵循硬化已完成：Composer checker 失败时最多 repair 一次；三个结构化
  worker 隔离不可信论文来源；主 loop 在每批工具结果后刷新权威运行状态。

### Research Idea Composer 当前能力

本地资料库优先的 Composer 已有：

- `ccf_a` → `ccf_b` → `other` 的确定性 pool 顺序；低优先级 pool 只能在前一
  pool 关闭并记录拒绝理由后使用。
- `composer_plan` 状态机，记录 baseline 选择、module 接受/拒绝、pool 关闭、
  `allowed_next_tools` 和 `report_ready`。
- 一个性能强、但仍有明确改进空间或研究故事的 CCF A baseline。
- 正常成功路径要求 3 个 accepted modules，来自 3 个不同 paper；每篇 module
  paper 最多贡献一个模块。
- 中文结构化报告、inline evidence refs 和 deterministic proposal checker。
- checker 会拦截无引用且未标为假设的指标提升、损失组合、复杂度变化、框架名、
  optimizer、学习率、batch size、epoch 等 implementation specifics。

最新严格 VI-ReID 真实重跑通过质量门：

- `termination=end_turn`
- `cost=¥0.649416`
- `papers=4/6`
- `proposal_check.passed=true`
- 1 个 baseline + 3 个来自不同 CCF A 论文的 modules
- `unsupported_specific_count=0`

这只是一个 clean demo，不能据此宣称跨任务稳定泛化。2026-05-23 用户明确跳过
2-3 个固定 Composer 任务的多任务验收；除非用户重新要求，不补跑这套真实任务。

### Retrieval 基线

默认测试库曾完成 34 papers / 2066 chunks 的 `text-embedding-v4` 索引。36 条
paper-level seed queries 的记录结果：

| 指标 | 结果 |
|---|---:|
| paper recall@5 | 98.4% |
| paper recall@10 | 100.0% |
| paper precision@5 | 32.8% |
| paper precision@10 | 16.9% |

13 条带 evidence anchor 的 query 使用 exact substring + embedding semantic
window match：

| 指标 | 结果 |
|---|---:|
| evidence recall@5 | 87.2% |
| evidence recall@10 | 89.7% |
| evidence anchor precision@5 | 44.9% |
| evidence anchor precision@10 | 45.3% |

anchor precision 只衡量已标注论文返回 chunk 对人工 anchor 或语义窗口的命中，
不是对所有未标注 chunk 的完整相关性判断。

### 已知边界

- M19 只有 VI-ReID 单例通过，未完成跨任务泛化验收。
- evidence recall 仍有约 10%-13% 的已知 grounding 缺口；正式方案必须把无证据
  细节降级成假设或风险。
- budget gate 在 LLM 调用边界检查，不做严格预扣；最后一次调用可能让实际成本
  略超预算。
- `Method.name` 跨运行会改写，`is_novel_to_this_paper` 等边界字段会随机翻转；
  eval 不对这些高噪声字段做严格单跑断言。
- 旧 session 可能带已删除的 `meta.id`；fields store 保存 raw JSON 因而兼容，
  但不能假设所有历史记录都能直接反序列化为当前 `Paper`。
- PDF-only metadata 不能保证 canonical title、venue 或 arXiv 信息完整；外部
  enrichment 仍未实现。
- 不做 reranker、paper alias/metadata retrieval、图表 CV 理解、云端多用户或
  多 embedding 模型共存，除非真实数据重新证明有必要。

## Milestone Digest

| Milestone | 状态 | 保留成果 |
|---|---|---|
| M1-M3 | Done | Python 项目骨架、logging/errors/cost、bounded tool loop |
| M4-M7 | Done | Pydantic schemas、真实 LLM 读取链路、JSONL session、结构化报告 |
| M8 | Done | 真实使用 issue triage；outline、section dedup、schema/prompt 修正 |
| M9 | Done | prompt cache 分层、usage/latency/cost 观测；同 paper rerun 约降 18.6% |
| M10 | Done | `fields.db` raw JSON + 表达式索引；13 篇查询 < 1ms |
| M11 | Done | sqlite-vec 跨论文索引和检索；旧 13 篇重建 186.9s |
| M12 | Done | 整篇粒度 `CrossPaperLink` 和方向枚举的确定性校验 |
| M13 | Done | 基于结构化字段的无 LLM 对比 |
| M14 | Done | 5-paper smoke suite、field assertions、绝对 cost/latency cap |
| M15 | Done | 静态 SVG 趋势报告；flash vs plus 实测模型选型 |
| M16 | Closed | 门禁与 schema retry 完成；其余原 DoD 按用户决策删除 |
| M17 | Superseded | bounded research loop 的有效部分并入单 Agent chat runtime |
| M18 | Done | FTS5/BM25 + vector RRF、多 chunk evidence、retrieval eval |
| M19 | Closed | Composer plan、checker 和单例验收完成；其余原 DoD 按用户决策删除 |
| M20 | Partial | Next.js 本地 Web shell 与证据/报告 UI 已落地；job streaming/upload 未做 |

## Stable Decisions From Completed Work

### LLM 输出与 prompt

- Pydantic `Field.description` 能抑制字面模板错误，但不能消除语义变体；后者用
  validator、retry 或 output filter。
- graded fields 优先用有清晰锚点的小枚举，不用容易挤到上界的 float。
- 有时间、因果或层级结构的方向枚举必须做 deterministic post-validation。
- qwen3.6-flash 在当前 Anthropic-compatible endpoint 下对嵌套 `$ref` 不稳定；
  tool schema 继续通过 `shared/jsonschema.py` 展开。

### Eval

- 单次严格 name-keyed assertions 低于 LLM noise floor，会制造 flake。
- 当前 eval 只拦 catastrophic-class regression；趋势图用于区分自然锯齿与整体断崖。
- 模型升级需要同时满足 0 regression 和正向 ROI；只通过回归门不等于应该升级。

### Cost 与模型

M15 用同一 smoke suite 对比 qwen3.6-flash 与 qwen3.6-plus：plus 5/5 PASS，
但成本 2.03x、延迟 2.22x，现有断言没有测出质量上行，因此继续使用 flash。
跨模型 cache 对比必须使用相同冷启动基线，不能把连续 warm runs 的均值与候选
首次调用直接比较。

### Storage 与 retrieval

- session 用 append-only JSONL，热查询索引用 SQLite。
- `retrieval/` 和 `knowledge/` 保持兄弟模块；共享 chunk/embedding 原语放
  `shared/`。
- embedding model 锁定并写 meta；换模型走全量 reindex，不并存多套向量。
- 小型个人库继续使用 SQLite；不要为了“企业感”引入独立向量数据库。

## Deferred Ideas

以下不属于当前 DoD，只有用户明确选择时才开始：

1. 跨任务 Composer 人工验收与质量统计。
2. 预算预估/预扣，修复最后一次 LLM 调用后的尾部超限。
3. 若真实 retrieval eval 出现新 miss，再评估 metadata/alias retrieval 或 reranker。
4. 可选的 paper intake：CCF venue map、DBLP/CVF/OpenReview/arXiv 元数据与公开 PDF，
   受限来源返回 `needs_user_pdf`，不绕过 paywall。

## Global Discipline

1. 一次只推进一个明确 milestone 或 bounded slice；DoD 满足后停下总结。
2. milestone 边界更新本文件，不把逐次命令输出继续堆进 Current Status。
3. 待验证假设被推翻时先更新 `ARCHITECTURE.md`，再继续实现。
4. 新 LLM call site 先设计 eval 覆盖，并报告预计 token/cost。
5. 默认不自动 commit 或 push；只有用户明确要求时执行。
