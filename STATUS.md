# STATUS

> 当前任务的跨会话接力快照。每次更新覆盖旧内容，不追加历史流水；详细设计与实验结果
> 保存在各自产物中。

更新于 2026-08-07。

## 新会话从这里继续

公式核实管线完成第二次大改：**锚点定位成为第一手段**（新工具
`locate_page_text`：模型引用公式上下正文行 → 文本层搜索返回归一化行框 →
推导裁切带 → `recognize_formula(region=...)`），`cache_slot` 自动裁切与
`equation_label` 降级为兜底，语义盲猜 region 除名。同时 C0 控制字符纳入
损坏检测并显式化为控制符图（SGD 型静默丢失现在有槽位、可见 `␏`），
fingerprint `slot_bbox_source=pdftotext-bbox-v5`。SKILL 升 v25。
跨行公式源头单槽位（v4 桥接规则）已先行提交（569cce8）。全部改动测试全绿、
lint 与基线一致，**待用户真机验证后确认收官**。

## 当前已实现与已验证

### 锚点定位 + C0 损坏检测（2026-08-07，待真机验证）

动因：SGD 公式的字形被映射成 C0 控制字符（ε→U+000F）或直接丢弃，旧检测
只认 FFFD/私用区，系统完全失明；模型一次 OCR 都没调用，凭记忆把公式补写
进报告（会话 `conversation-20260807T093040-0ec229e243` 实锤）。

- `agents/locate_page_text_tool.py`（新增，单一职责）：传 `paper_id`+`page`+
  layout.txt 引用短语，PyMuPDF `search_for` 返回每个匹配的归一化**短语框 +
  所在整行框**（整行框横跨栏宽）；纯文本层搜索，不渲染、不依赖图像模态与
  Poppler；复用 `inspect_page_tool` 库解析帮助函数。`paper_copilot.py`
  完成 schema/权限（read_library）/限额/异步分发注册。
- `shared/pdf_cache.py`：`_contains_extraction_garble` 覆盖三种损坏形态
  （FFFD/私用区、C0 控制字符（tab/换行除外）、DEL）；`_render_text_page`
  先在原文上算乱码 flags、再把控制字符转控制符图（U+000F→␏；
  `splitlines()` 会分行的 \v \f \x1c-\x1e 保持原样防行数错位）。
- `shared/poppler.py`：fingerprint v4→v5，旧缓存自动重建。
- SKILL v25：教科书级经典公式直接引用；其余公式第一手段走双锚点裁切带；
  兜底才是 cache_slot/equation_label；禁止语义猜 region。
- 测试：新增 `tests/agents/test_locate_page_text_tool.py`（6 例），
  `tests/shared/test_pdf_cache_slots.py` 增 C0 检测/显式化用例；
  tests/shared+agents+knowledge 114 passed（唯一失败为存量）；ruff 与基线
  逐行一致，mypy 仅与 `formula_ocr_tool` 同类的 pymupdf 存量告警模式。

### 跨行公式源头单槽位（v4，2026-08-07 已提交 569cce8）

兄弟槽位问题从源头消除：一个物理公式一个槽位；相邻乱码段夹 ≤2 行干净内容
（求和上下限）桥接为同一公式块；文本侧块数与 bbox 侧组数双闸门对齐；
本地复刻 LRN 页面结构验证单槽位带 bbox。真机验证并入锚点流程一起做。

### 更早完成（保留摘要）

- 公式槽位 bbox 自动裁切 v2：建库算乱码公式归一化 bbox 写入槽位标记，
  recognize 自动裁切 + 自适应升采样，真机 1分02秒 LRN 全对（会话
  `conversation-20260806T185806-ac8182997d`）。现降级为兜底路径。
- Agent 循环相似重复调用防护（归一化签名 + 软打断升级）。
- `paper read/search` 输出去哈希化、Helper 重建与 Formula OCR 组件安装闭环。

## 已知保留与决策点

- 完全丢弃型损坏（码位无残骸，如 SGD 的尖括号）仍无文本层信号；锚点定位
  可救（前提是模型起疑并调用工具），视觉检测属检测层缺口，未立项。
- 存量测试失败 2 个（干净 main 即失败，与本轮无关）：
  `tests/agents/test_tool_security.py::test_approved_library_mutation_executes_once`、
  `tests/chat/test_runtime.py::test_handle_chat_request_allows_direct_answer_without_index`。
- 测试脚本与运行产物留在 `tmp/`（不提交）。

## 下一步

1. 用户真机复跑：缓存因 v5 自动重建；核对点——SGD 行出现 `␏` 与槽位，
   模型走 `locate_page_text` 双锚点 + region 核实而非凭记忆补写；LRN 单槽位。
2. 验证通过后按 TASKS.md 伞形任务继续；视觉检测是否立项待用户定。
3. 全量门禁（ruff/mypy/pytest 全跑）本轮未执行（未请求）。

## 工作树事实

- 分支 `main`，v4 已提交（569cce8）；锚点/C0/SKILL 改动与本次文档更新
  随新一轮提交推送。涉及文件：
  - `src/paper_copilot/agents/locate_page_text_tool.py`（新增）；
  - `src/paper_copilot/agents/paper_copilot.py`：工具注册；
  - `src/paper_copilot/shared/pdf_cache.py`：C0 检测 + 控制符图渲染；
  - `src/paper_copilot/shared/poppler.py`：fingerprint v5；
  - `src/paper_copilot/agents/skills/research-papers/SKILL.md`：v25；
  - `tests/agents/test_locate_page_text_tool.py`（新增）、
    `tests/shared/test_pdf_cache_slots.py`；
  - `TASKS.md` / `STATUS.md`。

关键入口：

- `src/paper_copilot/agents/locate_page_text_tool.py`（`_search_page_text`）
- `src/paper_copilot/shared/pdf_cache.py`（`_is_extraction_garble_character` /
  `_visualize_control_characters`）
- 证据会话 `~/.paper-copilot/papers/conversation-20260807T093040-0ec229e243/`
