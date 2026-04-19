# TASKS

> 状态：活文档。每完成一个 milestone 勾掉 + 简短标注"实际遇到的问题"，
> 给未来的自己和简历叙事留证据。
>
> 每个 milestone 包含：目标 / 产出 / 依赖 / DoD（Definition of Done）/
> 预估 session 数。

---

## Phase 0: 地基（M1-M3）

### M1: 项目骨架

**目标**：项目可以跑 `uv run pytest`、`uv run ruff check .`、`uv run mypy src/`
三条命令都不报错。

**产出**：
- `pyproject.toml` 完整配置（ruff/mypy/pytest 所有 section）
- `src/paper_copilot/` 下所有子模块的空 `__init__.py`
- 一个 `tests/test_smoke.py`，只有 `def test_import(): import paper_copilot`
- `Makefile`：至少 `test` / `lint` / `format` / `typecheck` 四条
- `.pre-commit-config.yaml`（可选，推荐）

**依赖**：无（项目起点）

**DoD**：
- [ ] `uv run pytest` → 1 passed
- [ ] `uv run ruff check .` → 0 errors
- [ ] `uv run mypy src/` → 0 errors
- [ ] `make test` 可用

**预估**：1 session。

---

### M2: 基础设施—logging、errors、cost tracker

**目标**：`shared/` 模块的三个基础工具可用，被后续所有模块依赖。

**产出**：
- `shared/logging.py`：基于 `structlog` 或 `rich` 的结构化日志。
  支持同时输出到终端（美化）和 JSONL 文件（`~/.paper-copilot/logs/`）。
- `shared/errors.py`：异常基类 `PaperCopilotError`，及子类：
  `AgentError` / `SchemaValidationError` / `RetrievalError` /
  `KnowledgeError` / `SessionError`。
- `shared/cost.py`：`CostTracker` 类。按 session 累计 input/output/cached
  token 和 USD。支持以 context manager 使用。
- 每个都有对应单测。

**依赖**：M1

**DoD**：
- [ ] 所有 public class/function 有 type hint 和 docstring
- [ ] 单测覆盖率 > 80%
- [ ] `rich` 终端输出可读（至少试跑一次看效果）
- [ ] CostTracker 能正确处理 Anthropic API 响应的 `usage` 字段结构

**预估**：1-2 sessions。

**note**：cost tracker 的 API 先支持 Anthropic messages API 兼容格式
（覆盖 Anthropic 原生端点和百炼 Anthropic 兼容端点），**不要泛化成多
provider**。后面真要加 OpenAI 时再重构。

---

### M3: Agent loop 骨架（mock LLM）

**目标**：实现 `agents/loop.py` 的 async generator 主 loop，**用 mock LLM
响应跑通**。这是项目的核心骨架，后面所有 agent 都长在上面。

**产出**：
- `agents/loop.py`：
  - `async def run_agent_loop(messages, tools, config) -> AsyncIterator[Event]`
  - `Event` 是 discriminated union：`AssistantMessage` / `ToolUse` /
    `ToolResult` / `TerminateReason`
  - 三种终止：`end_turn` / `max_turns` / `max_budget_usd`
  - 支持通过 `.athrow(CancelledError)` 取消
- `agents/mock_llm.py`：一个假的 LLM 客户端，按预设脚本返回响应
- `tests/test_loop.py`：至少 5 个测试用例
  - 正常终止
  - max_turns 终止
  - max_budget 终止
  - cancel（`.athrow()`）
  - tool use → tool result 闭环

**依赖**：M2

**DoD**：
- [ ] 5 个测试用例全绿
- [ ] `run_agent_loop` 本身 ≤ 100 行（如果超过说明抽象错了，要 review）
- [ ] 能用 `async for event in run_agent_loop(...): print(event)` 消费

**预估**：2-3 sessions。

**关键提醒**：这一步不要调真实 LLM。Mock 让你专注于"loop 控制逻辑"的
正确性，不被网络和 API 变化干扰。M5 才接真实 API。

---

## Phase 1: 单篇核心（M4-M7）

### M4: Schema 定义

**目标**：定义项目的结构化契约。

**产出**：
- `schemas/paper.py`：
  - `PaperMeta`：id, title, authors, arxiv_id, year, venue
  - `Contribution`：claim, type (novel_method/novel_result/survey/...),
    confidence (0-1)
  - `Method`：name, description, key_formula (optional), novelty_vs_prior
  - `Experiment`：dataset, metric, result, comparison_baseline
  - `Limitation`：type (scope/method/empirical), description
  - `CrossPaperLink`（占位）：related_paper_id, relation_type, explanation
  - `Paper`：顶层聚合，含以上所有字段
- 每个 field 用 Pydantic `Field(description=...)`，description 将来会**直接
  注入 LLM prompt**。
- `tests/test_schemas.py`：至少覆盖 5 种 "LLM 输出错误但能 recover" 的 case
  （多一个字段、少一个字段、类型错、嵌套错、空 array）

**依赖**：M1

**DoD**：
- [ ] 所有 schema 能 `model_dump_json()` 往返
- [ ] 对 5 种错误 case 的行为符合预期（retry 或降级）
- [ ] 每个字段的 description 能**直接作为 prompt 片段**（而不是只给开发者
      看的注释）

**预估**：1-2 sessions。

**关键提醒**：Field description 是你 prompt 工程最省力的地方——
Pydantic 会把它塞进 JSON schema，Anthropic 的 tool use 会把 schema 展示给
模型。**写得好模型就懂，写得烂模型就瞎填**。至少花 30 分钟琢磨每个字段。

---

### M5: 接入真实 LLM + 第一个 SkimAgent

**目标**：第一次把真实 API 接进 M3 的 loop，实现 SkimAgent，能读一个 PDF
的前几页产出 `PaperMeta` + 粗结构。

**产出**：
- `agents/llm_client.py`：Anthropic SDK 的薄封装。处理：prompt cache 分层、
  结构化输出（tool use）、错误重试、cost 上报。
  base_url 指向百炼 Anthropic 兼容端点
  （https://dashscope.aliyuncs.com/apps/anthropic），model 固定为
  qwen3.6-flash。
- `agents/skim.py`：`SkimAgent.run(pdf_path) -> PaperMeta & skeleton`
- `shared/pdf.py`：PDF 读取（用 pymupdf），提供"前 N 页文本 + 目录"
- 一个 `scripts/try_skim.py`，手动测：给一个真实 arxiv PDF，跑 SkimAgent
  看输出

**依赖**：M3, M4

**DoD**：
- [ ] 跑 `try_skim.py` 对**三篇不同领域的真实论文**（建议：一篇 NLP、一篇
      CV、一篇 theory）能产出合理的 PaperMeta
- [ ] cost 被正确记录（从 CostTracker 能看到）
- [ ] 每次 run 产生一个 JSONL 日志（临时放 `/tmp`，M6 后移到正式位置）

**预估**：2-3 sessions。

**关键提醒**：这是**整个项目的第一次 reality check**。如果跑出来结果很烂，
不要赶紧加 prompt engineering 往前推——**停下来，review 架构**。可能的
问题：schema 字段划分不合理（M4 要改）、loop 抽象不够（M3 要改）、
PDF 解析丢信息（shared/pdf.py 要改）。

**M5 之后强制 review 一次 ARCHITECTURE.md 的"待验证假设"那一节。**

---

### M6: Session JSONL 落盘

**目标**：SkimAgent 跑出来的所有东西（对话历史、tool call、schema 校验、
最终 PaperMeta）完整落盘到 `~/.paper-copilot/papers/<paper_id>/session.jsonl`。

**产出**：
- `session/store.py`：`SessionStore` 类，实现 append / read / tail / replay
- `session/types.py`：entry 类型定义（message / tool_result / compaction /
  schema_validation / final_output / session_header）
- `session/paths.py`：标准化路径逻辑（`~/.paper-copilot/papers/<id>/...`）
- 修改 `agents/loop.py`：把 events 写入 session（通过注入 store 依赖）
- `tests/test_session.py`：覆盖崩溃恢复（模拟写一半进程被 kill）

**依赖**：M5

**DoD**：
- [ ] 跑一篇论文后，`cat session.jsonl | head -5` 人类可读
- [ ] 模拟崩溃测试：写了 50 条 entry 后进程被 kill，重启后能读到 50 条
      （不是 49，不是 51）
- [ ] `paper_id` 格式定了（建议：arxiv id，否则 SHA1(title+year)[:12]）

**预估**：2 sessions。

---

### M7: DeepAgent + 单篇完整 read 流程

**目标**：`paper-copilot read <arxiv_url>` 能跑通完整流程，产出完整的
`Paper`（SkimAgent + 多个 DeepAgent 并发）。

**产出**：
- `cli/main.py`：用 Typer。至少实现 `read` 命令。
- `cli/commands/read.py`：编排 MainAgent 流程
- `agents/main.py`：`MainAgent`，负责派发 Skim 和 Deep，聚合结果
- `agents/deep.py`：`DeepAgent.run(pdf, section, schema) -> Contribution |
  Method | Experiment | Limitation`（按 section 和 schema 产出一种）
- `retrieval/chunker.py`：PDF → chunks（简单按 section + 长度切）
- `retrieval/search.py`：单篇内的 chunk 检索（用 sqlite-vec，bge-m3
  或 API）—— **这里决定 embedding 方案，之后不再改**
- 最终输出：markdown 报告（用 rich 在终端渲染）+ 完整 session JSONL

**依赖**：M6

**DoD**：
- [ ] 跑一篇 15-30 页的论文端到端不超过 2 分钟
- [ ] 输出的 Paper 有至少 3 个 Contribution、2 个 Method、2 个 Experiment、
      1 个 Limitation（不是硬性，但明显偏少说明 prompt/schema 有问题）
- [ ] 整个流程的 cost < ¥0.30（qwen3.6-flash，数字在首次真跑后校准）
- [ ] session.jsonl 可以完整 replay 出最终输出

**预估**：3-5 sessions。

**关键提醒**：这是**第一次能在简历上写的 milestone**。完成后录一个 1 分钟
demo 视频（你自己看，不对外）。视频作为简历项目的最终 demo 源素材。

---

## Phase 2: 真实使用 2 周（不是 milestone）

**这不是 milestone，是强制纪律。** 完成 M7 后，做**以下所有事**再进 M10：

1. **每天读 1-2 篇你本来就要读的论文**，用 paper-copilot 读
2. **每次 read 完后花 10 分钟**：
   - 看输出报告，记下哪里不满意
   - 看 session.jsonl，找最贵的一步 / 最慢的一步
   - 记一条 "issues.md" 条目（项目里新建一个文件）
3. **累积 10+ 篇之后**，回看 issues.md，归类：
   - Prompt 问题（改 schema description 或 system prompt）→ M8
   - Prompt cache 没命中 / 成本过高 → M9
   - 架构问题（要改模块边界）→ 停下来 review ARCHITECTURE.md
4. **诚实判断**：10 篇读完，你自己还愿意用它吗？
   - 愿意 → 继续 M8
   - 不愿意 → **停下来**，找根本问题。做跨论文和 eval 都救不了"主功能没价值"。

**这个阶段的产出**：`issues.md` + 10+ 篇论文的真实 session + 你对项目的真实
使用感受。这些是后续所有决策的输入。

**时长**：2 周，每天 30-60 分钟用 + 偶尔改 bug。

---

## Phase 2 衍生任务（M8-M9，基于 issues.md）

### M8: Prompt + schema 迭代（基于真实使用）

**目标**：根据 Phase 2 积累的 issues，改进 prompt 和 schema description。

**产出**：由 issues.md 决定。**不要在 Phase 2 之前预先写**。典型可能包含：
- 某几个 field description 重写
- DeepAgent 的 system prompt 加了反例
- 某个 schema field 拆分或合并

**依赖**：Phase 2 实打实做完

**DoD**：
- [ ] 至少 5 条 issues 被关闭（不是所有 issue 都要做，做最痛的几条）
- [ ] 对之前不满意的 3 篇论文重跑，确认改善
- [ ] 在 ARCHITECTURE.md 的"待验证假设"中勾掉或修改至少 2 条

**预估**：2-3 sessions。

---

### M9: Prompt cache 分层 + 成本观测

**目标**：把 prompt assembly 按变化频率分层，上 prompt cache，降成本。

**产出**：
- `shared/cache.py`：cache layer 打标工具，按变化频率把 prompt 分为：
  (1) tools 定义 (2) system prompt (3) persona (4) PDF 内容 (5) 用户 query
- `agents/llm_client.py`：在最后几个"不变层"的末尾插入 `cache_control:
  ephemeral`
- 新增 `paper-copilot doctor` 命令：读最近 N 次 session，输出缓存命中率、
  p50/p95 延迟、top-3 最贵的 session

**依赖**：M8（或 Phase 2 结束直接做也可）

**DoD**：
- [ ] 对相同 paper 跑第二次，第二次成本降 ≥ 50%
- [ ] 跑 10 篇新论文的平均 cache hit rate ≥ 50%
- [ ] `doctor` 命令输出美观可读

注：以上 50% 阈值源自 Anthropic `cache_control` 的经验值。切到百炼 qwen
后价格结构不同（显式缓存创建 ¥1.5/M、命中 ¥0.12/M、正常输入 ¥1.2/M），
首次完成 M9 时需用实际成本数据回校这两个阈值，必要时更新本节 DoD。

**预估**：2 sessions。

---

## Phase 3: 跨论文（M10-M13）

### M10: fields.db 字段索引

**目标**：把 Paper 的结构化字段落到 SQLite，支持 SQL-like 查询。

**产出**：
- `knowledge/fields_store.py`：SQLite 封装，schema 定好（建议用 JSON column
  + 表达式索引，避免多表 join）
- `knowledge/sync.py`：`index_paper(paper)` 增量同步
- `cli/commands/list.py`：`paper-copilot list --field method --contains
  contrastive`

**依赖**：M7（有 Paper 输出）

**DoD**：
- [ ] Phase 2 积累的 10+ 篇论文能批量 reindex
- [ ] 常见查询（按 method 关键词、按年份）< 50ms
- [ ] schema 向后兼容：加字段时不用 drop table

**预估**：2 sessions。

---

### M11: embeddings.db 向量索引 + 跨论文检索

**目标**：实现跨论文的 hybrid search。

**产出**：
- `knowledge/embeddings_store.py`：sqlite-vec 封装，带 paper_id 分区
- `knowledge/hybrid_search.py`：字段过滤 → 向量 top-k → 按论文聚合
- `knowledge/meta.py`：`meta.json` 读写，锁定 embedding 模型版本
- `cli/commands/search.py`：`paper-copilot search "<query>" [--year 2023+]`
- `cli/commands/reindex.py`：`paper-copilot reindex`

**依赖**：M10

**DoD**：
- [ ] 对 10+ 篇的库，search 延迟 < 1s
- [ ] reindex 10 篇论文的 chunk 重算 < 5 分钟
- [ ] meta.json 记录正确，换模型时检测到不一致并报错

**预估**：3 sessions。

---

### M12: RelatedAgent + 集成到 read 流程

**目标**：新 `read` 一篇论文时自动产出 CrossPaperLink。

**产出**：
- `agents/related.py`：`RelatedAgent`，输入是新论文的 Paper（初步版本），
  用 knowledge.hybrid_search 找 top-3 候选，用小模型判断是否真相关
- 修改 `agents/main.py`：流程末尾新增 RelatedAgent 步骤
- 修改 `schemas/paper.py`：`CrossPaperLink` 填具体字段
- 修改 markdown 报告：新增"相关论文"章节

**依赖**：M11

**DoD**：
- [ ] 新 read 一篇论文，如果库里有相关的，至少关联 1 篇；如果不相关就不强加
- [ ] 虚假关联率（人工判断）< 30%
- [ ] 每次关联额外成本 < $0.02

**预估**：2-3 sessions。

---

### M13: `compare` 命令

**目标**：实现用例 2。

**产出**：
- `cli/commands/compare.py`：从 fields.db 读两篇的结构化字段，渲染对比表
- 支持 `--deep` flag：调 LLM 做额外分析（可选）

**依赖**：M10

**DoD**：
- [ ] 对 Phase 2 积累的论文中挑 3 对做对比，输出人类可读
- [ ] 不加 `--deep` 时不调用 LLM（0 cost）

**预估**：1 session。

---

## Phase 4: eval（M14-M15）

### M14: Golden curation + suite runner

**目标**：能把 session 里某个字段标为 golden，能定义 suite 跑回归。

**产出**：
- `eval/goldens.py`：读写 `eval/goldens/<paper_id>_<field>.json`
- `eval/suite.py`：YAML suite 解析 + 执行（复用 agents/main.py 的 run）
- `eval/assertions.py`：schema check / field diff / cost / latency
- `cli/commands/eval.py`：`eval mark` / `eval run`

**依赖**：M12 以上都稳定了（否则 eval 的 ground truth 也会不稳）

**DoD**：
- [ ] 从 Phase 2 积累中挑 5 篇论文，每篇 mark 2 个字段为 golden
- [ ] 跑一次 suite 能 pass（因为是对自己的输出 eval）
- [ ] 改 prompt 故意让输出退化，再跑 suite 能 fail 并指出具体字段

**预估**：2-3 sessions。

---

### M15: Eval 报告 + 实战回归发现

**目标**：eval 模块产出 HTML 报告；**用它真的发现并修复一个问题**。

**产出**：
- `eval/report.py`：生成 HTML 报告（accuracy / cost / cache hit 趋势）
- 故意换一个模型或改一个 prompt，跑 eval suite 检测退化
- 把这次"发现退化 → 定位 → 修复"的完整过程写进 `docs/stories/<date>.md`

**依赖**：M14

**DoD**：
- [ ] HTML 报告能打开，三个趋势图可读
- [ ] 至少一次真实"退化被 eval 发现"的案例 + 完整故事记录
- [ ] 这个案例的数字（退化百分比、修复后改善）进入简历 bullet

**预估**：2 sessions。

---

## 全局纪律

1. **一个 session 一个 milestone**。不跨 milestone、不合并 milestone。
2. **每个 milestone 完成后 commit + 更新 TASKS.md 勾选框**。
3. **遇到"待验证假设"被推翻**，停下来更新 ARCHITECTURE.md，再继续。
4. **Phase 2 是红线**——不做 Phase 2 直接冲 Phase 3 会让整个项目失去灵魂。
5. **M5、M7、M11、M15 是 checkpoint**——每个 checkpoint 后强制问自己：
   "如果明天停工，这一步成果能不能独立写进简历？" 不能就是出了问题。

## 总时间估算

- Phase 0：4-6 sessions（2-3 天）
- Phase 1：8-12 sessions（4-6 天）
- Phase 2：2 周真实使用（每天 30-60 分钟）
- M8-M9：4-5 sessions（2-3 天）
- Phase 3：8-11 sessions（4-6 天）
- Phase 4：4-5 sessions（2-3 天）

**总计**：编码部分约 30-40 sessions，按一天 2 个有效 session 算 15-20 天
编码 + 2 周使用沉淀，**8-10 周**能到可以写进简历并讲深度的状态。

如果中途发现节奏偏离（比如 Phase 1 用了 15+ sessions），**停下来 review**
是 milestone 粒度不对还是卡在某个设计问题上，**不要硬推**。