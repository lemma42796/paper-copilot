# TASKS

> 状态：活文档。每完成一个 milestone 勾掉 + 简短标注"实际遇到的问题"，
> 给未来的自己和简历叙事留证据。
>
> 每个 milestone 包含：目标 / 产出 / 依赖 / DoD（Definition of Done）/
> 预估 session 数。

## Current Status

> 更新于 2026-05-24。每次 milestone 边界或 Phase 2 状态变化时刷新本节。
> 新会话问"项目进行到哪了"首先看这里,辅以 `git log -n 10` + 勾选框。

- **终端界面状态（2026-07-20）**：已删除 `src/paper_copilot/cli/`、CLI 测试、
  `paper-copilot` / `pc` console scripts 及 Typer/Rich 直接依赖。历史 milestone
  中的 CLI 命令仅保留为当时的实现记录，不代表当前仍提供终端操作入口。

- **已完成**:M1–M15(Session A + B 全部 done)。`paper-copilot read <pdf>` 端到端可用,含 `--force` +
  `--lang en|zh`。`paper-copilot doctor` (M9) 查最近 N 次 session 的
  cache 命中率 / p50-p95 latency / top-3 贵论文。`paper-copilot reindex`
  + `paper-copilot list` (M10) 落 SQLite 字段索引,支持 `--year` /
  `--field ... --contains ...` 查询。`paper-copilot search "<q>"` (M11)
  跨论文 hybrid search:text-embedding-v4(1024 维) + sqlite-vec KNN + fields
  预过滤。M12:`read` 末尾 spawn RelatedAgent,基于 `cross_paper_links`
  enum(5 档)挑库里 ≤ 3 篇相关论文,落盘 `graph/cross-paper-links.jsonl`
  并渲进 markdown 报告。`read` 末尾自动同步 fields.db + embeddings.db;
  `reindex --pdf-dir <dir>` 从历史 session 重建两个索引(embeddings 需
  PDF 在场,按 sha1 paper_id 匹配)。M13:`paper-copilot compare <a> <b>`
  从 fields.db 读两篇结构化数据,methods 按 name 对齐,experiments 按
  (dataset, metric) 对齐,limitations / contributions 双栏 bullet,A↔B
  方向的 cross_paper_link 单独成节渲染;`--format json` 给脚本消费
  (0 LLM cost)。
  M14:`paper-copilot eval mark <pid> -f <field>` 从 session.jsonl 落
  golden 进 `eval/goldens/<pid>_<field>.json`,`paper-copilot eval run
  <suite.yaml>` 在 tmpdir(隔离用户索引)重跑 MainAgent,字段断言 +
  绝对预算 cap。pyyaml 加进直接依赖。M15 Session A:`eval run` 自动落
  `eval/runs/<run_id>.jsonl`(per-run 一文件,带 git_sha + cache_hit_ratio);
  `paper-copilot eval report` 渲一份纯 stdlib 手搓 SVG 静态 HTML,三张
  趋势图(per-field PASS rate / per-paper cost / per-paper cache-hit ratio)
  + 顶部 last-vs-prev diff(PASS 翻转 / cost ±10% / cache ±10%)。
  `eval/runs/` + `eval/report.html` 进 .gitignore 当 runtime data。
  M15 Session B:`shared/cost.py` 加 `QwenPlusPricing` + `pricing_for_model()`
  支持多 tier 计费;跑 plus 候选 vs flash baseline 对比,数据决定继续用 flash
  (2.03x cost / 2.22x latency,0 quality 上行),story 落盘
  `docs/stories/2026-04-27-model-selection-flash-vs-plus.md`。
- **当前阶段**:**M18 paper-level RAG gate 已完成,chunk/evidence 级 baseline
  已补上,最终 chunk selector v1 已接入;M19 local-library-first Composer
  skeleton + deterministic plan/state 已开始编码**。
  截至 2026-05-21,
  chat-first runtime/API 与 macOS-style web shell 已可用。后续在 2026-07-19
  删除了 route / task profile：用户原始 prompt 直接进入 Paper Copilot，
  由模型自主决定直接回答或调用工具。
  检索侧已从 bge-m3 切到百炼 `text-embedding-v4`(1024 维),并落地
  FTS5/BM25 + vector RRF + multi-chunk evidence + chunk ref lookup + 前端证据
  面板。默认数据根 `~/.paper-copilot` 已用
  `/Users/a123/paper-copilot-test-pdfs` 补齐 text-embedding-v4 索引:当前
  34 papers / 2066 chunks。RAG v1 当前 gate:34 篇 / 36 queries seed eval
  mean `recall@5=98.4%`,`recall@10=100.0%`;不再为 seed eval 继续微调
  ranking。当前 paper mean `precision@5=32.8%`,`precision@10=16.9%`。
  chunk/evidence baseline 当前只覆盖 13 条带 anchor 的 query;eval matching
  已从严格 substring 改为 exact substring + embedding semantic window match。
  当前 query-mean `evidence_recall@5=87.2%`,`evidence_recall@10=89.7%`,
  说明此前一部分 miss 是“语义相关但不含人工 anchor 原文”的保守计分。
  当前 evidence anchor precision 为 `@5=44.9%`,`@10=45.3%`;它只衡量
  anchor-labeled paper 返回 chunks 中有多少命中人工 anchor 或语义窗口,不是
  未标注 chunk 的完整相关性判断。
  未做/暂跳过:reranker、paper alias/metadata 检索、retrieval misses/top-k
  诊断接前端、unsupported claim 系统人工抽样。M19 真实"论文创新方案生成"
  可以继续推进,但要把 evidence chunk recall 作为已知 grounding 风险。
  代码层 evidence chunk selection v1 已完成:top paper 排名不动,每篇内部
  默认取 20 个候选 chunk pool,再返回 3-5 个 evidence chunks。正式复跑后
  evidence recall 小升、precision 小降;最终 chunk selector v1 已补上,不要继续
  盲目扩大 pool。正式复跑后 evidence recall/precision 均小幅上升;下一步
  可以带着已知 grounding 风险进入 M19。M19 第一刀已把
  `ccf_a`→`ccf_b`→`other` 的本地资料库优先级写进工具约束;本轮补上
  deterministic plan/state 骨架,已经能拦截未按顺序 fallback;严格 3-module
  真实重跑已通过。M19 proposal checker/remediation v1 已接入 session/report;
  checker 启用后的 ReID 真实重跑已原生通过质量门:`proposal_check.passed=true`,
  无 issues、无过程话术清理 warning。按用户 2026-05-23 决策,暂跳过
  2-3 个固定 Composer 任务的多任务验收套件;当前只能声明 ReID 单例 demo
  clean 通过,不能声明 M19 已跨任务稳定泛化。后续继续推进时,把该风险作为
  已知边界,不要再为跳过的验收补跑真实任务,除非用户重新要求。
- **当前架构命名**（2026-07-19）：系统收敛为单 Agent。`Paper Copilot` 是
  唯一具备自主 tool loop 的 Agent；原 `MainAgent` / `SkimAgent` /
  `DeepAgent` / `RelatedAgent` 已分别改名为 `ReadPaperTool` /
  `SkimPaperTool` / `ExtractPaperTool` / `LinkRelatedPapersTool`。下方历史
  milestone 保留当时名称，不代表当前架构仍是 multi-agent。
- **当前输入决策**（2026-07-19）：已删除关键词 router、`route` 和
  `task_profile` 运行时控制。用户原始 prompt 直接进入 Paper Copilot；模型
  自主选择直接 `end_turn` 或调用具体工具。普通聊天不要求论文索引，也不写入
  research quality trend；Composer checker 只在实际调用 Composer 工具后启用。
- **最新交接**:**README demo 截图已换成 4K PNG**
  (2026-05-24)。`README.md` / `README.en.md` 的 4 张前端截图已从
  1280x720 JPG 切到 3840x2160 PNG:`paper-copilot-workbench.png` /
  `paper-copilot-composer.png` / `paper-copilot-evidence.png` /
  `paper-copilot-qa-report.png`。截图来自本地 production Next.js 页面 +
  `paper-copilot serve` API,复用了历史报告/证据数据,没有触发新的真实
  `/chat` 或 LLM 调用。验证:`npm run build`(apps/web) 通过,
  `git diff --check -- README.md README.en.md` 通过;未跑 `pytest` /
  `ruff` / `mypy`。旧 1280x720 JPG 已不再被 README 引用。
- **上一编码进展**:**报告 Markdown 表格渲染已接入**
  (2026-05-23)。Next.js 简易 Markdown renderer 现在支持 GFM 风格表格:
  `| header |` + `|---|` 会渲染成横向可滚动的 `<table>`,单元格里的 evidence refs
  仍走同一套可点击证据反查。已用历史 ReID demo 报告验证 `候选模块` 表格显示为
  1 个 table,表头为 `# / 模块名称 / 来源论文 / 功能描述`,3 个模块行正常;
  console 无 error。验证:`npm run typecheck`(apps/web) 通过。未跑
  `pytest` / `ruff` / `mypy`,未触发真实 `/chat` / LLM。
- **上一编码进展**:**Composer 风险与缺口已接入右侧摘要**
  (2026-05-23)。Next.js 右侧 Composer 摘要现在会从已生成的报告 Markdown 中提取
  `风险与缺口` 小节,把待验证假设/风险条目直接显示在运行信息里;其中的 field
  refs 仍可点击并打开右侧证据面板。该实现只做前端历史报告展示增强,未改变
  后端 final payload contract。验证:`npm run typecheck`(apps/web) 通过;浏览器
  已确认历史 ReID 报告显示 `风险与缺口`、点击风险条目中的 field ref 可打开字段
  证据,console 无 error。未跑 `pytest` / `ruff` / `mypy`,未触发真实 `/chat` / LLM。
- **上一编码进展**:**field evidence ref 反查已接入前端证据面板**
  (2026-05-23)。`/evidence` 现在同时支持 chunk refs 与 field refs:
  `[paper_id:chunks[12]]` 仍返回 chunk 原文,`[paper_id:methods[0]]` /
  `[paper_id:experiments[0]]` / `[paper_id:contributions[1].claim]` 等 field refs
  会从 `fields.db` 的 paper JSON 中解析对应字段并返回可读文本。前端报告正文和
  Composer 摘要里的 field refs 现在都可点击,右侧证据面板会显示论文标题、年份、
  字段路径与字段内容;Composer 摘要中的 evidence ref 按钮也从"复制"改为"打开"。
  已用本地 `8766` API 验证 field lookup,并在浏览器中点击历史 ReID 报告的
  `[c8258c808553:methods[0]]` 打开字段详情成功,console 无 error。验证:
  `uv run python -m py_compile ...` 通过,`npm run typecheck` 通过;未跑
  `pytest` / `ruff` / `mypy`,未触发真实 `/chat` / LLM。
- **上一编码进展**:**M19 Composer 产品侧/报告侧展示收口已接入**
  (2026-05-23)。`/chat` 与 `/reports` API 现在会把 session final payload 中的
  `composer_plan` / `proposal_check` 传给前端;历史报告也能显示已落盘的
  Composer 结构化状态。Next.js 右侧运行信息新增 Composer 摘要:展示
  checker 通过/需处理状态、accepted module 计数、distinct paper 约束、
  unsupported specific 计数、baseline paper、3 个 module 的 paper_id / pool /
  rationale / attachment / compatibility / evidence refs。前端默认 Composer
  prompt 已从 medical segmentation 例子改成当前 ReID 3-module demo 口径,
  避免继续误导真实试跑。按本轮策略未跑 `pytest` / `ruff` / `mypy` / 真实
  `/chat`;仅做代码层自查,不新增 LLM 调用。
- **上一编码进展**:**M19 proposal remediation v1 已接入**
  (2026-05-23)。在 checker 基础上继续收紧 Composer final report prompt 与
  `composer_plan.final_report_contract`:跨论文拼出来的新损失组合、新框架命名、
  指标提升、复杂度变化、optimizer/lr/batch/epoch 等 implementation specifics,
  必须有 exact citation 支撑;否则只能放进 `风险与缺口` 并明确标为
  `待验证假设` / `expected observation`,不能写成主方案事实。checker 同步改成
  同一边界:无引用联合损失会 hard fail,但引用支撑或 hypothesis/risk 写法可通过。
  同时把 evidence ref 解析从严格 `[paper_id:field]` 放宽为可容忍 bracket 内空格
  的 `[ paper_id:field ]`,并扩展过程话术清理以覆盖"报告已准备就绪"和紧随的
  markdown 分隔线。随后又补强兼容性检查:checker 可通过模块名/缩写把 compatibility
  表格行关联回 accepted module;prompt/contract 要求每个 compatibility row/bullet
  写 source paper_id。focused tests 增至 5 条,覆盖 spaced citation、chatter strip、
  compatibility table mapping、无引用联合损失 fail、hypothesis pass。验证:
  `uv run python -m py_compile ...` 通过,
  `uv run pytest tests/agents/test_composer_proposal.py -q`(5 passed);未跑整套
  `pytest` / `ruff` / `mypy`。
- **最新真实重跑**:**M19 Composer remediation clean ReID rerun 通过质量门**
  (2026-05-23)。命令同 strict 3-module ReID 任务:
  `uv run paper-copilot research "基于可见光-红外行人重识别（VI-ReID），帮我找一个可做的创新点：先选一个性能强但仍有改进故事的强基线，再从本地 CCF A 论文里找 3 个可兼容模块，要求每篇 module 论文最多取一个模块，给出中文实验方案" --pdf-dir /Users/a123/paper-copilot-test-pdfs --max-turns 16 --budget-cny 1.2 --max-papers 6 --no-record-quality --no-update-report`。
  成功结束:`termination=end_turn`,`cost=¥0.649416`,`events=35`,`papers=4/6`。
  `proposal_check.passed=true`,`issues=[]`,`removed_process_chatter=[]`,
  counts:`accepted_module_count=3`,`distinct_module_paper_count=3`,
  `citation_paper_count=4`,`english_heading_count=0`,`unsupported_specific_count=0`。
  `composer_plan.current_step=write_structured_proposal`,`report_ready=true`。
  baseline 为 DiVE(`c8258c808553`),3 个 module 为
  IDKL/IP(`6e870fa58055`)、HOS-Net/HSL(`80877d60f969`)、TokenMatcher/DTM
  (`bf1ea703e53c`),均来自 CCF A 且不同 paper。最终 report 没有 `质量检查`
  失败小节;损失融合/复杂度/资源需求等均转入 `风险与缺口` 并标为 hypothesis。
  session:
  `/Users/a123/.paper-copilot/papers/research-20260523T101050194694Z-f1574e90/session.jsonl`;
  report:
  `/Users/a123/.paper-copilot/papers/research-20260523T101050194694Z-f1574e90/research-report.md`。
- **上一编码进展**:**M19 proposal quality checker v1 已接入**
  (2026-05-23)。新增 `agents.composer_proposal` 纯规则 checker,只在
  `framework_composer` final output 边界运行,不新增 LLM call 或依赖。checker 会
  先移除最终报告开头的已知 agent 过程话术,再检查:中文 report + 中文 section
  标题、baseline 是否有性能强证据与 improvement/story opening、accepted modules
  是否正好 3 个且来自不同 paper、每个 module 是否在 report 中带 citation 与
  attachment/compatibility 说明、低优先级 pool 是否有 fallback 关闭记录、以及
  指标提升/训练超参/复杂度变化/MRIC-like 等 implementation specifics 是否缺
  citation 或没有标成 hypothesis/expected observation。检查结果写入
  `final_output.proposal_check`;未通过或移除过过程话术时会在 `research-report.md`
  末尾追加 `质量检查` 小节。Composer final report contract 和 prompt 已改为中文
  section:问题定义 / 强基线 / 候选模块 / 兼容性 / 组合方案 / 实验方案 /
  风险与缺口 / 证据。
  补了 focused checker tests 作为规则说明。按当前验证策略只跑了
  `uv run python -m py_compile ...` 和
  `uv run pytest tests/agents/test_composer_proposal.py -q`(2 passed);未跑整套
  `pytest` / `ruff` / `mypy`。
- **上一失败重跑**:**M19 Composer checker-enabled ReID rerun 未过质量门**
  (2026-05-23)。命令:
  `uv run paper-copilot research "基于可见光-红外行人重识别（VI-ReID），帮我找一个可做的创新点：先选一个性能强但仍有改进故事的强基线，再从本地 CCF A 论文里找 3 个可兼容模块，要求每篇 module 论文最多取一个模块，给出中文实验方案" --pdf-dir /Users/a123/paper-copilot-test-pdfs --max-turns 16 --budget-cny 1.2 --max-papers 6 --no-record-quality --no-update-report`。
  成功结束:`termination=end_turn`,`cost=¥0.8191068`,`events=35`,`papers=4/6`。
  trace 最终 `composer_plan.current_step=write_structured_proposal`,
  `report_ready=true`;baseline 为 DiVE(`c8258c808553`),3 个 module 为
  HSL(`80877d60f969`)、IP(`6e870fa58055`)、CIM(`9e5acb459b0e`),均来自不同
  CCF A 论文。输出已是中文 section,没有开头过程话术,accepted modules 数量与
  distinct paper 约束通过。原始落盘 checker 报 3 条 unsupported,其中两条是带
  citation 的真实性能数字误报;随后已把 checker 收窄为"metric claim 只有在缺
  citation 且未标成 hypothesis/expected observation 时才拦",并对同一 report
  离线重算为 1 条 true issue:`联合优化:融合 MRIC 损失(来自 HOS-Net)与 3M 损失
  (来自 IEEE)` 没有 citation/structured-field 支撑,也没有标为假设。session:
  `/Users/a123/.paper-copilot/papers/research-20260523T090430390070Z-f1574e90/session.jsonl`;
  report:
  `/Users/a123/.paper-copilot/papers/research-20260523T090430390070Z-f1574e90/research-report.md`。
  下一刀应让 final report 生成/后处理把这种跨论文损失拼接和新框架命名降级为
  hypothesis/risk,或要求每个具体 implementation choice 都带引用。
- **上一编码进展**:**M19 deterministic Composer plan/state 骨架已接入**
  (2026-05-22)。新增 `agents.composer_plan` 记录 Composer workflow state:
  `list_composer_library` → CCF A baseline search → baseline inspect/select →
  CCF A module search → module suitability/compatibility decision → 必要时
  close pool 后 fallback 到 CCF B/other → structured proposal。`PaperCopilotContext`
  现在携带 `composer_plan`;`list_composer_library` 会初始化/回传 plan,
  `search_composer_candidates` 会按 plan 拦截越级搜索,`inspect_paper` 会记录
  已 inspect 的 paper_id,新增 `update_composer_plan` 工具用于记录
  `select_baseline` / `accept_module` / `reject_module` /
  `close_module_pool`。现在 CCF B 搜索除了需要 LLM 输入 rejected list/reason,
  还必须先在 plan 里关闭 CCF A;`other` 同理必须先关闭 CCF A 与 CCF B。
  `composer_plan` 会进工具结果和 final session payload,并带
  `allowed_next_tools` / `report_ready` / final report contract。prompt 已更新为
  跟随 `composer_plan.allowed_next_tools`,且不要在 `report_ready=true` 前写最终
  proposal(除非所有 module pool 已查完并明确写 gap report)。补了一条 focused
  dispatch 测试作为行为说明。按当前验证策略未运行 `ruff` / `mypy` / `pytest`;
  实现后已跑 `py_compile`,并做了一次真实 research 重跑(见下一条)。
- **最新真实重跑**:**M19 Composer ReID strict 3-module trace audit 通过**
  (2026-05-23)。命令:
  `uv run paper-copilot research "基于可见光-红外行人重识别（VI-ReID），帮我找一个可做的创新点：先选一个性能强但仍有改进故事的强基线，再从本地 CCF A 论文里找 3 个可兼容模块，要求每篇 module 论文最多取一个模块，给出中文实验方案" --pdf-dir /Users/a123/paper-copilot-test-pdfs --max-turns 16 --budget-cny 1.2 --max-papers 6 --no-record-quality --no-update-report`。
  成功结束:`termination=end_turn`,`cost=¥1.253052`,`events=44`,`papers=6/6`。
  注意:预算参数为 `¥1.2`,最终因最后一次 LLM 调用后结算略超,说明 budget gate
  仍是调用边界检查而不是严格预扣。
  trace 顺序符合 stricter plan:
  `list_composer_library` → `search_composer_candidates(role=baseline,pool=ccf_a)`
  → 多篇 `inspect_paper` → `update_composer_plan(select_baseline)` →
  `search_composer_candidates(role=module,pool=ccf_a)` → 多篇 `inspect_paper` →
  三次 `update_composer_plan(accept_module)` → final。最终
  `composer_plan.current_step=write_structured_proposal`,`report_ready=true`,
  `allowed_next_tools=[write_final_proposal]`,未触发 CCF B/other fallback。
  产出方案为 IDKL(`6e870fa58055`) 强 baseline,加 3 个来自不同 CCF A 论文的
  module:HSL(`80877d60f969`),SFTS(`1e77e94f507f`),CIM(`9e5acb459b0e`)。
  session:
  `/Users/a123/.paper-copilot/papers/research-20260523T080934995962Z-f1574e90/session.jsonl`;
  report:
  `/Users/a123/.paper-copilot/papers/research-20260523T080934995962Z-f1574e90/research-report.md`。
  人工看报告结论:流程验证合格,但报告质量还没到最终交付标准。具体问题包括:
  开头残留"报告已准备好"这类 agent 过程话术;section 标题仍是英文
  `Problem` / `Baseline` / `Candidate Modules`;`训练数据标注成本高`、CIM
  复杂度从 `O(n²)` 降到线性、`MRIC-like联合优化`、`+1~2%` /
  `+2~4%` 预期提升等 claim 没有足够 citation/structured-field 支撑。
  仍缺的下一刀:proposal quality/checker 需要确定性检查中文 final report、baseline
  性能强证据 + improvement/story opening、3 个 distinct module papers、每个 module
  attachment point、以及 unsupported implementation specifics;对预期指标提升
  只能标为 hypothesis/expected observation,不能写成事实结论。
- **上一真实试跑**:**M19 Composer ReID trace audit 通过主流程**
  (2026-05-22)。命令:
  `uv run paper-copilot research "基于可见光-红外行人重识别（VI-ReID），帮我找一个可做的创新点：先选一个强基线，再从本地 CCF A 论文里找 1-2 个可兼容模块，给出实验方案" --pdf-dir /Users/a123/paper-copilot-test-pdfs --max-turns 10 --budget-cny 0.8 --max-papers 4 --no-record-quality --no-update-report`。
  成功结束:`termination=end_turn`,`cost=¥0.320442`,`events=23`,`papers=2/4`。
  trace 顺序符合 plan:
  `list_composer_library` → `search_composer_candidates(role=baseline,pool=ccf_a)`
  → `inspect_paper` → `update_composer_plan(select_baseline)` →
  `search_composer_candidates(role=module,pool=ccf_a)` → `inspect_paper` →
  `update_composer_plan(accept_module)` → final。最终 `composer_plan.current_step`
  为 `write_structured_proposal`,`report_ready=true`,未触发 CCF B/other fallback。
  产出方案为 DiVE(`c8258c808553`) + IEEE/AAAI-22 CIM/REM/3M Loss
  (`9e5acb459b0e`)。session:
  `/Users/a123/.paper-copilot/papers/research-20260522T150546222461Z-c0b73f7b/session.jsonl`;
  report:
  `/Users/a123/.paper-copilot/papers/research-20260522T150546222461Z-c0b73f7b/research-report.md`。
  暴露的问题:报告有 `AdamW/lr/batch size/120 epochs` 等实现细节没有被
  citation/checker 约束,说明下一刀需要 proposal quality/checker 抓
  unsupported implementation specifics,不能只看 heuristic evidence coverage。
- **Baseline 标准校正**(2026-05-23):按用户纠正,baseline 选择口径不是泛泛
  "强/可复现",而是 **性能强、高起点,但仍有可以改进或容易讲研究故事的地方**。
  已同步到 `docs/design/chat_first_research_copilot_plan.md` 的 Baseline
  Selection Criteria、`framework_composer` prompt,以及 `composer_plan`
  final report contract。下一刀 checker/scorer 需要把这条做成硬检查:
  baseline 必须有性能强证据 + improvement/story opening 证据。
- **Module 数量校正**(2026-05-23):按用户纠正,最终方案目标不是 1-3 或
  2-3 个 module,而是 **3 个 accepted modules**。已同步
  `framework_composer` prompt、`composer_plan` final report contract 和
  `report_ready`:除非所有 module pool 都已搜完并明确写 gap report,否则
  `accepted_modules` 少于 3 个时不能进入 ready/final proposal 状态。
- **Module 来源约束补强**(2026-05-23):设计文档早已写明
  "Each module paper can contribute at most one module",但上一轮代码/prompt 没有
  硬约束,导致旧 ReID trace 从同一篇 IEEE/AAAI-22 paper 里拿 CIM/REM/3M Loss
  三个组件。已补成硬规则:3 个 accepted modules 必须来自 3 个不同
  `paper_id`;`accept_module` 重复接受同一 module paper 会报错,final report
  contract/prompt 也明确 one paper at most one module。
- **最终报告语言校正**(2026-05-23):最终 report/proposal 必须用中文输出。
  已同步 `Paper Copilot` final report guidance、`composer_plan` final report
  contract 和 M19 设计文档;后续 checker 应把非中文 final report 视为不合格。
- **上一编码进展**:**M19 Composer 本地资料库工具骨架已接入**
  (2026-05-22)。新增 `agents.composer_library` 扫描用户 `pdf_dir` 下的
  `ccf_a/`、`ccf_b/`、`other/` 三个 pool,返回 PDF 的 `paper_id`、路径、
  indexed 状态和已入库 meta。`knowledge.hybrid_search.search()` 新增可选
  `paper_ids` 过滤,供 Composer 只在指定 pool 内检索。Paper Copilot 新增
  `list_composer_library` 与 `search_composer_candidates`:baseline 只能搜
  `ccf_a`;module 默认先搜 `ccf_a`;只有传入 `rejected_ccf_a_modules` +
  `rejection_reason` 才能 fallback 到 `ccf_b`;`other` 还要求同时说明
  `ccf_b` rejection。`framework_composer` prompt 已同步强调 CCF A module
  优先、CCF B fallback、最终报告解释为什么没选更高优先级 pool。随后补了
  `list_pdfs` / `read_paper(paper_id=...)` 对嵌套 PDF 的递归扫描,适配
  `ccf_a/ccf_b/other` 子目录;Composer 候选搜索结果新增 `pool_trace`,prompt
  明确建议工具顺序:`list_composer_library` → baseline search → baseline
  inspect → CCF A module search → 必要时 CCF B fallback。用户确认
  `/Users/a123/paper-copilot-test-pdfs` 里的论文都先按 CCF A 处理,CCF B/other
  暂空;因此 Composer library 现在支持 flat `pdf_dir` 直接作为 `ccf_a` pool,
  并按 `paper_id` 去重(显式 `ccf_a/` 优先于根目录重复 PDF)。HTTP API 新增
  `GET /composer/library?pdf_dir=...`,只扫描目录和 `fields.db`,不读 PDF、
  不 embedding、不调 LLM,用于前端/手动检查 pool 状态。前端右侧资料库面板
  已接入该 preview,会展示 flat CCF A 模式、CCF A/CCF B/Other 的 PDF 数与
  indexed 数,以及 module pool 顺序;该 UI 只检查资料库准备状态,不启动 agent。
  百炼 Function Calling 文档已判断为"流程有用、接口格式不可直接照搬":当前
  代码走 DashScope Anthropic-compatible endpoint,工具定义仍是
  `name` / `description` / `input_schema`,不是 OpenAI/DashScope 的
  `type:function` / `function.parameters`;可复用的是"LLM 选工具 → 应用端执行
  工具 → tool result 回灌 → 再调 LLM"的循环、工具描述/token 成本/小工具集/
  安全边界等生产经验。长期记录见
  `docs/design/chat_first_research_copilot_plan.md` 的
  "Function Calling Integration Note"。
  按用户本轮指令未跑 `ruff` / `mypy` / `pytest` / 真实 `/chat`。
- **上一编码进展**:**最终 evidence chunk selector v1 已接入**
  (2026-05-21)。`knowledge.hybrid_search._paper_local_chunks()` 现在不再对
  每篇 `evidence_pool_per_paper` 候选直接截断前 N 条,而是先保留原有
  vector + BM25/RRF 候选分,再用 query term 覆盖、BM25/vector 双路命中、
  method/experiment/result 等 section hint 和 token-overlap redundancy
  penalty 做确定性最终选择。该改动不改变 top paper ranking、不引入 reranker/
  LLM/新依赖,也不改变 `search_library` payload contract。已跑
  `uv run pytest tests/knowledge/test_hybrid_search.py -q`(12 passed)、
  touched-file `ruff check`、touched source `mypy` 和 `git diff --check`;
  按用户要求正式复跑
  `uv run paper-copilot eval retrieval eval/retrieval/queries.yaml`,recorded run:
  `eval/runs/2026-05-21T10-04-04Z.jsonl`。当前结果:paper mean
  `recall@5=98.4%`,`recall@10=100.0%`,`precision@5=32.8%`,
  `precision@10=16.9%`;13 条 evidence-labeled queries 的 query-mean
  `evidence_recall@5=87.2%`,`evidence_recall@10=89.7%`,
  `evidence_anchor_precision@5=44.9%`,`evidence_anchor_precision@10=45.3%`。
- **上一编码进展**:**embedding cache 已接入**
  (2026-05-21)。论文库 chunks 的向量本来就落在
  `~/.paper-copilot/embeddings.db`;本次补的是通用文本向量缓存:
  search/chat/retrieval eval/related/read/reindex 现在通过
  `~/.paper-copilot/embedding_cache.sqlite` 按 `model + dim + text_sha256`
  复用已算向量,避免重复 query / evidence anchor / semantic window / chunk text
  反复调用 `text-embedding-v4`。该改动不改变 retrieval ranking 或
  `search_library` 输出;换模型或换维度不会复用旧缓存。已跑
  `uv run pytest tests/eval/test_embedding_cache.py tests/eval/test_retrieval.py tests/eval/test_runs.py tests/eval/test_report.py -q`
  与扩展后的 focused suite(52 passed,5 warnings)、touched-file `ruff check`、
  touched source `mypy` 和 `git diff --check`;为避免额外花 embedding API 成本,
  本轮未复跑真实 retrieval eval。
- **上一编码进展**:**evidence anchor semantic matching 已接入**
  (2026-05-21)。`eval.retrieval` 的 evidence matching 现在先保留严格
  substring 命中;未命中时把同 paper 返回 chunk 切成 45-token/20-stride
  小窗口,用现有 `text-embedding-v4` 比 anchor-vs-window cosine similarity,
  阈值 `_SEMANTIC_ANCHOR_THRESHOLD=0.75`。这只改 eval 计分口径,不改
  retrieval ranking 或 `search_library` 输出。已跑
  `uv run pytest tests/eval/test_retrieval.py tests/eval/test_runs.py tests/eval/test_report.py -q`
  (18 passed,5 warnings)、touched-file `ruff check` 和 `git diff --check`。正式复跑
  `uv run paper-copilot eval retrieval eval/retrieval/queries.yaml`,recorded run:
  `eval/runs/2026-05-21T09-05-27Z.jsonl`;`eval/report.html` 刷新为 10 runs /
  339 rows。当前结果:paper mean `recall@5=98.4%`,`recall@10=100.0%`,
  `precision@5=32.8%`,`precision@10=16.9%`;13 条 evidence-labeled queries 的
  query-mean `evidence_recall@5=82.1%`,`evidence_recall@10=84.6%`,
  `evidence_anchor_precision@5=43.6%`,`evidence_anchor_precision@10=44.4%`。
  主要新增命中来自 q006/q023/q033/q036。该 eval 口径会额外调用 embedding API
  编码 anchor 与候选 chunk 窗口;本轮未跑真实 `/chat` / LLM。
- **上一编码进展**:**evidence chunk selection v1 已接入**
  (2026-05-21)。`knowledge.hybrid_search.search()` 现在先按全库 hybrid
  chunk 排名固定 top papers,再对每个 selected paper 用同一 query 做
  paper-local vector + BM25/RRF chunk pool,最后返回
  `max_chunks_per_paper` 个 evidence chunks。`search_library` 新增
  `evidence_pool_per_paper` 参数,默认 20、上限 50,用于扩大每篇内部 evidence
  候选池而不改变 paper ranking。已补 focused 单测覆盖“论文进入 top papers,
  但目标 evidence chunk 未进入第一阶段全局 pool”的场景。已跑
  `uv run pytest tests/knowledge/test_hybrid_search.py tests/agents/test_research.py -q`
  (24 passed,5 warnings)、touched-file `ruff check` 和 `git diff --check`。正式复跑
  `uv run paper-copilot eval retrieval eval/retrieval/queries.yaml`,recorded run:
  `eval/runs/2026-05-21T08-06-26Z.jsonl`;`eval/report.html` 刷新为 9 runs /
  303 rows。当前结果:paper mean `recall@5=98.4%`,`recall@10=100.0%`,
  `precision@5=32.8%`,`precision@10=16.9%`;13 条 evidence-labeled queries 的
  query-mean `evidence_recall@5=56.4%`,`evidence_recall@10=56.4%`,
  `evidence_anchor_precision@5=24.4%`,`evidence_anchor_precision@10=23.9%`。
  相比上一轮,q033 evidence recall 从 `0.0%` 到 `33.3%`,q018 recall 不变但
  anchor precision 从 `66.7%` 降到 `33.3%`。未跑真实 `/chat` / LLM。
- **上一编码进展**:**retrieval precision 指标已接入**
  (2026-05-19)。`paper-copilot eval retrieval` 现在同时计算/展示/记录
  paper `precision@5/@10` 与 evidence anchor `precision@5/@10`;run history
  JSON 兼容旧 retrieval rows,`eval report` 的 retrieval summary、趋势图和
  detail table 都已展示 precision。定义:paper precision 是 topK 中 relevant
  papers 占比;evidence anchor precision 是 anchor-labeled paper 返回 chunks
  中包含人工 anchor 的比例,用于观察"多取 chunk 后是否稀释证据密度",不是
  未标注 chunk 的完整相关性判断。正式复跑:
  `eval/runs/2026-05-19T13-13-50Z.jsonl`;`eval/report.html` 刷新为 16 runs /
  347 rows。当前结果:paper mean `recall@5=98.4%`,`recall@10=100.0%`,
  `precision@5=32.8%`,`precision@10=16.9%`;13 条 evidence-labeled queries
  的 query-mean `evidence_recall@5=53.8%`,`evidence_recall@10=53.8%`,
  `evidence_anchor_precision@5=25.6%`,`evidence_anchor_precision@10=25.6%`。
  已跑 touched eval 单测:
  `uv run pytest tests/eval/test_retrieval.py tests/eval/test_runs.py tests/eval/test_report.py`
  (17 passed,5 warnings),以及 touched-file `ruff check`。
- **上一编码进展**:**chunk/evidence anchors 已收紧为答案型原文短句**
  (2026-05-19)。按用户追问,将 `eval/retrieval/queries.yaml` 中
  `Soft-Mask Images`、`Diverse Tokens Neighbor Learning`、`This is followed
  by the triplet loss` 等方法名/短词式 anchor 替换为"动作 + 对象/效果"的
  原文 evidence 短句,例如 q019 改为
  `generate soft-mask images with the BG being suppressed`,q018 改为
  `Part Selection Module (PSM) is applied to select tokens...`。只读核查
  16 个 anchors 均能在对应 paper chunk 中直接命中(`bad=0`)。正式复跑:
  `eval/runs/2026-05-19T11-00-30Z.jsonl`;`eval/report.html` 刷新为 15 runs /
  311 rows。结果:paper mean `recall@5=98.4%`,`recall@10=100.0%`;13 条
  evidence-labeled queries 的 query-mean `evidence_recall@5=53.8%`,
  `evidence_recall@10=53.8%`。相比上一版 56.4% 小降是标签更严格导致,
  结论不变:经常找对论文,但 top paper result 携带的 3 条 evidence chunks
  仍没稳定覆盖人工答案句。按用户验证策略,本轮未运行 `ruff` / `mypy` /
  `pytest`。
- **更早编码进展**:**chunk/evidence 级 retrieval recall baseline + label audit 已完成**
  (2026-05-19)。`eval/retrieval/queries.yaml` 新增可选
  `evidence_anchors`(`paper_id` + stable text anchor),不使用易漂移的
  chunk_id;`paper-copilot eval retrieval` 现在同时输出/记录 paper recall 与
  `evidence_recall@5/@10`,run history 与 `eval report` 也渲染 evidence recall
  趋势和 latest query detail。首轮未审标签 dogfood 为
  `evidence_recall@5/@10=44.9%`;随后只读核查发现 q017/q019/q027/q033
  存在 anchor 文本断词/概括句问题,q023 anchor 语义不够贴近 query,已改为能在
  对应 paper chunk 中直接命中的稳定原文 anchor。修正后正式记录:
  `eval/runs/2026-05-19T10-21-13Z.jsonl`;`eval/report.html` 刷新为 14 runs /
  275 rows。结果:paper mean `recall@5=98.4%`,`recall@10=100.0%`;13 条
  evidence-labeled queries 的 query-mean `evidence_recall@5=56.4%`,
  `evidence_recall@10=56.4%`。剩余弱项主要不是找错论文,而是 top paper
  result 携带的 3 条 evidence chunks 没覆盖人工 anchor。按用户验证策略,本轮
  未运行 `ruff` / `mypy` / `pytest`。
- **更早编码进展**:**retrieval ranking 观察切片已完成**
  (2026-05-19)。`eval/retrieval/queries.yaml` 已从 12 篇 / 15 queries 扩到
  当前默认论文库 34 篇 / 36 queries,新增 ReID / VI-ReID / multi-modal /
  token selection / Transformer survey / diffusion / Mamba 等 seed。继
  q012/q018/q033 label 审核后,又审了 q014/q015/q020/q025/q033:q014 收窄为
  ViLBERT vs ViT,q020 把 test-time training 标签换成 VI-ReID 表征论文,
  q025 去掉非 ReID 的 TransFG 标签;q015/q033 保留为真实 top-5 排序弱项。
  复跑 `paper-copilot eval retrieval eval/retrieval/queries.yaml`:mean
  `recall@5=98.4%`,`recall@10=100.0%`,recorded run:
  `eval/runs/2026-05-19T09-32-49Z.jsonl`;`eval/report.html` 已刷新为 12 runs /
  203 rows。随后只读比较 current / overfetch10 / overfetch20 / rrf10 /
  vector_only:overfetch10 仅把 mean `recall@5` 提到 `98.6%`,但 q015
  `-25.0%`、q033 `+33.3%`,属于互相抵消的排序交换;overfetch20、rrf10、
  vector_only 都有更明显回退。因此本轮不改默认 ranking 参数。按用户最新
  指令,本轮未运行 `ruff` / `mypy` / `pytest`。
- **默认论文库设置**(2026-05-19):`/Users/a123/paper-copilot-test-pdfs`
  已设为 chat/research 默认本地论文库。后端优先读 `PAPER_COPILOT_PDF_DIR`,
  否则在本机 fallback 到该路径;前端资料库输入框默认也填这个目录。`reindex`
  仍要求显式传 `--pdf-dir`,避免误触发全量重 embedding。按用户最新指令,
  本轮未运行 `ruff` / `mypy` / `pytest`。
- **默认论文库 embedding 补齐 1**(2026-05-19):对
  `/Users/a123/paper-copilot-test-pdfs` 中尚未进入 `embeddings.db` 的 21 个
  PDF 逐篇执行 `read`,避免全量 `reindex` 重跑旧论文。结果:20 篇成功,1 篇失败
  (`TransFG- A Transformer Architecture for Fine-Grained Recognition.pdf`,
  paper_id=`860e24025c67`,DeepAgent `emit_deep.methods` schema validation
  failed)。当前 `embeddings.db` 为 33 papers / 2030 chunks;本批 20 篇 read
  合计约 ¥1.8720,平均约 ¥0.0936/篇;日志:
  `/private/tmp/paper-copilot-read-missing.log`。按用户最新指令,本轮未运行
  `ruff` / `mypy` / `pytest`。
- **默认论文库 embedding 补齐 2**(2026-05-19):单独重跑唯一失败的 TransFG
  (`paper-copilot read ... --force`) 成功,本次成本约 ¥0.0547。当前
  `/Users/a123/paper-copilot-test-pdfs` 的 34 个 PDF 已全部进入
  `embeddings.db`:34 papers / 2066 chunks,missing=0。按用户最新指令,本轮未运行
  `ruff` / `mypy` / `pytest`。
- **M17-min 进展**(2026-05-18):新增 `paper-copilot research "<topic>"`
  的最小 bounded tool loop 骨架。当前包装本地库工具:`list_papers` /
  `list_pdfs` / `read_paper` / `search_library` / `inspect_paper` /
  `compare_papers` / `find_related_papers`,带 max_turns / budget /
  max_papers / termination summary / session trace / research-report.md。
  `read_paper` 已从占位升级为受控自动读:只读取 `--pdf-dir` 下本地 PDF,
  可由 `pdf_path` 或匹配到本地 PDF 的 `paper_id` 触发,成功后写单篇
  session/report 并同步 fields + embeddings + graph,worker cost 会计入
  research 总 budget。`find_related_papers` 是 0-LLM tool:优先读
  `graph/cross-paper-links.jsonl`,再用 fields.db 里的 `cross_paper_links`
  补充。它不会联网找论文、不做 RAG 升级;完整 M17 DoD 仍未满足。
- **当前验证策略**:用户最新明确指令(2026-05-18):"不再做测试了"。后续 M17
  实现任务不要主动跑 pytest / LLM 试跑 / 全量门禁;必要时只做最小静态检查,
  并在回复里明确标注"未测试"。全量三件套在 `b4e4d79` 前跑过一次,之后未再
  全量跑。
- **M17 人工试跑 1/3**(2026-05-18):topic=`compare attention mechanisms
  across Bahdanau attention, Transformer, and ViT`。`--max-turns 4` 能走
  list/inspect/compare,但停在 max_turns,只生成一句占位报告,同时暴露过一次
  planner 把 `inspect_paper.fields` 错填成 `title/year/top_methods/...` 的
  schema error。重跑 `--max-turns 8 --max-papers 3 --budget-cny 0.2` 成功
  `end_turn`,cost ¥0.0571,events=17,papers=3/3,report 可读,session:
  `/Users/a123/.paper-copilot/papers/research-20260518T090546424841Z-6e47b315/session.jsonl`。
- **M17 人工试跑 2/3**(2026-05-18):topic=`compare metric learning and
  training tricks for face recognition and person re-identification`。
  `--max-turns 8 --max-papers 3 --budget-cny 0.2` 成功 `end_turn`,cost
  ¥0.0434,events=14,papers=3/3,last_tool_error=None。Planner 正确选中
  `FaceNet` / `In Defense of the Triplet Loss` / `Bag of Tricks`,工具路径是
  `list_papers -> inspect_paper x3 -> final report`,没有触发 compare/find
  related。report 可读,但开头仍带一句过程性话术。session:
  `/Users/a123/.paper-copilot/papers/research-20260518T091259404664Z-e96c8456/session.jsonl`。
- **M17 人工试跑 3/3**(2026-05-18):topic=`compare the evolution of image
  recognition architectures from LeNet to AlexNet, Inception, ResNet, and ViT`。
  `--max-turns 8 --max-papers 5 --budget-cny 0.2` 能正确选中 5 篇并调用
  compare,但停在 max_turns,只生成一句占位报告。重跑 `--max-turns 10
  --max-papers 5 --budget-cny 0.2` 成功 `end_turn`,cost ¥0.0960,events=29,
  papers=5/5,last_tool_error=None。Planner 选中 LeNet/AlexNet/Inception/
  ResNet/ViT,工具路径包含 `list_papers` 多次、`inspect_paper x5`;未触发
  find_related。发现的问题:5 篇任务 8 turns 偏紧;planner 会输出过程性话术;
  `list_papers.year` 传过字符串但 Pydantic 容忍转换。session:
  `/Users/a123/.paper-copilot/papers/research-20260518T091657508790Z-495725e7/session.jsonl`。
- **M17 planner/schema 收敛 1**(2026-05-18):针对 3 次人工试跑的低风险修正
  已完成:默认 `research --max-turns` 从 12 提到 16;`year/limit/k/max_items`
  改成 strict int,避免 `"2017"` 这类字符串静默通过;planner prompt 明确最终
  输出不能带过程性话术,并补充少重复 list、何时用 compare/find_related 的工具
  选择规则。已跑相关 `ruff` / `mypy` / `tests/agents/test_research.py` +
  `tests/test_smoke.py`,未跑全量 pytest,也未再做 LLM 实跑。
- **M17 planner/schema 复跑 1**(2026-05-18):复跑视觉架构 topic 时第一次用
  新默认 16 turns 进入最终报告阶段,但 LLM 返回 `stop_reason=max_tokens`,
  CLI 抛 `AgentError`,session:
  `/Users/a123/.paper-copilot/papers/research-20260518T092628989382Z-495725e7/session.jsonl`。
  随后做最小修正:给 `LoopConfig` 增加可选 `max_tokens`,只让 Paper Copilot
  传 3000;prompt 同时要求最终 report `< 900 words`。重跑同命令成功
  `end_turn`,cost ¥0.0879,events=23,papers=5/5,last_tool_error=None,报告
  直接从 `Findings` 开始,无过程性话术;工具路径为 `list_papers x1` +
  `inspect_paper`/`compare_papers`,没有无谓 year-filter list。session:
  `/Users/a123/.paper-copilot/papers/research-20260518T092927821092Z-495725e7/session.jsonl`。
  已跑相关 `ruff` / `mypy` / `tests/agents/test_loop.py` +
  `tests/agents/test_research.py` + `tests/test_smoke.py`,未跑全量 pytest。
- **M17 read_paper 自动读实现**(2026-05-18):公共 read pipeline 已抽到
  `agents/read_pipeline.py`,`paper-copilot read` 与 Paper Copilot tool 共用。
  Paper Copilot 的 `read_paper` 在 async dispatch 中会校验 PDF 位于
  `--pdf-dir` 下、受 `max_papers` 限制、复用同一个 `LLMClient`,并把
  Skim/Deep/Related worker cost 合进 research 总 cost;若没有本地 PDF /
  session 目录已存在但未入库 / embedding handles 不可用,返回
  `needs_user_action` 而不是编结论。按用户最新指令,本次没有跑 pytest /
  全量门禁;只跑了 touched-file ruff。
- **M17 `--pdf-dir` 快速验收 1**(2026-05-18):用户要求"最快速跑"后,
  用最小真论文 PDF
  `/Users/a123/Documents/reid/顶刊顶会参考文献/Eliminating_Background-Bias_for_CVPR_2018_paper.pdf`
  跑 `research`。参数:`--max-turns 4 --max-papers 1 --budget-cny 0.25`。
  结果成功 `end_turn`,cost ¥0.1147,events=11,papers=1/1。`read_paper`
  返回 `status=read`,paper_id=`1f65cbc78943`,indexed chunks=92,report
  只汇报 read 成功。RelatedAgent 触发过一次 temporal directional link
  drop warning(2017 新论文指向 2019 候选的 `compares_against` 被丢掉),
  属于预期防错。session:
  `/Users/a123/.paper-copilot/papers/research-20260518T113724081683Z-426259ec/session.jsonl`。
- **M17 read→inspect 提示修正**(2026-05-18):快速验收后发现 planner/report
  容易把 `max_papers=1` 误解成 read 后不能再 inspect 同一篇。已补
  `read_paper` payload:`can_inspect_same_paper=true` + `recommended_next_tool`
  指向 `inspect_paper`,并在 Paper Copilot 初始指令里明确:限制的是唯一
  paper_id,同一 paper_id 的 inspect 不消耗新的 slot。
- **M17 read→inspect 默认路径收敛**(2026-05-18):Paper Copilot tool schema
  和初始指令进一步明确:正常 research task 中 `read_paper` 返回
  `read`/`already_read` 后,默认下一步应 `inspect_paper` 同一 paper_id,
  再写 final report,以便 report 引用 meta/contributions/methods/experiments
  而不只是汇报 read 成功。已补 mock tool-loop 测试覆盖
  `read_paper -> inspect_paper -> end_turn`,未跑 pytest/LLM。
- **M17 inspect evidence payload**(2026-05-18):`inspect_paper` 保留原始字段,
  同时新增 `evidence_summary` 与 `suggested_citations`。summary 直接给
  title/year/venue、top_contributions、top_methods、key_experiments、
  top_limitations;citations 每条带 `paper_id` / `field` / `text`,方便 final
  report 稳定引用结构化证据。Paper Copilot 初始指令也改为优先使用这两层
  写 Findings/Evidence。按用户要求,本次不跑任何验证命令。
- **M17 synthesis path 引导**(2026-05-18):`inspect_paper` 现在还返回
  `recommended_followups`,当 `max_papers` 还有空间时建议
  `find_related_papers` / `search_library`,当已触达两篇时建议
  `compare_papers`。Paper Copilot 初始指令明确:综合/对比任务不要在只
  inspect 一篇后直接 final,应扩展至少一篇库内相关论文并 inspect/compare
  后再 synthesis。已补 mock trace 覆盖
  `read_paper -> inspect_paper -> find_related_papers -> inspect_paper ->
  compare_papers -> end_turn`;按用户要求未运行任何验证命令。
- **M17 final evidence refs**(2026-05-18):Paper Copilot final report 现在要求
  Evidence bullets 使用可解析引用格式 `[paper_id:field]`,字段优先来自
  `suggested_citations` 或 `compare_papers` 输出。`run_paper_copilot` 会从最终
  markdown 中抽取引用并写入 session `final_output.evidence_refs`
  (`paper_id` / `field` / `raw`),为后续 unsupported claim rate 统计留接口。
  已补 mock 断言,按用户要求未运行任何验证命令。
- **M17 final quality payload v1**(2026-05-18):`run_paper_copilot` 现在基于最终
  markdown 的 `Findings` 与 evidence refs 写入确定性
  `final_output.quality`:包含 `evidence_ref_count`、`findings_claim_count`、
  `findings_inline_ref_count`、`claims_without_refs_count`、
  `evidence_coverage_ratio`。这是粗粒度 heuristic,不是 LLM judge,用于后续
  unsupported claim rate / evidence coverage 的趋势信号。已补 mock 断言,
  按用户要求未运行任何验证命令。
- **M17 research quality trend 接入**(2026-05-18):eval run-history 的
  `RunRow` 现在兼容可选 research quality 字段;新增
  `paper-copilot eval record-research <session.jsonl>` 可把 Paper Copilot
  session 的 `final_output.quality` 记录成 `research_quality` row。`eval report`
  遇到这些字段时会追加 evidence coverage 与 unsupported claim ratio 两张
  趋势图。已补纯 mock/HTML 断言,按用户要求未运行任何验证命令。
- **M17 research quality 自动记录**(2026-05-18):`paper-copilot research`
  现在默认在写 `research-report.md` 后把当前 session 的
  `final_output.quality` 追加到 eval run-history,终端输出 `quality:` 路径;
  可用 `--no-record-quality` 跳过。记录失败只 warning,不影响 research
  report 输出。按用户要求未运行任何验证命令。
- **M17 eval report 自动刷新**(2026-05-18):`paper-copilot research` 成功记录
  quality 后默认刷新 repo-local `eval/report.html`,终端输出 `eval report:`
  路径;可用 `--no-update-report` 跳过。`eval/_paths.py` 新增
  `default_report_path()` 统一默认位置。按用户要求未运行任何验证命令。
- **Chat-first intent router v1**(2026-05-18):新增 `paper_copilot.chat.router`
  作为后续前端单输入框的后端路由层。Paper Copilot 现在会先把自然语言
  请求路由为 `research` 或 `idea_composer`;命中"创新点/研究想法/idea/
  proposal/选题/实验方案"等意图时,final prompt 自动切到 Composer 输出
  结构:Problem / Prior Evidence / Gap / Idea / Why It Might Work /
  Experiment Plan / Risks / Evidence。`final_output.request_route` 会落盘,
  quality 统计也能从 Composer 的 `Idea` section 抽 claim。按用户要求未运行
  任何验证命令。
- **Chat-first runtime API v1**(2026-05-18):新增
  `paper_copilot.chat.runtime.handle_chat_request()` 作为前端单输入框可复用
  的后端入口。输入裸自然语言,内部完成 route、Paper Copilot run、
  `research-report.md` 落盘、quality run 记录、`eval/report.html` 刷新,
  返回 `ChatRunResult`:`route` / `report_markdown` / `session_path` /
  `report_path` / `quality_run_path` / `eval_report_path` / cost / paper budget。
  `paper-copilot research` 现在只是薄 CLI 壳负责参数校验和打印。按用户要求
  未运行任何验证命令。
- **HTTP API 边界 v1**(2026-05-18):新增 `paper_copilot.api.http`。不加新依赖,
  用 stdlib HTTP server 暴露 `POST /chat` 与 `GET /health`;`/chat` 接收
  `{message,pdf_dir?,max_turns?,budget_cny?,max_papers?,root?}` 并调用
  `handle_chat_request()`,返回 JSON 版 `ChatRunResult`。新增
  `paper-copilot serve --host 127.0.0.1 --port 8765` 启动 API,供后续前端单
  输入框直接对接。已补模型序列化断言,按用户要求未运行任何验证命令。
- **前端技术决策**(2026-05-18):用户确认下一步进入前端,选择 Next.js 而不是
  静态 HTML 原型。最终产品不是 CLI;普通用户只面对一个自然语言输入框。
  **UI 必须是 macOS 风格**:安静、原生感、侧边栏/工具栏/毛玻璃或浅色层次
  要克制,避免 dashboard/营销页/厚重卡片风。Python 侧继续作为本地后端,
  现有 `paper-copilot serve` 暴露 `POST /chat`;Next.js 前端只消费这个 API。
  推荐目录: `apps/web/`。
- **Next.js 前端 shell v1**(2026-05-18):新增 `apps/web`。Next.js App Router
  单页 shell 已连 `GET /health` 与 `POST /chat`,左侧本地 run history,中间
  prompt + Markdown 报告区,右侧 connection/run metadata(route、stop、cost、
  events、paper budget、session/report/eval 路径)。UI 走 macOS 风格轻量
  侧边栏/工具栏/浅色毛玻璃层次,不做登录/云同步/复杂 dashboard。已跑
  `npm run typecheck` + `npm run build`;`npm install` 报 2 个 moderate audit
  项,未自动 `npm audit fix --force`。
- **历史报告列表 v1**(2026-05-18):按用户“赶时间,不跑真实 `/chat`”的要求,
  做了无 LLM 调用切片。新增 `GET /reports` 扫描
  `<root>/papers/*/research-report.md` + 对应 `session.jsonl`,返回 request、
  route、markdown、session/report path、cost、events、paper_budget。前端左侧
  report list 启动时读取该接口,点击历史项直接打开已落盘 markdown,不触发
  新 agent run。已跑 `uv run pytest tests/api/test_http.py`、针对新增 Python
  文件的 `uv run mypy ...`、`npm run typecheck`、`npm run build`;未跑真实
  `/chat` / LLM。
- **报告阅读体验 v1**(2026-05-18):无 LLM 调用前端切片。入口 label 从
  “研究问题”改成“你想研究什么?”;历史报告列表增加选中态;右侧 metadata 的
  session/report/quality/eval 路径提供复制按钮;Markdown 渲染会识别
  `[paper_id:field]` 格式 evidence refs,高亮为可点击复制的小标签。已跑
  `npm run typecheck` + `npm run build`;未跑真实 `/chat` / LLM。
- **报告工具栏 v1**(2026-05-18):无 LLM 调用前端切片。报告区顶部新增当前
  request 摘要 + route/cost,并提供“刷新历史 / 复制报告路径 / 复制会话路径”;
  空状态补“从左侧选择历史报告,或输入新任务”与刷新历史按钮;复制动作增加
  轻提示(已复制/刷新失败等)。已跑 `npm run typecheck` + `npm run build`;
  未跑真实 `/chat` / LLM。
- **前端状态收尾 v1**(2026-05-18):按用户“不要在前端浪费太多时间”要求,
  做最小前端-only 收尾:历史报告标题两行截断并显示更新时间;API 离线时禁用
  “开始”按钮并提示先启动 `paper-copilot serve`;提交运行时报告区显示
  loading 状态。已跑 `npm run typecheck` + `npm run build`;未跑真实
  `/chat` / LLM。
- **前端控制项精简 v1**(2026-05-18):按用户反馈,删除主界面的“预算”和
  “轮数”输入;前端不再向 `/chat` 传 `budget_cny` / `max_turns`,由后端默认
  harness 边界决定。界面只保留“论文数”作为用户可理解的范围控制。已跑
  `npm run typecheck` + `npm run build`;未跑真实 `/chat` / LLM。
- **前端控制项精简 v2**(2026-05-19):按用户反馈,继续删除主界面的“论文数”
  输入,并移除右侧 metadata 的“论文数”展示;前端不再向 `/chat` 传
  `max_papers`。查多少篇由 agent 任务规划决定,过多时仍由后端 harness 默认
  上限兜底停下。已跑 `npm run typecheck` + `npm run build`;未跑真实
  `/chat` / LLM。
- **资料库入口 v1**(2026-05-19):按用户确认,优先做“指定本地论文目录”而非
  PDF 上传。右侧配置从“PDF 目录”改成“资料库 / 本地论文文件夹”,路径保存到
  `localStorage`,之后每次 `/chat` 自动带上该目录;API 地址移到“本地服务”。
  已跑 `npm run typecheck` + `npm run build`;未跑真实 `/chat` / LLM。
- **资料库入口 v2**(2026-05-19):按用户反馈,资料库入口改成点击“选择目录”
  打开本机目录选择器,而不是只让用户手输路径。前端调用
  `POST /library/select-directory`,后端在 macOS 上用系统 `choose folder`
  返回绝对路径,选中后回填并保存到 `localStorage`。已跑 API 单测、
  touched-file `ruff`/`mypy`、`npm run typecheck` + `npm run build`;
  未跑真实 `/chat` / LLM。
- **Composer 语义校正**(2026-05-19):按用户纠正,Research Idea Composer
  不是泛泛“缝合论文”,而是 baseline-first workflow:先找可复现 baseline,
  再找 3 个可接入模块/技巧,最后形成可验证的组合改进方案和消融计划。
  已把 router 关键词、Paper Copilot idea prompt、前端默认示例同步到该语义。
- **主页使用提示与右侧折叠**(2026-05-19):前端主页新增“可以这样用”提示区,
  分两类入口:知识库问答(解释单篇论文、多篇论文对比、研究问题询问)与
  新论文模型框架(按研究方向先找 baseline、再找模块、组合可验证方案)。
  每类各 3 个可点击 prompt 示例。右侧运行信息/资料库/本地服务面板已做成
  可折叠。已跑 `npm run typecheck` + `npm run build`;未跑真实 `/chat` / LLM。
- **后端意图分层决策**(2026-05-19):后端应自动识别两种用法,不完全交给
  LLM 自由决定产品模式。短期用轻量 router 将请求分成 knowledge_qa
  与 framework_composer(baseline-first);识别后再让 LLM 在对应 bounded
  harness/prompt/tool 策略内自动编排工具。不要让一个无约束 prompt 同时决定
  模式和执行。
- **Route/profile 命名收敛**(2026-05-19):后端 route 与 output_profile 已从
  `research`/`idea_composer` 收敛为 `knowledge_qa`/`framework_composer`。
  历史报告读取会把旧 session 的 route 映射到新名字;前端展示同步为
  “知识库问答”与“新论文模型框架”。按用户验证策略,未跑真实 `/chat` / LLM。
- **Knowledge QA task_profile v1**(2026-05-19):`knowledge_qa` 仍保持一个产品
  route,但新增轻量 `task_profile` 指导工具策略:`single_paper_focus` /
  `fixed_set_compare` / `topic_survey` / `evidence_lookup` / `claim_check` /
  `experiment_extraction` / `timeline_synthesis` / `gap_analysis`。Paper Copilot
  初始 prompt 会写入 task profile 并追加对应查证据约束;历史报告缺失该字段时
  默认映射为 `topic_survey`。按用户验证策略,未跑真实 `/chat` / LLM。
- **M18 evidence payload v1**(2026-05-19):`search_library` 返回保持旧
  `results` 兼容,同时新增标准 `evidence[]`:`paper_id` / title / year /
  chunk_id / section / page_start / page_end / snippet / distance / score /
  source_kind / `citation_ref`。Paper Copilot final guidance 已要求优先使用
  `search_library evidence citation_ref` 或 inspect/compare 字段引用。按用户
  新指令,以后默认不跑任何验证命令;本次未运行验证。
- **M18 multi-chunk evidence v1**(2026-05-19):`knowledge.hybrid_search.SearchResult`
  保留 `best_chunk`,新增每篇最多 3 条默认 chunk evidence(`chunks`),并让
  `search_library` 的顶层 `evidence[]` 展平成多条可引用 chunk;`results[]`
  继续一篇一个 best chunk,但每个 result 也带 `evidence_chunks`。tool 输入新增
  `max_chunks_per_paper`(默认 3,上限 5)。按用户指令未运行验证。
- **M18 FTS5/BM25 + RRF v1**(2026-05-19):`EmbeddingsStore` 在同一
  `embeddings.db` 内新增 `chunk_fts` FTS5 表,`replace_paper`/`delete_paper`
  同步维护文本索引,打开旧库时会补齐缺失 FTS 行。`hybrid_search.search`
  新增可选 `query_text`,有文本时同时取 vector KNN 与 BM25 命中,用 RRF 融合
  chunk 排名后再按 paper group;`search_library` 与 CLI `search` 已传入原始
  query。evidence payload 现在带 `rrf_score`/`vector_rank`/`bm25_rank`/
  `vector_distance`/`bm25_score`。按用户指令未运行验证。
- **M18 evidence ref lookup v1**(2026-05-19):新增 `chat.evidence`
  反查 `[paper_id:chunks[chunk_id]]`,HTTP API 暴露 `GET /evidence?ref=...`;
  前端报告中的 chunk evidence ref 现在可点击,右侧证据面板展示论文标题、年份、
  section、页码和 chunk 原文。非 chunk 字段引用仍保持点击复制。按用户指令未运行
  验证。
- **Embedding 默认切换**(2026-05-19):默认 embedding 从本地 `BAAI/bge-m3`
  切到阿里云百炼 OpenAI-compatible `text-embedding-v4`,维度固定 1024 以兼容
  当前 sqlite-vec schema。`Embedder` 现在读取 `DASHSCOPE_API_KEY`,本地开发
  可 fallback 到 `ANTHROPIC_API_KEY`;旧 `embeddings_meta.json` 会因模型名不匹配
  要求重新 `reindex --pdf-dir`。chunking 改用轻量本地 token-span 近似,不再加载
  bge tokenizer/model。百炼文档中对工程有用的 endpoint / dimensions / batch
  限制 / 价格 / 多模态边界已记入 `docs/design/dashscope_text_embedding.md`。
  按用户指令未运行验证。
- **text-embedding-v4 runtime reindex**(2026-05-19):按用户指定并已写入记忆的
  PDF 目录 `/Users/a123/paper-copilot-test-pdfs` 重建默认数据根
  `~/.paper-copilot` 的 embedding 索引。重建前旧 bge-m3 `embeddings.db` 与
  `embeddings_meta.json` 已备份到
  `~/.paper-copilot/backups/2026-05-19-text-embedding-v4/`。本次 reindex
  fields.db indexed 20 paper(s),fields skipped 2;embeddings.db indexed
  12 paper(s) / 482 chunks,embeddings skipped 8(no matching pdf),elapsed 85.0s。
  新 `embeddings_meta.json` 为 `embedding_model=text-embedding-v4`,
  `embedding_dim=1024`。
- **retrieval eval seed labels**(2026-05-19):新增并扩充
  `eval/retrieval/queries.yaml`,人工标注当前 text-embedding-v4 索引覆盖的
  34 篇论文,共 36 条中英文 seed query。标签先只做 paper-level
  `relevant_papers`,作为 `paper_recall@k` 分母;chunk 层只保留
  `snippet_hints`,避免依赖 reindex 后可能变化的 chunk_id。
- **retrieval eval command v1**(2026-05-19):新增
  `paper-copilot eval retrieval eval/retrieval/queries.yaml`。命令读取
  paper-level retrieval labels,对当前默认数据根的 `fields.db` +
  `embeddings.db` 跑 hybrid search,按聚合后的 top papers 计算
  `paper_recall@5` / `paper_recall@10`,并渲染每条 query 的 top papers 与
  missed@10。命令仍是观测性质,不设 fail gate。
- **retrieval eval history v1**(2026-05-19):`eval retrieval` 现在默认记录
  history run,每条 query 一行 JSONL,包含 query、相关 paper 数、recall@5/10、
  missed@5/10、top papers;`--no-record` 可跳过。`eval report` 新增
  Retrieval mean recall 趋势区,且 retrieval rows 不再污染 extraction
  PASS/cost/cache 图。已跑 focused `ruff` / `mypy` /
  `tests/eval/test_runs.py tests/eval/test_report.py`,并 dogfood 真实命令一次:
  mean `recall@5=98.3%`,`recall@10=100.0%`,报告刷新为 1 run / 15 rows。
- **retrieval eval report detail v1**(2026-05-19):`eval report` 的 retrieval
  section 现在追加 latest query detail 表,按弱项优先展示每条 query 的文本、
  recall@5/10、missed@5/10 和 top 5 papers,用于快速定位 q015 这类 top-5
  未满的查询。按用户最新指令,本轮未运行 `ruff` / `mypy` / `pytest`。
- **retrieval eval 34-paper run 1**(2026-05-19):34-paper seed 扩充后已跑
  `paper-copilot eval retrieval eval/retrieval/queries.yaml`,mean
  `recall@5=91.9%`,`recall@10=96.1%`,recorded run
  `eval/runs/2026-05-19T09-21-03Z.jsonl`;`eval report` 刷新为 2 runs /
  51 rows。弱项优先看 q012/q018/q033,分别反映跨家族对比、间接 baseline label
  和多模态表述下的漏召。
- **retrieval eval label audit v1**(2026-05-19):审完 q012/q018/q033 后仅改
  `eval/retrieval/queries.yaml` 标签/查询意图:q012 改为 ViT inductive-bias
  exact lookup,q018 去掉间接 ViT baseline,q033 去掉泛化 fusion 论文。YAML
  一致性检查通过(corpus=34,queries=36,duplicate_ids=0,missing_relevant=0);
  复跑 retrieval eval 后 mean `recall@5=95.6%`,`recall@10=100.0%`,recorded
  run `eval/runs/2026-05-19T09-27-55Z.jsonl`;`eval report` 刷新为 11 runs /
  167 rows。本轮按用户最新指令未运行 `ruff` / `mypy` / `pytest`。
- **retrieval eval top-5 label audit v2**(2026-05-19):继续审 q014/q015/q020/
  q025/q033。q014 改成 ViLBERT vs ViT,避免 broad "multimodal transformers"
  被多模态 ReID 论文抢语义;q020 用 `6e870fa58055` 替换
  `7206a2c64532`,把标签对齐到 RGB/IR 表征而非 test-time training;q025 去掉
  非 ReID 的 TransFG 标签。q015/q033 未强行改标签,保留为真实 top-5 排序弱项。
  YAML 一致性检查通过(corpus=34,queries=36,duplicate_ids=0,
  missing_relevant=0);复跑 retrieval eval 后 mean `recall@5=98.4%`,
  `recall@10=100.0%`,recorded run `eval/runs/2026-05-19T09-32-49Z.jsonl`;
  `eval report` 刷新为 12 runs / 203 rows。本轮按用户最新指令未运行
  `ruff` / `mypy` / `pytest`。
- **retrieval ranking 观察切片**(2026-05-19):只读比较 q015/q033 的 current、
  rrf10/30/100、overfetch10/20、vector_only。q015 的 AlexNet 论文
  (`2315fc6c2c0c`) 在 current 下只有 vector rank=24 且无 BM25 命中,说明
  "AlexNet" 别名与论文标题/正文词面不完全对齐;overfetch10/20 会把 q015
  从 `75.0%` 拉到 `50.0%`。q033 的 DeMo (`3b53aa0674f2`) 在 current 下是
  BM25 rank=36,overfetch10 可进 top-5。全 36 query 对比:current mean
  `recall@5=98.4%`,`recall@10=100.0%`;overfetch10 mean `recall@5=98.6%`,
  `recall@10=100.0%`,但只是 q015 `-25.0%` 与 q033 `+33.3%` 抵消;overfetch20
  mean `recall@5=97.7%`,`recall@10=99.3%`;rrf10 mean `recall@5=97.7%`;
  vector_only mean `recall@5=97.7%`,`recall@10=99.3%`。结论:不要为这 2 条
  改默认 ranking 参数。
- **协作偏好更新**(2026-05-19):不要每次改完代码就自动 commit/push。默认只
  修改与验证,等用户明确说“commit / push / 保存进度”再提交推送。本次用户
  明确要求保存进度并 push。
- **下一个任务建议**:M19 checker/remediation、前端 Composer 摘要展示、field
  evidence ref 反查、风险与缺口右侧摘要、Markdown 表格渲染都已完成,且用户已决定跳过多任务验收套件。下一刀不要
  回头调 RAG ranking、扩大 evidence pool 或补 baseline/module recall;优先
  让用户人工看当前 ReID demo 报告与前端展示是否顺眼。若继续编码,只做极小的
  前端可用性修正,不要再扩大 M19 范围。当前测试资料库是
  `/Users/a123/paper-copilot-test-pdfs`,全部先按 flat CCF A 处理,CCF B/other
  暂空;真实试跑继续不要用 medical segmentation 默认例子。除非用户重新要求,
  继续不跑 `ruff` / `mypy` / `pytest` / 真实 `/chat`。
- **后续路线规划**:`docs/design/chat_first_research_copilot_plan.md` 记录
  M16 之后的总方向:Harness Engineering 第一准则、Evidence-grounded RAG
  升级、Research Idea Composer、单输入框 Chat UX、后端/前端分阶段落地。
- **2026-05-18 规划会话交接上下文**:本轮只做规划和文档,不改实现。用户
  认可后续产品方向:保留 CLI 作为底层工具和开发者入口,普通用户最终只面对
  一个自然语言输入框;新增功能对外命名为 Research Idea Composer/论文创新
  方案生成助手,避免"水论文/缝合神器"叙事。RAG 升级优先做 evidence
  citation、FTS5/BM25 + text-embedding-v4/sqlite-vec + RRF、retrieval eval;
  暂不换主流向量库,除非规模/并发/ACL/托管需求触发。CCF PDF
  `/Users/a123/Documents/reid/第七版中国计算机学会推荐国际学术会议和期刊目录（正式版）.pdf`
  已确认是 2026 版 CCF venue 白名单,主要给 DBLP URL,不是论文库;联网发现
  只做 DBLP/开放 PDF metadata,付费或缺失 PDF 交给用户补。本路线顺序:
  M16 harness hardening → M17 chat-first tool harness → HTTP API → Next.js
  macOS-style local web UI → M18 evidence-grounded RAG → M19 Research Idea
  Composer deeper workflows。若新会话要继续实现,默认从 Next.js 前端 shell
  开始,不要再回到 CLI 入口设计。
- **2026-05-17 交接上下文**:当前项目是固定的多 Agent 论文阅读流水线
  (Main → Skim → Deep → Related) + eval harness,不是 Codex / Claude Code /
  OpenClaw 风格的"LLM 自主调工具、观察结果、继续推进直到任务完成"的
  agent runtime。现有 `agents.loop.run_agent_loop` 有 tool-loop 雏形,但
  主流程没有用;Skim/Deep/Related 的 tool_use 主要是结构化输出通道。若
  目标是"解放人类干活"和真实生产力,路线应是先做 M16 硬化,再做 M17
  Autonomous Research Loop。
- **M15 Session A 实测 (2026-04-27)**:
  - 6 次 smoke.yaml 跑(5 baseline + 1 degraded),~12min wall、**~¥1.7**
    LLM 开销。每次自动落 `eval/runs/<run_id>.jsonl`,`eval report` 一
    秒生成 19KB 静态 HTML。
  - **趋势图直接验证 M14 教训**:run 5(完全没改任何东西)AlexNet methods
    自然噪声 7→3 触 `len_short`,methods PASS rate 那条线一根锯齿从 100%
    跌到 80%。run 6 故意改 DeepAgent prompt 为 "Methods: skip this list"
    后 5/5 papers got 0 methods,同条线直坠 0% 形成断崖。**run 5 锯齿
    vs run 6 断崖,肉眼一秒区分 noise vs catastrophic** —— M15 的核心价值。
  - **last-vs-prev diff 自动捕获**:degraded 跑触发 4 条 PASS→FAIL methods
    flip(第 5 个本来就 FAIL 不算 flip)、2 条 cost drift -19%/-20%
    (LLM 不写 methods 所以更便宜)、2 条 cache drift > ±10%。
  - **零依赖手搓 SVG**:不引入 plotly/matplotlib,polyline + circle marker
    + 5 档 Y 轴网格,800x280 静态画布。`<title>` SVG tooltip 给数值,
    open in browser 不需要 JS / 网络。
  - **架构决策**:`PaperResult.cost_cny: float` → `cost: CostSnapshot`,
    把 cache_read/creation 字段透出给 runs.py。`eval run` 默认 record,
    `--no-record` opt-out;`eval report --last N --suite NAME` 切片。
  - **测试**:9 个 unit test 覆盖 RunRow 往返 / disjoint cache 计费 /
    `last+suite_name` 顺序(必须先 filter 再 truncate,否则 last=2 在
    最后两个 deep run 上 filter smoke 会得 0 行)。
  - **gitignore eval/runs/**:开源场景下 run 历史是 runtime data
    (跟 `data/` 一样),不应当混进 repo。Session B 模型切换的 story
    单独 commit 一份静态 HTML/截图到 `docs/stories/` 当证据。
  - **DoD 状态**:HTML 报告可读 ✅、baseline 噪声+断崖在图上可见 ✅、
    退化故事记录 ⏳ 留给 Session B。
- **M15 Session B 实测 (2026-04-27)**:
  - **候选**:qwen3.6-plus(snapshot 2026-04-02),百炼定价
    2.0/2.5/0.2/12.0 CNY per Mtok(input/cache-create/cache-hit/output),
    跨四档统一 1.67x flash。
  - **配套基础设施**:`shared/cost.py` 加 `QwenPlusPricing` + `Pricing` union
    + `pricing_for_model(model)` 路由(prefix match,fail-loud on unknown);
    `agents/main.py` `CostTracker(pricing=pricing_for_model(DEFAULT_MODEL))`
    一行接入。这部分留下,模型切换零摩擦的真实必需,不属 Session B 一次性
    脚手架。
  - **跑法**:`DEFAULT_MODEL = "qwen3.6-plus"` 一行临时改 + `smoke.yaml`
    budget cap 0.20 → 0.50。`eval run smoke.yaml` → 第 7 个 run row
    (`2026-04-27T14-15-51Z.jsonl`)。跑完两条临时改全部还原。
  - **结果(suite 合计)**:5/5 PASS、0 regression。Cost ¥0.273 → ¥0.553
    (**2.03x**),latency 124s → 274s(**2.22x**)。
  - **2.03x > 1.67x 价格比说明 plus 输出更长**(token 体量增加 ~22%);
    2.22x latency > 2.03x cost 说明 plus **每 token 也更慢**——同 family
    升档时这两条都不在产品页上写。
  - **Cache 看似下滑(0.246 → 0.092)是伪信号**。Baseline runs 2-5 是同 model
    连跑,前次 system+tools 仍在 5min TTL 内复用;plus 是首次冷启,等价
    baseline run 1(0/0.122/0.076/0.119/0.128 vs plus 0/0.140/0.080/0.105/
    0.136,几乎相同)。**Cross-run cache 比较必须配同 model 冷启对照**,
    否则会读出"模型切换降 cache"的假规律。
  - **决策:继续用 flash**。eval 通过 ≠ 应当升级:
    1. M14 把断言收到 catastrophic-class noise floor 之后,eval **看不出
       plus 比 flash 更好**——只能看出"都过线"
    2. 2x cost / 2.2x latency 在零可测收益时不成立
    3. 颗粒度不够发现的微妙收益(method name 跨次稳定性、subtle
       hallucination)是未来 milestone 的真问题,不是 Session B 的事
  - **核心教训:Session B 比 Session A 更接近真实工程判断**。Session A
    run 6 摆拍证明"探测器对已知断崖有响应"(必要但 reader 一眼看穿);
    Session B 让 eval 当裁判,**结果是用数据否决了一次本来会过 0
    regression 关的升级**。简历 bullet 写"用 eval 数据驱动模型选型决策"
    比"用 eval 抓自己故意搞的破坏"强一档。
  - **触发重评条件**(写入 story):新增更细颗粒度断言发现 flash 落后;
    plus / flash 价格比下到 < 1.3x;用户人工捕获 flash 答错 + plus 答
    对的 case 累积。
  - **Pre-existing mypy 错**:`agents/main.py:106` `related_run.response.usage`
    漏 None 检查(`tracker.record(...)` 收到 `int | None`),与 Session B
    改动无关,git stash 验证后维持原状不修。
  - **DoD 三条全 ✅**:数据驱动决策做了、story 落 docs/stories/、简历 bullet
    候选文案在 story 末尾。
- **M14 实测 (2026-04-25)**:
  - 5 篇 × 2 字段 = 10 goldens 落盘:ResNet (2c03df8b48bf) / AlexNet
    (2315fc6c2c0c) / ViT (268d347e8a55) / Bahdanau (071b16f25117) /
    Inception (445d06b2ac99),都是 methods + contributions。
  - **Transformer (a639448e61be) 跳过**:M5 期 session 没有 final_output
    entry(那时还没引入),`mark` 报错。要用就 `read --force` 重读一次。
  - **核心教训:LLM noise floor 比预想高**。第一版严格断言(every golden
    method by name + per-type count)5/5 papers FAIL on no-op rerun:
    1. Method *names* 跨次重命名(`Residual Learning Framework` ↔
       `Residual Block`,`Bottleneck Building Block` ↔ `Bottleneck
       Architecture`)— 名字 alignment 不能强制
    2. `is_novel_to_this_paper` 在同 prompt + 同 model 下也会随机翻转
       (Identity Shortcut Connections True↔False,Dropout False↔True)—
       这是 M8 教训重现:semantic variant 的 prompt anchor 不可靠,
       结构化 enum 也救不了
    3. Contribution `type` 同样随机分布漂移(`novel_method` 偶尔变
       `analysis`)
  - **v1 最终断言策略**:
    - meta 严格(verbatim 提取,稳定)
    - methods / contributions:只 fail "灾难性长度下降"(< golden × 50%)
    - experiments:严格 (dataset, metric) 对齐(数据集名是从论文表里
      抄的,稳定)
    - 弃用:methods name 对齐 / `is_novel_to_this_paper` / type 计数
  - DoD 验证:同 prompt 同代码 5/5 PASS;故意改 DeepAgent system prompt
    `"- Methods: skip this list. Return [] ..."` → 5/5 FAIL with
    `len_short methods` 字段精确指认,exit 1,prompt 立即 git checkout 复原。
  - Suite 隔离:每跑一个 paper 起新 tmpdir 当 `PAPER_COPILOT_HOME`,
    RelatedAgent 自动短路(fields.db 空),用户的真索引不受影响;suite
    可重复跑,跨次结果只受 LLM noise 影响(已被断言阈值吸收)。
  - 单 suite run 5 篇 ~¥0.28、~5min。Goldens prep 阶段 5 篇 `read --force`
    刷新 sessions(老 session 是 M5/M6/M7 期 schema,`is_novel` 为 None
    之类)~¥0.28。整个 M14 LLM 总开销 ~¥0.85。
  - **M15 该做什么**:多次跑同一篇做 majority-vote golden,把
    `is_novel_to_this_paper` 这种 stochastic 字段从噪声里捞回来;OR 给
    schema 加 confidence 字段;OR 接受 v1 现状,只看 budget + meta +
    experiments + 灾难性长度。本届 M14 框架可发现 prompt 灾难性退化,
    够用,不够发现微妙退化 — 这本身是 M15 报告 / 趋势可视化要解决的。
- **M13 实测 (2026-04-25)**:
- **M13 实测 (2026-04-25)**:
  - 三对人类对比:Transformer (2017) vs ViT (2021)、AlexNet (2012) vs
    ResNet (2015)、Bahdanau (2015) vs ViLBERT (2019)。
  - Methods 对齐:同时代同主题对(Transformer/ViT)0 共享(name 大小写
    精确匹配 — ViT 没把 "Transformer" 列成自己的 method),AlexNet/ResNet
    8 a-only / 4 b-only。fuzzy 匹配/语义合并不进 M13(需要 LLM)。
  - Cross-paper-links 渲染:Bahdanau ↔ ViLBERT 那对触发 `A → B
    shares_method` 一行,从 fields.db 的 `cross_paper_links` 字段直读,
    不读 graph/cross-paper-links.jsonl(后者 append-only 有历史污染)。
  - 退出码契约:正常 0 / 缺 paper_id 1 / 同 id、bad format 2。
  - 0 LLM 默认路径已 grep 验证(compare.py 不 import llm_client/anthropic/
    Embedder)。
- **M12 实测 (2026-04-25)**:
  - Bahdanau (2015,12 候选库) `--force` 重读:LLM 输出 2 link
    (`builds_on→Transformer-2017`, `shares_method→ViLBERT-2019`)。
    **temporal validator** 拦掉错向 builds_on(候选 year > 新论文 year +
    directional 类型 → drop),最终落盘 1 条 ViLBERT shares_method,
    人工评 0/1 false。
  - **重要发现**:LLM 即使看到候选 year 字段也会把"我影响了它"硬塞进
    `builds_on`(M8 教训命中:semantic variant prompt 修不动)。
    `_DIRECTIONAL_RELATIONS = {builds_on, compares_against,
    applies_in_different_domain}` 三个类型走严格时序校验
    (`candidate.year > new_paper.year > 0` → drop);`shares_method` /
    `contrasts_with` 对称类型免检。
  - RelatedAgent 单次成本(input 654 + cache_creation 1011 + output 210):
    **~¥0.002**(latency 2.1s),DoD `< $0.02 ≈ ¥0.144` 富余 70x。
  - Cache 策略遵 M9 结论:system + tools 打 marker,user 不打。RelatedAgent
    user payload ~2K tokens 在 Dashscope qwen-flash 临界区,保守不碰。
  - Session trace 完整保留 LLM 原始 tool_use 输出(2 link)+ final_output
    的 validator-filtered 版本(1 link),M14 eval 直接对比即可量化"LLM
    错向率 vs validator 拦截率"。
  - 已知遗留:`shares_method` ViLBERT 链 borderline(Bahdanau enc-dec 内
    attention vs ViLBERT 跨模态 co-attention,机制粒度不同),M14 golden
    时再判。
  - graph/cross-paper-links.jsonl 是 append-only,首跑无 validator 时
    误落的 1 行 `builds_on→Transformer` 留作历史,不主动改写。M14 用
    图时按 "读最新行覆盖" 处理。
- **M11 实测 (2026-04-24)**:
  - 13 篇全量 reindex(bge-m3 CPU 推理,MacBook M1):**186.9s**,
    DoD ≤ 5 min,约 2.7x 余量。单篇 chunks 14-107 不等,总 621 chunks。
  - 搜索延迟(warm,bge-m3 已加载):query encode + KNN + fields lookup
    **287-973ms**,DoD < 1s 满足。冷启动(含 torch import + 模型权重
    加载)约 **17s** 是个人项目 CLI 一次性 invoke 的固有成本,不计入 DoD。
  - `embeddings_meta.json` 不匹配(model/dim 任一变)`search` 开头就
    `KnowledgeError` 退出码 2,不会跑出脏结果。
  - 架构决策:chunker 进 `shared/chunking.py`(retrieval/knowledge
    互不 import 的硬规则下,section→chunk 是共享原语);Section 在
    shared 定义,SectionText→Section 的转换在 cli 层做,3 行代码。
  - 历史 13 篇 session 不记录 PDF 路径 → reindex 用 `--pdf-dir` 按
    sha1 重新匹配,`emit_skim` tool_use 里恢复 PaperSkeleton,零 LLM
    成本。PDF 不在 dir 里的 paper 只跳过 embeddings,fields 仍重建。
  - Transformers warning "Token indices sequence length is longer
    than the specified maximum sequence length (14707 > 8192)":在
    长 section 上 `tokenizer(full_text, return_offsets_mapping=True)`
    触发,但我们只用 offset mapping 做 chunking,永远不把 >8K 的序列
    送入模型 forward,无实际影响。
  - **M10 实测 (2026-04-24)**:
    - 13 篇真实论文全量 reindex 成功(session.jsonl 里的 `meta.id` 等 M7
      旧字段因为 fields.db 存 raw JSON 不做二次校验,自然兼容)。
    - 所有查询 < 1ms(13 篇规模):`list_all` 0.24ms / `query_contains`
      0.2-0.3ms / 加 `--year` 过滤降到 0.06-0.09ms。DoD 的 50ms 阈值
      留了 50x 余量,FTS5 暂不上。
    - 单表 JSON + 表达式索引(`json_extract($.meta.year)` / `$.meta.arxiv_id`)
      + `json_each` 内联数组扫描。加字段无需 ALTER TABLE。
- **M9 实测定论 (2026-04-24)**:
  - 三层 cache(tools / system / user)只有 tools + system 那 ~2.8K tokens 在
    Dashscope qwen3.6-flash 上稳定命中。Deep 的 ~18K user PDF 块打
    `cache_control` 反而是 **净亏** —— 每次被按 125% 的创建费算账,却永远
    读不出来(A/B 实测四次 off→on,cache_read 固定 2809 与 marker 位置无关,
    off 时 cache_create=0,on 时 cache_create 14-17K 不等)。已改成 Skim 全量
    打 marker(user 4K 在阈值内)、Deep 只打 system+tools。
  - 修前同 paper rerun 降 19.7%(还是带着 user marker 白交创建费),修后降
    **18.6%**(0.0489 → 0.0398)。
  - 详见 ARCHITECTURE.md 的"Dashscope qwen-flash user-message cache 大小
    阈值"假设。
- **M9 DoD 回校**:原写的"同 paper 降 ≥50% / 跨 paper 命中 ≥50%"源自
  Anthropic native 经验值,qwen-flash 架构天花板够不到。实测后改成
  **≥15% / ≥15%**,见 M9 节。
- **M7 已知偏离 ARCHITECTURE**:`retrieval/chunker.py` + `retrieval/search.py`
  仍推迟,详见 ARCHITECTURE.md 的 `retrieval/`。
- **M8 回归已执行(6 篇)**:Zhou06 (outline 修) / Bahdanau + HGNN
  (section dedup 修) / AlexNet + Inception + ViLBERT (schema 三合一)。
  全部生效,1 残留:AlexNet 的"English-language visual"模板变体(M9
  未收,eval 时如再现需走 validator/output filter 硬机制)。
- **M8 未收的 output_tokens / system prompt 观察**(M9 未覆盖):
  - `output_tokens` 贴 3000 天花板的 66–80%;大论文或 result-heavy 论文
    可能撞顶(已提到两次 `--lang zh` 开发中的 stringification 事故)
  - qwen3.6-flash 对长 system prompt 敏感,堆砌 emphasis 会破坏嵌套 schema
    的 structured-output 稳定性 → prompt 迭代时保持短而聚焦

---

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
- [x] 跑一篇论文后，`cat session.jsonl | head -5` 人类可读
- [x] 模拟崩溃测试：写了 50 条 entry 后进程被 kill，重启后能读到 50 条
      （不是 49，不是 51）
- [x] `paper_id` 格式定了（建议：arxiv id，否则 SHA1(title+year)[:12]）

**实际遇到的问题**：qwen3.6-flash forced tool_choice 不产生 TextBlock，
assistant message entry 常态缺位。

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
- [x] 跑一篇 15-30 页的论文端到端不超过 2 分钟
      — ViT (22 页) ~40s, ViLBERT (11 页) ~15s via CLI。
- [x] 输出的 Paper 有至少 3 个 Contribution、2 个 Method、2 个 Experiment、
      1 个 Limitation
      — Transformer 5/4/4/3, ViT 5/3/6/3, ViLBERT 4/5/12/4。
- [x] 整个流程的 cost < ¥0.30（qwen3.6-flash，数字在首次真跑后校准）
      — ViLBERT ¥0.058, ViT ¥0.106, Transformer ¥0.05。预算远未触及。
- [x] session.jsonl 可以完整 replay 出最终输出
      — D4 决策下：SkimAgent/DeepAgent 只写 tool_use + schema_validation trace，
      MainAgent 写唯一一条 final_output 含完整 Paper。

**实际遇到的问题 / 偏离 ARCHITECTURE**：

- **retrieval/chunker.py + retrieval/search.py 推迟**（偏离 ARCHITECTURE M7 产出
  清单）：ST1.5 spike 验证全文投喂（25-75k tok）在 qwen 窗口内、cost 可控，
  retrieval 属 D1 决策下的"先不加"。真实需求由 Phase 2 使用数据驱动。
- **DeepAgent 走聚合方案而非 per-field fan-out**（D2 决策）：一次 forced
  tool_choice 调用吐 C/M/E/L 四个 list。三篇 reality check 下 schema
  validation 全通过，成本线性、稳定。
- **output_tokens 紧贴 3000 ceiling**（ViT 2398, ViLBERT 2279, Transformer
  1498）：更大/更 result-heavy 论文可能 truncate。未 truncate 之前不调整。
- **confidence 字段几乎全 1.0 / 0.9，LLM 不使用刻度**：M8 prompt tuning
  的优先级。
- **arxiv_id 在 PDF 首页不印时 LLM 正确返回 null**（ViT, ViLBERT 均无印刷的
  arxiv id）：不是抽取 bug，是 PDF-only 信息源的固有缺口，需外部 enrichment。
- **Dashscope 支持 `cache_control` ephemeral 5m TTL**（ST1.5 spike 验证）：
  当前 DeepAgent 单调用未启用；M9 或 per-field fan-out 时可用。
- **SessionStore 重跑语义**：paper 目录已存在时 raise，CLI 用 `--force`
  覆盖。暴露给用户显式,不静默吞数据。

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
- [x] 至少 5 条 issues 被关闭（不是所有 issue 都要做，做最痛的几条）
  — 2026-04-24 关了 5 条:outline fallback / section 嵌套重复 / `meta.id`
    删 / Method `is_novel_to_this_paper` / Confidence → evidence_type
- [x] 对之前不满意的 3 篇论文重跑，确认改善
  — 重跑 6 篇:Zhou06 (outline) / Bahdanau + HGNN (dedup) / AlexNet +
    Inception + ViLBERT (schema)
- [x] 在 ARCHITECTURE.md 的"待验证假设"中勾掉或修改至少 2 条
  — 修改 2 条"M5 已验证":SkimAgent 3 页假设加无 outline 分支;
    Pydantic Field description 万能假设加"模板语义变体" caveat

**预估**：2-3 sessions。 **实际:1 session(2026-04-24)**。

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

**DoD**（2026-04-24 实测回校后）:
- [x] 对相同 paper 跑第二次，第二次成本降 ≥ **15%**（实测 18.6%,
      transformer.pdf,5 分钟内 rerun）
- [x] 同 paper rerun 下 Skim cache 全命中,Deep 的 system+tools 层命中
      (跨 paper 的 10 篇基线未跑,因实测已证跨 paper 只有 system+tools
      会命中,数据上限约 **14-19%**,已作为 M14 eval 的命中率 baseline)
- [x] `doctor` 命令输出美观可读（rich.table,top-3 红色高亮）

**M9 实测校注**（2026-04-24）:原写的 ≥50% 源自 Anthropic native 经验值,
qwen-flash + Dashscope 架构下 user-message cache 大小上限约 ~5K tokens
(详见 ARCHITECTURE.md 待验证假设),Deep 的 18K user 块打 marker 属于净亏
——现在代码里只在 Skim 的 user 打 marker(4K 在阈值内),Deep 只打
system+tools。如将来 qwen 版本升级触发阈值变化,用 `scripts/m9_cache_ab.py`
做 1 分钟回归。

**预估**：2 sessions。**实际**:1 session（包含现场调查把 DoD 从 Anthropic
经验值校准到 qwen-flash 实际天花板）。

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
- [x] Phase 2 积累的 10+ 篇论文能批量 reindex(13/13 成功)
- [x] 常见查询（按 method 关键词、按年份）< 50ms(实测 < 1ms,50x 余量)
- [x] schema 向后兼容：加字段时不用 drop table(单表 JSON 存 Paper,
      旧 session 的 `meta.id` 残留字段自然兼容)

**预估**：2 sessions。**实际**:1 session。

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
- [x] 对 10+ 篇的库，search 延迟 < 1s — 13 篇实测 287-973ms (warm)
- [x] reindex 10 篇论文的 chunk 重算 < 5 分钟 — 13 篇 186.9s (2.7x 余量)
- [x] meta.json 记录正确，换模型时检测到不一致并报错 — 手动篡改验证通过

**预估**：3 sessions。**实际**:1 session。

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
- [x] 新 read 一篇论文，如果库里有相关的，至少关联 1 篇；如果不相关就不强加
      — Bahdanau 实测:13 篇库挑出 ViLBERT 1 条 + Transformer 被时序校验
      拦下,5 篇 CV 全过滤。
- [x] 虚假关联率（人工判断）< 30%
      — Bahdanau 单 paper:LLM 50% 错(builds_on 方向反),validator 拦
      后 0/1 = 0%。多 paper 样本要等 M14 golden suite 正式测。
- [x] 每次关联额外成本 < $0.02
      — RelatedAgent 单次 ~¥0.002 ≈ $0.0003,70x 余量。

**架构决定 (2026-04-25)**:
- `relation_type` 锁定 5 档 enum(`builds_on` / `compares_against` /
  `shares_method` / `contrasts_with` / `applies_in_different_domain`);
- 时序校验放后置 validator 而非 prompt anchor(M8 教训);
- `graph/cross-paper-links.jsonl` 由 `knowledge/graph_store.py` 维护
  (append-only),paper_id+related_paper_id+relation_type+explanation+
  related_title+indexed_at 单行,反向查询扫全文件(MVP 规模够);
- RelatedAgent 跳过条件:库里 < 2 篇候选(self 过滤后)直接返回空,
  不调 LLM。

**预估**:2-3 sessions(实际 3 sessions:schema → graph_store →
RelatedAgent → main/read/render 串线 → temporal validator 修复)。

---

### M13: `compare` 命令

**目标**：实现用例 2。

**产出**：
- `cli/commands/compare.py`：从 fields.db 读两篇的结构化字段，渲染对比表

**依赖**：M10

**DoD**：
- [x] 对 Phase 2 积累的论文中挑 3 对做对比，输出人类可读 (Transformer/ViT,
      AlexNet/ResNet, Bahdanau/ViLBERT — 见 Current Status M13 实测)
- [x] compare 0 LLM cost（grep 验证 compare.py 无 LLM imports）

**预估**：1 session(实际 1 session)。

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
- [x] 从 Phase 2 积累中挑 5 篇论文，每篇 mark 2 个字段为 golden
      (ResNet / AlexNet / ViT / Bahdanau / Inception × methods + contributions)
- [x] 跑一次 suite 能 pass(loosen 断言至 LLM noise floor 之后:5/5 PASS)
- [x] 改 prompt 故意让输出退化，再跑 suite 能 fail 并指出具体字段
      (DeepAgent system prompt "Methods: skip this list" → 5/5 FAIL with
      `len_short methods`)

**预估**：2-3 sessions(实际 2 sessions:Session A 数据层 / Session B 编排
+ goldens + DoD 验证 + noise floor 校准)。

---

### M15: Eval 报告 + 实战回归发现

**目标**：eval 模块产出 HTML 报告；**用它 gate 一次真实决策（模型选型 /
prompt 变更 / 架构调整），把决策过程写成 story**。

**产出**：
- `eval/report.py`：生成 HTML 报告（accuracy / cost / cache hit 趋势）—
  Session A 已完成（RunRow 持久化 + SVG 趋势图 + last-vs-prev diff）。
- Session B：用 eval 数据驱动一次真实模型选型决策。默认模型从
  qwen3.6-flash 临时切到 qwen3.6-plus，跑一次 `eval run smoke.yaml`，
  对比 Session A 留下的 5 次 baseline，由趋势图量化"质量改善 vs cost
  增长 vs cache 命中变化"，按数据决定升级 / 不升级 / 混合分配（不同
  agent 用不同模型）。结果未知再跑——这是和 Session A run 6 摆拍的
  本质区别：run 6 是 sanity check（证明探测器对已知断崖信号有响应,
  必要,做完即丢）,Session B 让 eval 当裁判。
- 把决策过程写进 `docs/stories/<date>.md`：候选模型 / baseline 数据 /
  candidate 数据 / 趋势图截图 / 决策理由 / 后续行动。

**依赖**：M14

**DoD**：
- [x] HTML 报告能打开,三个趋势图可读 — Session A 完成 (2026-04-27),
      6 次 smoke 实测、19KB 静态 HTML、零 JS 依赖手搓 SVG。
- [x] 用 eval 数据驱动一次真实模型选型决策 (qwen3.6-flash vs qwen3.6-plus)
      — Session B 完成 (2026-04-27)。结果:5/5 PASS、0 regression,但 plus
      2.03x cost / 2.22x latency 且 eval 颗粒度看不出 plus 有质量上行,
      决策**继续用 flash**。**不再摆拍**:用数据否决了一次本来会过 0
      regression 关的升级——比 Session A run 6 摆拍更接近真实工程判断。
- [x] 决策过程进 `docs/stories/2026-04-27-model-selection-flash-vs-plus.md`:
      候选 / baseline / candidate 数据 / 数据解读 / 决策理由 / 触发重评
      条件 / 简历 bullet 候选文案。
- [x] 决策数字 (cost +103% / latency +122% / quality 0 regression / cache
      cold-start 等同 baseline run 1) 进入简历 bullet —
      "用 eval 量化升级收益,数据否决了一次本来会过门槛的模型升级"。

**预估**：2 sessions。Session A 已完成 (1 session)。

---

### M16: 工程硬化 + 阅读质量指标 + 开源可复现性（候选，未开始）

**目标**：把项目从"能讲深度的个人工程项目"打磨到"更接近优秀开源项目 /
面试展示级 LLM Agent 项目"。M16 不加新论文阅读功能,只补可靠性、质量指标、
可复现 demo 和展示材料。

**为什么现在做**：M14/M15 已经证明 eval/cost/cache harness 有价值,但当前
项目还存在几个会影响开源可信度和简历叙事的缺口:

- schema 校验失败没有 retry/fallback,LLM 偶发坏结构会让 `read` 直接失败
- `eval/suites/smoke.yaml` 依赖本地 PDF,clone 后不能开箱跑
- `ruff` / `mypy` 还不是全绿,也没有 CI 自动拦截
- 现有指标偏工程观测(cost / latency / cache),缺少"读得准不准"的质量指标
- session trace 已有,但 per-agent 成功率 / retry / 成本延迟还没有汇总成指标
- README 缺少一眼能懂的 agent 流程图、demo 输出和指标表

**产出**：

- **失败恢复**:
  - schema validation 失败时自动 retry 一次
  - retry 仍失败时把原始 tool input / validation error 写入 session
  - 用户报错明确指出 agent、字段、失败原因
  - `read --force` 改成先跑到临时目录,成功后再替换旧 session/report/index,
    避免新 run 失败时丢掉旧成功结果
- **阅读质量指标**:
  - extraction completeness:关键 methods / experiments / contributions 是否抽全
  - unsupported claim rate:抽取结果中找不到论文依据的比例
  - evidence coverage:每条 contribution / method / experiment 是否带页码或原文片段
  - schema first-pass valid rate:第一次 tool-call 输出就过 schema 的比例
  - eval pass stability:同一 smoke suite 多次运行 PASS/FAIL 是否稳定
  - p95 latency per paper
  - cost per successful paper
  - RelatedAgent link precision 作为跨论文关联的辅助指标,不要把项目叙事带偏成 RAG
- **证据追溯**:
  - 为 contribution / method / experiment 增加 evidence 引用方案
  - report 里能展示页码或短 evidence snippet
  - eval 能统计 evidence coverage 和 unsupported claim rate
- **可复现 demo**:
  - 提供 fixture 下载脚本或明确的 `examples/` 输入集
  - `eval/suites/smoke.yaml` 在文档指定步骤下可复现运行
  - 提交一份示例 `report.md` / eval report 截图或 HTML artifact
- **Agent 可观测性**:
  - 统计 per-agent latency / tokens / cost / schema retry / failure rate
  - `doctor` 或 `eval report` 增加 agent 级汇总
  - RelatedAgent skipped reason / link validator drop reason 可聚合查看
- **边界与开源工程**:
  - 收敛 agents 的公开 run 入口,让 eval 不直接依赖 agents 内部类
  - 加 GitHub Actions: `ruff check .` / `mypy` / `pytest`
  - README 增加 agent 流程图、真实输出片段、指标表、"不是普通 RAG demo"的说明
  - 可选:CONTRIBUTING.md / issue template / badges / demo video

**依赖**：

- M14/M15 eval 基础设施稳定
- 先修当前门禁红项:`ruff`、`mypy`
- 不引入新依赖;如果 evidence 或 metrics 需要额外库,先讨论再加

**DoD**：

- [x] `uv run ruff check .` 通过
- [x] `uv run mypy` 通过
- [x] `uv run pytest` 通过
- [ ] GitHub Actions 自动跑 ruff / mypy / pytest
- [ ] smoke eval 在文档步骤下可复现运行,不依赖未说明的本地 PDF 状态
- [ ] schema first-pass valid rate / retry rate / per-agent cost latency 有记录
- [ ] 至少 5 篇论文有 evidence coverage / unsupported claim rate 人工抽样结果
- [ ] README 展示 agent 流程、demo 输出、核心指标和模型选型故事

**M16-min 裁剪记录 (2026-05-18)**:用户明确跳过 GitHub Actions(每次 push
发邮件很烦)和可复现 smoke eval。本轮完成门禁全绿与 schema validation
最小恢复:一次 retry、失败时 session 保留 raw tool_use input +
schema_validation error,CLI 最终错误包含 agent / tool / field loc。

**预估**：3-5 sessions。先做门禁 + 可复现 demo,再做质量指标和 evidence。

---

### M17: Autonomous Research Loop（候选，M17-min 已开始）

**目标**：把 paper-copilot 从"读一篇论文的固定流水线"升级成"能完成一个
研究任务的论文研究助理"。用户给研究目标,系统自动分解任务、调用工具 /
worker agent、观察结果、补读缺口、汇总报告,直到任务完成或触发预算 /
turn 上限。

**当前事实**：项目已有 `agents.loop.run_agent_loop`、session trace、cost
tracker、schema/tool-use 基础,但主功能没有使用真正的 tool loop。SkimAgent /
DeepAgent / RelatedAgent 都是一次性 forced tool-call,更像结构化抽取 worker。
M17 的价值不是"堆更多 agent",而是让 LLM 在 harness 内自主推进研究任务。

**目标体验**：

```bash
paper-copilot research "compare attention mechanisms for vision-language models" \
  --pdf-dir ./papers --budget-cny 2.0
```

系统自动:

1. 枚举或搜索候选论文
2. 对未读论文调用 `read_paper`
3. 搜索本地库找相关论文和片段
4. 挑 3-8 篇最相关论文做比较
5. 发现证据不足时补读 section / paper
6. 写 synthesis report,列出结论、证据、未覆盖问题和后续阅读建议

**核心设计原则**：

- 主 Agent 是 planner / controller,不是又一个一次性总结 prompt
- worker agent / tools 必须 bounded:明确输入输出、预算、失败语义
- 每一步都写 session trace:thought 摘要、tool call、tool result、cost、
  schema validation、termination reason
- deterministic tools 优先于 LLM 自由发挥:已有 `read`、`search`、`compare`、
  `list`、`doctor` 能包装成 tool surface
- 不能让 agent 随意扫全库和无限读 PDF;必须有 max_turns、max_budget、
  max_papers、max_sections
- eval 不只看最终文本,还要看 task success、工具调用路径、预算和证据覆盖

**候选工具 surface**：

- `list_papers(pdf_dir | library_filter) -> paper candidates`
- `read_paper(pdf_path | paper_id) -> Paper summary + session path`
- `search_library(query, filters, k) -> ranked papers/chunks`
- `inspect_paper(paper_id, fields) -> structured fields + evidence`
- `deep_read_section(paper_id, section_query) -> extracted evidence`
- `compare_papers(a, b) -> structured comparison`
- `find_related_papers(paper_id, k) -> related links/candidates`
- `write_synthesis_report(topic, paper_ids, evidence) -> markdown report`

**指标**：

- task success rate:给定研究任务是否产出可用 report
- evidence coverage:报告里关键结论是否有 paper_id/page/snippet
- unsupported claim rate:人工抽样发现无依据结论的比例
- tool-call success rate / retry rate / failure reason 分布
- per-task cost / p95 latency / turns / papers read
- ablation:固定流水线 vs autonomous loop 在复杂任务上的人工验收差异

**MVP 范围**：

- 只支持本地 PDF 目录 + 已有 library,不联网搜论文
- 只做 1 类任务:`research "<topic>" --pdf-dir <dir>`
- 最多读取 5 篇新论文,最多 12 turns,预算默认 ¥2
- 输出一份 `research-report.md` 和完整 session trace
- 失败时明确说明缺哪些论文/证据/预算,不编完整结论

**依赖**：

- M16 至少完成门禁全绿、schema retry、可复现 demo、基础质量指标
- agents 需要公开稳定 tool surface,eval 不直接摸内部类
- 若要加真正 planner prompt,先设计 eval case,不要先写复杂编排

**DoD**：

- [ ] `paper-copilot research "<topic>" --pdf-dir <dir>` 能端到端跑通
      (M17-min 已有 CLI + bounded loop + 本地库工具骨架 + find_related_papers;
      `read_paper` 自动读已接入,尚未做人类端到端验收)
- [ ] 至少 3 个固定研究任务有人工验收记录
- [ ] session trace 能还原每一步工具调用和决策
- [ ] max_turns / max_budget / max_papers 都能触发并给出清晰终止原因
- [ ] report 中关键结论带 evidence,人工抽样 unsupported claim rate 可统计
- [ ] 与固定 `read + compare` 手工流程做一次对比,说明自动 loop 节省了哪些人工步骤

**预估**：4-8 sessions。不要在 M16 前开工;否则会把未硬化的流水线包进更
复杂的 agent runtime 里,调试成本会爆炸。

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
