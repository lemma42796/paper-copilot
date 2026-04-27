# ARCHITECTURE

> 状态：draft v2，跨论文检索纳入主架构。标注"待验证"的部分预期会在 M5
> （首个真 LLM 调用）和 M11（跨论文集成）之后重新 review。

## 设计哲学

借鉴 Claude Code 的三条工程原则：

1. **Harness is everything, trust the model.** 脚手架做到位，不过度 prompt
   调优。模型会进步，脚手架该删就删。
2. **Radical simplicity.** 主 loop 单线程、subagent 单向派发、不做 multi-agent
   编排。用可调试性换掉复杂度。
3. **Local-first, file-as-source-of-truth.** 所有状态以人类可读文件形式落盘
   （JSONL、markdown），用户可以 cat / grep / git diff。

## 目标规模

锚定 **50-100 篇论文的个人知识库**。所有技术选型都在这个规模下优化：
不做分布式、不做多租户、不做 > 500 篇规模的索引优化。

## 顶层模块

```
src/paper_copilot/
├── cli/          # 命令行入口（Typer）
├── agents/       # Agent loop + subagents
├── schemas/      # Pydantic 模型，结构化输出契约
├── session/      # JSONL session tree 读写
├── retrieval/    # 单论文内 chunk 检索（深挖用）
├── knowledge/    # 跨论文索引与检索（结构化字段 + 语义）
├── eval/         # 回归测试框架（M5 之后才开始写）
└── shared/       # 通用工具：logging、cost tracker、cache helpers
```

## 模块职责

### `cli/`
用户面。接收命令（`read` / `compare` / `search` / `reindex` / `eval run` /
`doctor`），把参数组装成 agents 的输入，流式打印结果。不含业务逻辑，
不直接读写 session 文件。

### `agents/`
项目的核心。包含：

- **MainAgent**：主 loop，async generator 写法。三种终止信号：
  `end_turn` / `max_turns` / `max_budget_usd`。负责派发 subagent、
  聚合结果、生成最终结构化报告。
- **SkimAgent**：快速扫读整篇论文，产出"结构路标"（章节、图表位置、
  核心术语）。上下文小。SkimAgent 是叶子 agent，直接调 llm_client.generate，
  不走 run_agent_loop——tool_use 仅作结构化输出通道，无真实 tool execution
  需要循环。DeepAgent 才是 loop 的首个真实消费者。
- **DeepAgent**：针对 MainAgent 指定的页/章节做深读，产出具体的
  Contribution / Method / Experiment / Limitation 字段。可并发多实例。
- **RelatedAgent**（M11 引入）：在 `read` 流程中被 MainAgent 派发，
  基于新论文的初步结构化字段，查 knowledge 索引找出库里最相关的 3 篇，
  产出跨论文对比字段（CrossPaperLink）。

Subagent 的关键约束：**只返回一条结构化结果给 MainAgent，不暴露自己的
完整对话历史**。这是防止主上下文被 subagent 的 tool output 污染。

### `schemas/`
所有结构化输出的 Pydantic 模型：`Paper`、`Contribution`、`Method`、
`Experiment`、`Limitation`、`CrossPaperLink`。

约定：**任何跨模块传递的 LLM 产出必须经过 schema 校验**。schema 校验失败
自动 retry 一次，仍失败降级为"自由文本 + warning"写入 session。

### `session/`
JSONL session tree 的读写。一个 session = 一篇论文的完整分析过程。

文件布局：

```
~/.paper-copilot/
├── papers/
│   ├── <paper_id>/
│   │   ├── source.pdf              # 原始 PDF
│   │   ├── session.jsonl           # 主 session（树形）
│   │   └── chunks/                 # 分块文本（单篇 retrieval 用）
│   └── ...
├── index/                          # 跨论文索引（knowledge 模块拥有）
│   ├── embeddings.db               # sqlite-vec：跨论文向量索引
│   ├── fields.db                   # sqlite：结构化字段索引
│   └── meta.json                   # embedding 模型版本、reindex 时间
├── graph/
│   └── cross-paper-links.jsonl     # 跨论文关联（CrossPaperLink 落盘）
└── eval/
    ├── goldens/                    # 被标记为 ground truth 的 session
    └── runs/<timestamp>.jsonl      # eval 历史运行结果
```

Session JSONL 结构（借鉴 OpenClaw）：
- 第一行：`{type: "session", id, paper_id, cwd, timestamp, model}`
- 后续行：`{id, parent_id, type, ...}`，type ∈ {message, tool_result,
  compaction, branch_summary, schema_validation}
- Append-only，崩溃最多丢一行。

这个模块是**其他所有模块的底层存储 API**，它只关心"怎么存/读 JSONL"，
不关心 agent 或 schema 语义。

### `retrieval/`
**仅用于单篇论文内部**的 chunk 检索（给 DeepAgent 用）。

流程：PDF → chunks → embedding → 存到单论文的 `chunks/` 目录。
DeepAgent 通过 query 拿到 top-k chunk + 页码。

**刻意与 `knowledge/` 分开**：单篇检索的 query 来自 MainAgent 的深读意图
（"methodology section 的数学定义"），跨论文检索的 query 来自用户或
结构化字段匹配，两者生命周期、更新频率、查询 pattern 都不同。

**M7 实际状态**：仅实现了 `split_by_sections`（按 Skeleton 章节切出
全文文本）。`chunker.py`（embedding 分块）和 `search.py`（sqlite-vec +
bge-m3 检索）推迟到 Phase 2 信号驱动再加——M7 三篇 reality check 下
DeepAgent 全文投喂成本 ¥0.05-0.11/篇，未触及 ¥0.30 预算，retrieval
未证明必要。

### `knowledge/`
跨论文索引与检索。三个职责：

1. **字段索引维护**：每次 `read` 完成后，把 Paper 的结构化字段
   （Contribution/Method/Experiment/Limitation）写入 `fields.db`。
   支持 SQL-like 查询（"所有 Method 包含 'contrastive' 的论文"）。
2. **向量索引维护**：把每篇论文的 chunks 同步到 `embeddings.db`（除了
   单篇内部使用外，也作为跨论文语义检索的底层）。带 paper_id 分区，
   支持"在 N 篇候选中检索"的过滤。
3. **Hybrid 检索接口**：给 agents 和 cli 用。输入是 query + 可选的字段过滤
   （如"只查 NLP 类论文"），输出是 top-k 论文 + 每篇的相关 chunk + 结构化
   字段摘要。内部流程：字段过滤 → 向量 top-k → 轻量重排。

**embedding 模型锁定** `bge-m3`（中英双语、开源、本地可跑）。meta.json
记录当前使用的模型 + 版本号；换模型需要 `paper-copilot reindex` 重建。
**不支持多 embedding 共存**（存储翻倍、索引复杂，不值得）。

**MVP 阶段只做 hybrid 检索**，不做重排器（重排器是进阶）。

**M10 实际状态(2026-04-24)**:fields.db 已落地,走**单表 JSON + 表达式
索引**(`papers(paper_id, indexed_at, data)` + `json_extract($.meta.year)` /
`$.meta.arxiv_id` 两个表达式索引)。数组子串查询(method contains X)走
`json_each` 内联扫描。13 篇规模下全部查询 < 1ms(DoD 阈 50ms,50x 余量),
FTS5 推迟到 ~1k 篇阈值触发再加。`fields_store.upsert` 只存 raw JSON 不
二次校验 → M7 旧 schema 的 `meta.id` 残留字段天然兼容,代价是不能直接
从 fields.db 反序列回 `Paper` 对象;如未来要支持"从历史 session 重建
Paper",需单写 migration。

**M11 实际状态(2026-04-24)**:embeddings.db + hybrid_search 落地。
`chunks(chunk_id, paper_id, ord, section, page_start, page_end, text)` +
`vec_chunks` (sqlite-vec vec0,float[1024]) 共享 chunk_id / rowid;KNN
查询 `MATCH ? AND k = ?` + 可选 `rowid IN (SELECT chunk_id FROM chunks
WHERE paper_id IN (...))` 子查询做预过滤。hybrid_search 算法:
field_filter(year / contains)→候选 paper_ids→KNN 取 k*5 chunks→按
paper_id 取 best chunk→top-k。**不做重排器**(MVP)。chunker 进
`shared/chunking.py`(纯函数,tokenizer 注入),`retrieval/`↔`knowledge/`
互不 import 的硬规则下,section→chunk 是兄弟模块共享原语。历史 session
不记录 PDF 路径 → `reindex --pdf-dir <dir>` 按 sha1 paper_id 重新匹配,
`emit_skim` tool_use 里恢复 PaperSkeleton,零 LLM 成本重建两个索引。
模型 / dim 不匹配在 `embeddings_meta.json` 开门校验,早 fail 避免脏距离。
13 篇实测:reindex 186.9s(DoD < 5min,2.7x 余量)、search warm 287-973ms
(DoD < 1s);冷启动 17s 是 torch import + 模型权重加载的固有代价,CLI
一次性 invoke 吞。

### `eval/`
内部 eval 模块。Goldens 是字段级快照(不是 session 级标记),suite 跑
MainAgent 重读对比。

**M14 v1 落地**:

- `goldens.py` — `eval/goldens/<paper_id>_<field>.json` 一篇一字段一文件
  (仓库内,纳入 git)。`mark_from_session` 直接读 session.jsonl 的最近
  `final_output`,不读 fields.db(后者会被 reindex 改写,不是真值)。
  支持字段:meta / contributions / methods / experiments(limitations
  / cross_paper_links 故意不支持,见 assertions 节)。
- `suite.py` — Pydantic Suite/PaperSpec/BudgetPerPaper schema,YAML
  入。每个 paper 跑 MainAgent.run 前先校 `compute_paper_id(pdf) ==
  paper_id`(防 PDF 换路径),再用 tmpdir 当 PAPER_COPILOT_HOME 起隔离
  run(RelatedAgent 自动短路,用户的真索引不动,suite 可重复)。
- `assertions.py` — 纯函数,JSON dict in / `FieldFailure` list out。
- `cli/commands/eval.py` — `eval mark` / `eval run` / `eval report`,
  `run` 按结果 exit 0/1 并默认 record 一份 run 历史(`--no-record` 可关)。
- `eval/suites/smoke.yaml` — 5 篇 × 2 字段示例 suite,绝对预算 cap
  (¥0.20 / 180s 每篇)。

**断言策略**(M14 实测校准过的 noise floor):

| 字段 | 触发 fail 的条件 |
|---|---|
| meta | title / year / arxiv_id 严格相等;authors 长度匹配 |
| methods | 长度 < golden × 50%(灾难性下降) |
| contributions | 长度 < golden × 50% |
| experiments | (dataset, metric) 对齐每个 golden 必须出现 |
| budget(suite 配) | cost / latency 超 YAML 绝对 cap |

**故意丢掉的断言**(noise floor 太高 → 假阳性):

- methods name 对齐(LLM 跨次重命名:`Residual Learning Framework` ↔
  `Residual Block`)
- `is_novel_to_this_paper`(同 prompt 同模型也随机翻转,M8 教训重现)
- contribution `type` 计数(同样跨次漂移)
- limitations(无稳定结构 key)
- cross_paper_links(tmpdir 隔离下永远空)

**永不做**:LLM-as-judge(架构红线)。

**M15 Session A 落地**(2026-04-27,趋势可视化解决 noise floor):

- `runs.py` — `RunRow` 扁平 schema(每行 = 一个 (run_id, paper_id, field)),
  `write_run(SuiteResult)` 落 `eval/runs/<run_id>.jsonl`,`load_history`
  读最近 N 个文件并按 `suite_name` 切片。**先 filter 再 truncate** 是
  关键(否则 last=2 在最后两个 deep run 上 filter smoke 会得 0 行)。
  `cache_hit_ratio = cache_read / (input + cache_read + cache_create)`
  按 disjoint 计费拍。`run_id` 用 `2026-04-27T15-30-45Z` 文件名安全格式,
  字典序 = 时间序。
- `report.py` — 纯 stdlib 手搓 SVG,800x280 画布、polyline + circle marker
  + 5 档 Y 轴网格 + `<title>` SVG tooltip,**零 JS / 零图表库依赖**。
  三张图:per-field PASS rate、per-paper cost (¥)、per-paper cache-hit
  ratio。顶部 markdown 摘要 diff 最近一次 vs 上一次:PASS 翻转(↗/↘)、
  cost drift > ±10%、cache drift > ±10%。空状态(无 run 历史)给 hint
  指向 `eval run`。
- **解决了什么**:M14 实测出 LLM noise floor 高 → 单跑 PASS/FAIL 是
  二元噪声(同 prompt 同模型也会 4/5 vs 5/5 抖)。趋势图把"一根锯齿"
  vs"整条断崖"画出来,肉眼可分 noise vs catastrophic regression。
  Session A 实测 6 跑(5 baseline + 1 故意 degrade)恰好踩到这两种
  情况,DoD 三条第一条 ✅。
- **没做什么**:multi-run majority-vote golden、schema confidence 字段、
  HTML 交互式滚动/筛选。M14 节末提到的"M15 该做什么"三选一在 Session A
  时刻被趋势图替代(更便宜:每篇跑 5 次 vs 一次跑 5 篇,数学等价但
  不需要重标 golden)。

**M15 Session B 落地**(2026-04-27,把 eval 当真实决策的裁判):

- 候选 qwen3.6-plus(snapshot 2026-04-02),百炼定价 2.0/2.5/0.2/12.0
  CNY per Mtok,跨四档统一 1.67x flash。配套基础设施:`shared/cost.py`
  加 `QwenPlusPricing` + `Pricing` union + `pricing_for_model(model)` 路由
  (prefix match,fail-loud on unknown);`agents/main.py`
  `CostTracker(pricing=pricing_for_model(DEFAULT_MODEL))` 一行接入。这部分
  留下,**未来切换零摩擦的真实必需**,不算 Session B 一次性脚手架。
- 跑法:`DEFAULT_MODEL = "qwen3.6-plus"` 一行临时改 + `smoke.yaml` budget
  cap 0.20 → 0.50。一次 `eval run` 落第 7 个 run row,跑完两条临时改全部
  还原。
- 结果:5/5 PASS、0 regression。但 cost ¥0.273 → ¥0.553(**2.03x**,大于
  价格比 1.67x → 说明 plus 输出更长 ~22%),latency 124s → 274s(**2.22x**,
  大于 cost ratio → plus 每 token 也更慢),cache 冷启等同 baseline run 1。
- 决策:**继续用 flash**。eval 颗粒度看不出 plus 有质量上行(M14 收到
  catastrophic-class noise floor 之后只能看出"都过线"),2x cost / 2.2x
  latency 在零可测收益时不成立。
- **Session B 比 Session A 更接近真实工程判断**:Session A run 6 摆拍证明
  探测器对已知断崖有响应(必要但 reader 一眼看穿);Session B 让 eval 当
  裁判,**用数据否决了一次本来会过 0 regression 关的升级**——这才是 eval
  系统的真实价值。决策 story `docs/stories/2026-04-27-model-selection-flash-vs-plus.md`。
- **Cross-run cache 比较的陷阱**:baseline runs 2-5 是同 model 连跑前次
  system+tools 仍在 5min TTL 内复用,plus run 7 是该 model 首次冷启。直
  接平均会读出"模型切换降 cache"的假规律,正确对比是 candidate run 1 vs
  baseline run 1。

**M5 之前这个模块只有空目录 + README;M14 是 v1 有产出但有限;
M15 Session A 把"信号 vs 噪声"可视化做出来,Session B 用 eval 数据驱动
了一次真实模型选型决策并落 story 简历可见。**

### `shared/`
- `logging.py`：统一结构化日志（JSON 格式，落盘 + 终端美化）
- `cost.py`：Cost tracker,按 session 累计 input/output/cached token。
  支持多 tier 计费(`QwenFlashPricing` + `QwenPlusPricing`),`pricing_for_model(model)`
  按 model id 前缀路由(M15 Session B)
- `cache.py`：Prompt cache 辅助（layer 打标、边界插入）
- `errors.py`：统一异常基类
- `jsonschema.py`：JSON Schema 工具。当前提供 `inline_refs`，把 Pydantic
  生成的 `$defs` + `$ref` schema 展开成扁平形态后作为 LLM tool input_schema。
  存在理由：qwen3.6-flash 在 Anthropic 兼容端点下对 `$ref` 处理不可靠（会
  返回字符串化的嵌套对象而不是真 dict），见 M5 待验证假设。未来换 provider
  或模型升级后重新评估是否可移除。

## 模块依赖方向

```
               cli
                │
                ▼
            agents  ◄────────── schemas
                │
     ┌──────────┼──────────┐
     ▼          ▼          ▼
  session   retrieval   knowledge
     │                      │
     └──────────┬───────────┘
                ▼
              shared

eval ──► agents (仅公开 run 入口), session, schemas, knowledge, shared
         (不碰 agents 内部；不依赖 retrieval, cli)
```

**硬性规则**：

- `session/`、`retrieval/`、`knowledge/`、`shared/` **不能**反向 import
  `agents/` 或 `cli/`
- `schemas/` **不能** import 任何其他模块（它只定义数据结构）
- `retrieval/` 和 `knowledge/` 之间**不能**互相 import——它们是兄弟模块，
  共享的只有 `shared/` 里的 embedding util
- `eval/` 可以调用 `agents/` 的**公开 run 入口**（这样 eval 强制 dogfood
  主功能，见用例 4），但不能 import `agents/` 的内部模块；此外只消费
  `session/`、`schemas/`、`knowledge/`、`shared/` 的公开接口，不依赖
  `retrieval/` 和 `cli/`——这样 extractor 内部重构时 eval 不被拖累

违反以上任何一条都是代码 review 的 blocker。

## 模型分配

所有 agent——MainAgent / SkimAgent / DeepAgent / RelatedAgent，以及
query rewrite / chunk rerank 等子任务——统一使用 **qwen3.6-flash**，
**不做模型分层**。具体 model id 在 `agents/llm_client.py` 里一处收敛。

- **端点**：`https://dashscope.aliyuncs.com/apps/anthropic`
  （阿里云百炼提供的 Anthropic API 兼容网关）
- **SDK**：继续用 `anthropic` Python SDK，只替换 `base_url` 和 API key，
  请求/响应格式、tool use、`cache_control` 语义复用原生 Anthropic 的约定
- **cost 参考**：单篇一次 `read` 端到端约 **¥0.2**，数字会在 M7 跑真数据
  后校准
- **为什么不做分层**：Sonnet / Haiku 分层的意义在 Anthropic 原生生态
  （价格差 ~5×）才成立；qwen3.6-flash 在 flash 档位价格已经足够便宜，
  分层带来的实现复杂度不值
- **2026-04-27 M15 Session B 复核**:把 `DEFAULT_MODEL` 临时切到 qwen3.6-plus
  跑一次 `eval run smoke.yaml`,实测 plus **2.03x cost / 2.22x latency / 0
  quality 上行**(eval 颗粒度看不出 plus 比 flash 更好,M14 noise floor
  之后只能看出"都过线")。**用数据否决了一次本来会过 0 regression 关的升
  级**,继续用 flash。多 tier 计费基础设施(`QwenPlusPricing` +
  `pricing_for_model()`)留下供下次切换零摩擦。详细数据 + 触发重评条件见
  `docs/stories/2026-04-27-model-selection-flash-vs-plus.md`。

`CLAUDE.md` 的 "Cost discipline" 只保留操作规则（所有 LLM 调用必须走
`agents/llm_client.py` 等），不再重复默认——此节为单一真源。

## 关键数据流

### 用例 1：`paper-copilot read <pdf_path>`

```
cli.read
  → agents.MainAgent.run(paper_id)                     # 启动主 loop
      → session.create_session(paper_id)               # 创建 JSONL 文件
      → spawn SkimAgent(pdf_path)                      # 独立上下文
          ← 返回 Paper.skeleton                        # 章节结构
      → for each section worth deep-reading:
          spawn DeepAgent(pdf_path, section)           # 独立上下文，可并发
              ← 使用 retrieval 获取单篇内 chunk
              ← 返回 Contribution/Method/...           # schema 校验
      → aggregate into Paper (初步版本)
      → spawn RelatedAgent(paper_draft)                # M11 新增
          ← 用 knowledge.hybrid_search 找库里相关 3 篇
          ← 返回 CrossPaperLink[]
      → merge into Paper (最终版本)
      → schemas.Paper.model_validate(result)           # 终检
      → session.append_final(paper)                    # 落盘
      → knowledge.index_paper(paper)                   # 更新跨论文索引
  → cli prints markdown report（含跨论文关联）
```

每一步的中间产物都写入 `session.jsonl`，不因为失败丢失。

### 用例 2：`paper-copilot compare <paper_id_A> <paper_id_B>`

```
cli.compare
  → 直接从 knowledge.fields.db 读两篇的结构化字段    # 不走 agent
  → 格式化为对比表（markdown）
  → 可选：如果用户加 --deep，派 MainAgent 做补充分析
  → cli prints table
```

**note**：compare 的 MVP 不跑 LLM，只基于已落盘的结构化字段。这既是
dogfood "我们的结构化抽取是有价值的"，也省成本。

### 用例 3：`paper-copilot search "<query>"`

```
cli.search
  → knowledge.hybrid_search(query, filters)
      → 字段过滤（如 --year 2023+，--topic nlp）
      → 向量 top-k in embeddings.db（带 paper_id 分区）
      → 按论文聚合：同一篇的多个 chunk 合并，保留最相关片段
  → cli prints: 论文列表 + 每篇的相关段落 + 结构化字段摘要
```

### 用例 4：`paper-copilot eval run <suite.yml>`

```
cli.eval_run
  → eval.SuiteRunner.run(suite)
      → for each test case:
          → load golden from session.load_golden(paper_id, field)
          → call agents.MainAgent (same as use case 1)    # 产出新结果
          → eval.assertions.compare(actual, golden)
          → record to runs/<timestamp>.jsonl
      → eval.report.generate_html()
  → cli prints summary + opens HTML
```

注意 eval 路径**完全复用**主功能的 agent loop，不另开一套——这是
"eval 必须 dogfood 主功能"的设计。

### 用例 5：`paper-copilot reindex`

```
cli.reindex
  → knowledge.rebuild_index()
      → 读 meta.json 判断当前 embedding 模型
      → 如果模型变了：备份旧 index 到 index/.backup/<timestamp>/
      → 遍历 papers/*/chunks/*，重算 embedding，写入新 embeddings.db
      → 从 session.jsonl 重建 fields.db
      → 更新 meta.json
  → cli prints 进度条 + 总耗时
```

## 取舍说明（面试官爱问的）

### 为什么单线程 async generator，不用 LangGraph 或其他框架？

- **Generator 给了三件事**：自然 backpressure、语言级取消（`.athrow()`）、
  类型化终止状态。callback/EventEmitter 做不到。
- **LangGraph 是状态机**，适合"审批 / 分支 / 人机交互"复杂流程，不适合
  "迭代调 tool 直到完成"这种简单循环——用了反而加复杂度。
- **后续可能引入 LangGraph**：如果 eval 里要加"人工 review → 决定 merge /
  reject" 的 approval 流程，那时考虑。

### 为什么是 subagent 而不是 one big prompt？

- 50 页论文塞进 one prompt 会让主上下文充满 PDF 原文，压缩/缓存/后续追问
  都变差。
- Subagent 主要是**上下文隔离手段**，不是并行手段（虽然顺便获得了并发）。
- 参考 Claude Code 的 LMCache 实测：3 个 Explore subagent 并发，主上下文
  从 ~200K 降到 ~20K。

### 为什么 JSONL 而不是 SQLite（指 session 存储）？

- **Append-only 崩溃安全**：进程崩了最多丢最后一行，比事务更硬。
- **人类可读**：我自己 debug 时可以 `tail -f` 看 agent 在干嘛。
- **Git 友好**：未来如果想 version control session 可以直接 diff。
- **代价**：查询性能差。这就是为什么 `knowledge/` 用 SQLite——
  **冷存储用 JSONL（session），热查询用 SQLite（index）**，分层清晰。

### 为什么 `retrieval/` 和 `knowledge/` 要分开？

- **生命周期不同**：`retrieval/` 的 chunk 只在当前 session 用完即走，
  `knowledge/` 的 index 是累积的、跨 session 的。
- **查询 pattern 不同**：单篇检索由 DeepAgent 用结构化意图驱动
  （"取 methodology section 的数学定义"），跨论文检索是用户或 RelatedAgent
  用自然语言查询。
- **失败 blast radius 不同**：单篇 chunk 损坏只影响当前论文，跨论文 index
  损坏影响全库——两者的备份、校验、重建策略不同。
- **不这么分的代价**：未来想独立优化跨论文检索（比如加重排、加缓存），
  会被单篇检索的逻辑拖累。

### 为什么锁定 embedding 模型，不支持多模型共存？

- **多模型共存**意味着每个 chunk 有 N 个 embedding，存储成本 × N，索引
  复杂度也 × N。
- **换模型是低频操作**（一年可能换 0-1 次），为这个低频操作付高频成本不划算。
- **解决方案是 `reindex` 命令**：一次性重建。100 篇论文 × 200 chunks ×
  1024-dim embedding，bge-m3 在 M1 Mac 上预期 < 10 分钟跑完。可接受。
- **meta.json 记录当前模型**：防止误用（模型不匹配直接报错）。

### 为什么 compare 命令不走 LLM？

- 如果结构化抽取做得好，对比两篇论文的 Method 字段是 SQL 层的事，不需要
  再调一次模型。
- 这也是对自己的**dogfood 压力**：如果 compare 的输出不够好，说明结构化
  抽取有问题，应该回去改 DeepAgent，而不是用 LLM 掩盖。
- 加 `--deep` flag 给用户"我还想要 LLM 进一步对比"的逃生口。

### 为什么不做 LLM-as-judge？

- 我的 eval 场景（structured paper extraction）字段都可以用 schema +
  field match 判对错，不需要 judge。
- Judge 本身有 bias，做好要跑 kappa 校准，成本过高。
- 未来如果加"summary 质量"这种无法结构化评测的字段，再考虑。

## 待验证的假设（M5 / M11 后重新审视）

**M5 已验证**：
- [x] SkimAgent 不需要 retrieval，只靠 PDF 前几页 + 目录就够
      — 三篇 reality check（transformer / vit / vilbert）用 3 页 front-matter
      + pymupdf 内嵌 outline 抽 PaperMeta + PaperSkeleton 全部通过，单篇
      成本 ¥0.01–0.015。
      **M8 修正（2026-04-24）**：前提是 PDF 有 embedded outline。
      Phase 2 的 Zhou 2006 NIPS（无 bookmarks）暴露:3 页前缀对无 outline
      的 PDF 远远不够——Skim 只能推断出前 3 页的 section,Deep 后续按
      该残缺 outline 切片,导致后半论文从未进入模型。现在 `skim.py` 分
      两个常量：`_FRONT_MATTER_PAGES_WITH_OUTLINE = 3` 和
      `_FRONT_MATTER_PAGES_WITHOUT_OUTLINE = 8`。对真正无 outline 的长论文
      仍可能不够，M14 eval 重新评估。
- [x] Pydantic Field description 作为 prompt 片段的有效性
      — M4 的设计赌注"description 写得好模型就懂"，M5 三篇全程未使用任何
      few-shot example，仅靠 description 措辞（尤其 arxiv_id 的
      "Copy EXACTLY"、SectionMarker.title 的 "no normalization"、
      page_end 的 "Do not guess"）就让模型行为稳定到 3/3 reality check
      通过。未来 prompt iteration 的第一优先级是改 description，不是
      加 system prompt 或 few-shot。
      **M8 修正（2026-04-24）**：description 对**模板型幻觉**有硬上限。
      Phase 2 的 "low-resource languages" 模板命中 4/13 (FaceNet/LeNet/
      AlexNet/ViLBERT)，"Not stated but likely:" 4/13。M8 在
      `Limitation.description` 加反例后:"Not stated but likely:" 前缀
      完全消失 ✓,但 AlexNet 把"low-resource languages"变形为"English-
      language visual object recognition tasks"(图片数据没语言这件事
      LLM 依然套模板)。结论:description 能杀"字面匹配"的模板,杀不掉
      "语义变体"。后者需要 retry / validator / output filter 类硬机制
      (M9+ 候选,非 prompt 层)。类似地,`Contribution.confidence` 从
      float(0-1) 换成 `evidence_type` enum 后,字段使用从 79% clumping
      到 1.0 变成结构化 3 档,证明**对于刻度型字段,enum > 数值 +
      description 锚点**。

**M5 推迟到后续 milestone 再验**（原 M5 那组里不属于 SkimAgent 单点能验的）：
- [x] sqlite-vec 够用，不需要独立向量库 — **M11 验证通过(2026-04-24)**:
      13 篇 / 621 chunks 规模下 KNN + rowid 子查询预过滤 warm 287-973ms,
      远低于 DoD 1s。单表结构化 chunks + `vec0` 虚表共享 rowid,复合
      过滤不用学 vec0 DSL。50-100 篇规模的正式验证留给 M14 eval。
- [ ] 单篇论文 chunk 50-200 个，top-k=5 够用 — 单篇 retrieval 仍推迟
      (M7 信号未出现,见 `retrieval/` 节)
- [ ] Claude Haiku 做 query rewriting 足够，不用 Opus — M7/M8
- [x] Prompt cache 命中率能到 60%+ — **M9 打脸**:qwen-flash +
      Dashscope 架构下 user-message cache 有**未公开的 ~5K token 大小
      上限**,Skim 的 4K user 块能全命中,Deep 的 18K user 块打 marker 反而
      被按 125% 创建费扣钱却永远读不出来。现状:Skim 三层 marker 全打,
      Deep 只打 system+tools(~2809 tokens)。同 paper rerun 成本下降上限
      ~19%,跨 paper 命中率上限 ~14-19%。原 60% 目标在当前模型+供应商组合
      下**架构性够不到**,已把 TASKS.md M9 DoD 改成 ≥15%。触发重验条件:
      qwen 版本升级 / 切到其他兼容层 / DeepAgent 改 per-field fan-out
      让单调用 user 块缩到 5K 以内。回归脚本:`scripts/m9_cache_ab.py`
- [x] DeepAgent 每字段一个独立实例 vs 一个实例输出多字段——哪种准确率更高 — M7
      — 选了"一个实例输出四个 list"的聚合方案（D2 决策）。Transformer/ViT/
      ViLBERT 三篇 reality check 下 schema validation 全通过，字段数量
      合理（5-6/3-5/4-12/3-4），cost 线性、稳定。per-field fan-out 留
      作 Phase 2 若质量下降的 fallback

**M5 过程中新暴露的假设**（原列表没有，由 reality check 产出）：
- [x] qwen3.6-flash 对 Pydantic 嵌套 schema 的 `$defs` + `$ref` 处理不可靠：
      schema 会被 HTTP 层接受，但返回的 `tool_use.input` 中被 `$ref` 引用
      的嵌套 object 字段会被字符串化成 JSON 字符串而不是真 dict。落地
      `shared/jsonschema.inline_refs` 作为 workaround，SkimAgent 三篇嵌套
      字段全部为真 dict。未来触发重新评估的条件:
      (a) qwen 模型版本升级（qwen3.7 / qwen4）
      (b) 切换到 Anthropic 原生或其他兼容层
      (c) M7 DeepAgent 的嵌套 schema 更深（>2 层）时，先不假设 inline_refs
          继续有效，用 scratch 重跑 Step 3 里那种 toy 验证
      触发时重跑 `/tmp/step3_scratch.py` 的 Call 2 模式。
- [x] qwen3.6-flash 对 `arxiv_id` 字段有"自动清洗"倾向（输入
      `arXiv:1706.03762v7` 会自作主张返回 `1706.03762`）：通过 Field
      description 中 "Copy the string EXACTLY" 措辞 + Python 侧
      `_normalize_arxiv_id` regex 归一化压制，三篇 3/3 原样输出,归一化
      在 Python 侧集中完成。
- [ ] arxiv API metadata 能否可靠补齐 PaperMeta 的 canonical 字段
      （title canonical capitalization、venue） — M8 验。
      M5 暴露两处 PDF 纸面无法覆盖的场景:vit 封面印刷全大写
      （"AN IMAGE IS WORTH..." vs canonical mixed-case），vilbert 作为
      2019 年 arxiv 首版不印 venue（`venue=null` 而非 "NeurIPS 2019"）。
      两处均**非 SkimAgent 抽取错误**——模型忠实于 PDF 原样 + 按 schema
      description 对 preprint 填 null——而是 PDF-only 信息源的固有缺口，
      需外部 enrichment。（与 M11 组 "Method.name 跨论文对齐" 是同类问题：
      都是"PDF 原样 vs canonical 形态"的落差，解法可能共享一个
      canonicalization 层。）

**M6 过程中新暴露的假设**：
- [x] qwen3.6-flash 在 forced `tool_choice={"type":"tool",...}` 下不返回
      TextBlock，只返回 tool_use 块。影响：session.jsonl 的 message(assistant)
      entry 在 SkimAgent 场景下常态缺位；M7 DeepAgent 若同样用 forced tool，
      M9 prompt cache 分层需以 tool_use 为边界而非 assistant turn 边界。

**M9 过程中新暴露的假设**（2026-04-24 实测产出）：
- [x] Dashscope 百炼 Anthropic-compat 对 `cache_control: ephemeral` 的
      **user-message 块存在未公开的大小阈值**（实测约 ~5K tokens)。
      超过阈值的 user 块,SDK/HTTP 层接受 marker 并按 125% 的"创建费"
      计账（`cache_creation_input_tokens` 被报回去）,但下次请求命中不到
      (连续 4 次 rerun 内 `cache_read_input_tokens` 恒为 system+tools 那
      2809 不动)。**净亏**,且官方文档未提（"无最大 cache block"）。
      落地 workaround:Skim (user ~4K,在阈值内) 三层 marker 全打,
      Deep (user ~18K) 只打 system+tools,user 不打。触发重验条件:
      (a) qwen 模型版本升级 — 阈值可能变
      (b) 切换到 Anthropic 原生端点 — 那边应当无此限制
      (c) DeepAgent 改 per-field fan-out 让单调用 user 块 < 5K
      重验方法:`scripts/m9_cache_ab.py on|off` 两两对比 cache_read/create。

**M11 之后审视（跨论文相关）**：
- [~] bge-m3 在论文语料上的召回率够用（否则考虑换 voyage-3-large 等 API）
      — **初步通过(2026-04-24)**:7 个真实 query 手工验证,rank-1 命中符合
      预期("triplet loss for face recognition"→FaceNet、"attention"+year=2017
      →Attention Is All You Need、"vision language pretraining multimodal"
      →ViLBERT)。样本太小,正式召回率要等 M14 golden suite。
- [~] 50-100 篇规模下，sqlite-vec 的跨库检索 < 500ms
      — 13 篇下 warm 287-973ms;50-100 篇规模无实测,sqlite-vec 线性扫描
      复杂度下预估仍远低于 1s,M14 eval 时正式验。
- [x] RelatedAgent 的自动关联粒度：整篇 vs 章节 vs 方法级？
      — **M12 决定整篇粒度(2026-04-25)**:`CrossPaperLink` 描述新论文
      到候选论文的整篇关系(`relation_type` 5 档 enum + explanation),
      不切到 method/section 级。理由:章节级关联会强迫 LLM 在 ~2K-token
      payload 里推理多对多,Phase 2 13 篇规模 + qwen-flash 输出稳定性
      要求下不划算;真要章节级先靠 `compare` 命令 dogfood。M14 golden
      时如果出现"两篇方法 X 类似但其它无关"的 case 再考虑细粒度。
- [x] fields.db 的 SQL schema：结构化字段能否用 JSON column + 表达式索引
      解决，不需要正则化成多表 — **M10 验证通过(2026-04-24)**:单表
      `papers(paper_id, indexed_at, data TEXT)` + 两个 `json_extract`
      表达式索引(year / arxiv_id),数组子串查询走 `json_each`。13 篇
      实测所有查询 < 1ms(DoD 50ms)。schema 加字段无需 ALTER TABLE —
      raw JSON 存 Paper,新字段自动流入。未来重验条件:
      (a) 库 > 1k 篇时 LIKE 是否需切 FTS5
      (b) 新增 author / venue 查询维度时,`json_each` 扫描成本是否显著
- [x] `read` 流程新增跨论文步骤后，端到端延迟能否控制在 90s 内
      — M11 `read` 末尾只加 "split_by_sections + chunk + encode + upsert"
      这一段,ViLBERT 实测加起来 ~5-10s(CPU bge-m3),远低于 90s。
      **M12 加 RelatedAgent 后(2026-04-25)**:Bahdanau --force 重读
      RelatedAgent 段 latency 2.1s(query encode + KNN + 1 次 LLM 调用),
      端到端总耗时仍在 30-60s 量级,DoD 满足。
- [ ] `Method.name` 跨论文对齐：是否需要 canonicalization 层（同义词合并、
      小写归一），还是靠 embedding 相似度在查询时处理？

## 不会做的事（再次强调）

- 不做 multi-agent 协商 / 对话
- 不做分布式 / 多机
- 不做用户认证 / 权限
- 不做自定义 embedding model
- **不做 > 500 篇规模的索引优化**（超出个人项目范围）
- **不做图谱遍历 / 引用链分析**（entity resolution 是另一个领域）
- 不做 PDF 图表的 CV 理解
- 不做实时 web UI（HTML 报告够了）
- 不支持多 embedding 模型共存