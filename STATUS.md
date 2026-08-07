# STATUS

> 当前任务的跨会话接力快照。每次更新覆盖旧内容，不追加历史流水；详细设计与实验结果
> 保存在各自产物中。

更新于 2026-08-08。

## 新会话从这里继续

公式核实管线已收官并通过真机验证。最终形态是三级定位优先级（SKILL v27）：
① `cache_slot` 自动裁切（建库阶段预计算坐标，确定性最高）→ ②
`locate_page_text` 双锚点推导（槽位无 bbox 或无槽位时；错误消息负责引导降级）→
③ `equation_label` 编号公式。accept 支持 `refined_latex`：模型把 OCR 产物
清理完善后随 accept 一并发布，缓存正本存修订版、原始 OCR 经双哈希留痕。
真机全链路验证通过（AlexNet「解释所有公式」任务，会话
`conversation-20260807T170916-c13149685f`）：整轮 turn_completed，无 bbox 槽位
被工具错误消息顺畅引导到锚点路径，`refined_latex` 实战争取了裁宽混入的垃圾，
accept 自然发生并带 `refined=true` 落盘，教科书公式直接引用未浪费 OCR。
伞形任务「按需论文缓存与可选本地公式 OCR」收官，当前无活动任务。

## 本轮实现与验证（2026-08-08）

- `agents/formula_ocr_tool.py`：accept 新增可选 `refined_latex`（accept 专用，
  recognize 传入报错）；确定性校验（非空、禁 `[[` 标记序列、禁控制字符）；
  发布版 = 修订版优先，output/trace 记录 `refined` 与发布版哈希。
- `shared/pdf_cache.py`：`record_formula_ocr` 接受 `latex`/`ocr_latex` 双输入；
  修订时槽位标记附 `refined=true`；`FormulaOCRRecord` 新增 `refined` 与
  `ocr_latex_sha256`（均带默认值，旧 manifest 向后兼容，schema_version 不变）。
- `agents/locate_page_text_tool.py`：移除 `page_evidence` 登记——文本层搜索
  本就不应入视觉证据台账，修复 `PageEvidenceFact` 校验导致的真机整轮中止
  （事故会话 `conversation-20260807T140208-8d78aa7f80`）。
- `skills/research-papers/SKILL.md` v27：公式管线从规则条文压成两段自然叙述
  （信号与判断 / 操作流程），三级优先级与"选最近锚点匹配"融入叙述；
  去除 manifest 与 `library_exec` 的重复表述。
- `agents/research_skill.py`：description 改从 SKILL.md frontmatter 解析
  （单一事实源），消除目录/系统提示词与文档漂移。
- 验证：`load_research_skill()` 实跑解析 v27 通过；真机会话
  `conversation-20260807T170916-c13149685f` 八个检查点全过
  （报告产物见会话目录 `research-report.md`）。按约定未跑测试套件。

## 已知局限与待决策点

- C0 残骸型槽位无 bbox（如 SGD 第 6 页）：v5 建库聚类未覆盖，现由锚点路径
  兜底；根因未排查，是否修待定。
- 槽位 `page-0006-formula-0002` 未回填：模型判断符号含义可从正文获得，
  未重试锚点；低优先级，不为此加规则。
- 完全丢弃型损坏（码位无残骸）仍无文本层信号；视觉检测属检测层缺口，未立项。
- 存量测试失败 2 个（干净 main 即失败，与本轮无关）：
  `tests/agents/test_tool_security.py::test_approved_library_mutation_executes_once`、
  `tests/chat/test_runtime.py::test_handle_chat_request_allows_direct_answer_without_index`。
- 测试脚本与运行产物留在 `tmp/`（不提交）。

## 下一步

无活动任务。候选事项待用户决定：无 bbox 根因排查、视觉检测立项、
全量门禁（ruff/mypy/pytest）执行。

## 工作树事实

- 分支 `main`；`f987ce2` 含锚点定位/C0 检测/SKILL v25，`569cce8` 含跨行单槽位。
- 本轮提交含：refined_latex 双版本落盘、SKILL v27、evidence 移除、
  description 单一事实源、TASKS/STATUS 更新。涉及文件：
  - `src/paper_copilot/agents/formula_ocr_tool.py`；
  - `src/paper_copilot/agents/locate_page_text_tool.py`；
  - `src/paper_copilot/agents/research_skill.py`；
  - `src/paper_copilot/agents/skills/research-papers/SKILL.md`；
  - `src/paper_copilot/shared/pdf_cache.py`；
  - `TASKS.md` / `STATUS.md`。

关键入口：

- `src/paper_copilot/agents/formula_ocr_tool.py`（`_validate_refined_latex` /
  accept 发布链路）
- `src/paper_copilot/shared/pdf_cache.py`（`_record_formula_ocr_locked` /
  `FormulaOCRRecord`）
- 证据会话 `~/.paper-copilot/papers/conversation-20260807T170916-c13149685f/`
