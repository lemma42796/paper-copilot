# STATUS

> 当前任务的跨会话接力快照。每次更新覆盖旧内容，不追加历史流水；详细设计与实验结果
> 保存在各自产物中。

更新于 2026-08-07。

## 新会话从这里继续

公式槽位自动裁切（cache slot bbox）已完成并客户端真机验证：recognize 只传
`cache_slot` 即走 `region_source=cache_slot_bbox` 自动裁切，accept 一次成功，
LRN 槽位填入逐符号正确的 LaTeX，全程 1分02秒。Skill 已升 v24。上一轮的循环
相似重复防护与 Skill 优化也一并提交。剩余工作见 TASKS.md 伞形任务。

## 当前已实现与已验证

### 公式槽位 bbox 自动裁切（2026-08-07 完成）

根因：槽位标记无坐标，纯文本模型盲猜 region（实测三次全框错/擦边，公式真实
位置仅 2.3 个百分点窄带）；OCR 模型能力足够（干净裁切 100% 正确）。修法是
消除猜测环节：

- `shared/poppler.py`：新增 `page_word_boxes`（`pdftotext -bbox` 单页 XHTML）；
  `_EXTRACTION_PARAMETERS` 加 `slot_bbox_source=pdftotext-bbox-v2`，bump
  版本即自动失效旧缓存。
- `shared/pdf_cache.py`：建库时对含乱码行的页面算公式 bbox——词按 y 聚类成
  行、相邻乱码簇合并成公式组（gap ≤ 1.5×簇高）、吸收组跨度内垂直相邻的非乱码
  行（求和上下限/分式行，gap ≤ 8pt，`grown` 判断防死循环）、四边留 4pt；
  **按乱码行展开**（跨行公式的每个槽位都拿完整 box，与槽位数对位），写入
  start 标记 `bbox=x1,y1,x2,y2`；行数不对齐则整页丢弃坐标降级为无坐标槽位；
  新增 `slot_bbox()` 读回 API。
- `agents/formula_ocr_tool.py`：recognize 三级 region 解析——显式 region →
  槽位 bbox → equation_label；自适应渲染（基础 1800 全页测算裁切尺寸，不足
  700×180px 则升采样，上限 3600）；accept **容忍模型回传的重复定位字段**
  （candidate_id 是唯一信任锚点）；output/trace 记 `region_source`。
- `agents/inspect_page_tool.py`：`_render_page` 加 `scale_to`、
  `_png_dimensions` 加 `max_dimension` 参数。
- SKILL.md v24：recognize 第一步改为 slot+page+purpose，明确"do not guess
  a region"，region 仅在报告 stored crop 失效时显式传。

### 验证（客户端真机，2026-08-07）

- 三轮迭代各修一个 bug：① 跨行公式合并成 1 组导致与 2 个槽位对齐检查失败、
  坐标被整页丢弃 → 按乱码行展开；② accept 拒收模型回传 `cache_slot`/
  `purpose`/`region` 导致 6 次重试全失败 → 容忍重复字段；③ region 盲猜本身
  → 自动裁切。
- 最终运行（会话 `conversation-20260806T185806-ac8182997d`）：1分02秒，
  1 recognize + 1 accept 全成功，revision `eb05ef1c` 发布，槽位
  `page-0004-formula-0001` 替换为完整 LRN LaTeX（含求和上下限与 β 指数）。
- 测试：`tests/shared/test_pdf_cache_slots.py` 14 passed（bbox 算法/标记/
  对位/校验放宽）；ruff/mypy 无新增告警（存量告警未动）。

### Agent 循环相似重复调用防护（2026-08-07 完成，随本次一并提交）

- `agents/loop.py` 归一化签名守卫：数字抹成 `#`、空白折叠，但保留 JSON 值
  末尾裸整数（`paper read <pdf> 5` 页码）避免误杀批量分页；窗口默认 8，
  第 4 次出现起软打断、第 6 次升级 `ToolLoopError`。
- `tests/agents/test_loop.py` 14 passed。

## 已知保留与决策点

- 残留：同一公式跨多行产生多个槽位时，accept 只修复被识别的那个槽位，兄弟
  槽位仍留乱码标记（`page-0004-formula-0002`）；候选后续优化是 accept 时
  自动修复共享同一 bbox 的兄弟槽位。
- 自动裁切 OCR 尾部偶有丢失的风险已通过 4pt margin + 自适应升采样缓解，
  真机运行结果完整，暂不再调参。
- 测试脚本与运行产物留在 `tmp/`（不提交）。

## 下一步

1. TASKS.md 伞形任务的剩余约束按需推进；兄弟槽位联动修复待用户排期。
2. 全量门禁（ruff/mypy/pytest 全跑）本轮未执行（未请求）。

## 工作树事实

- 分支 `main`，本次提交包含：
  - `src/paper_copilot/shared/poppler.py`、`shared/pdf_cache.py`：bbox 采集与槽位标记；
  - `src/paper_copilot/agents/formula_ocr_tool.py`：三级 region 解析、自适应渲染、accept 放宽；
  - `src/paper_copilot/agents/inspect_page_tool.py`：渲染参数化；
  - `src/paper_copilot/agents/skills/research-papers/SKILL.md`：v24；
  - `src/paper_copilot/agents/loop.py`、`tests/agents/test_loop.py`：相似重复防护；
  - `tests/shared/test_pdf_cache_slots.py`：新测试；
  - `TASKS.md` / `STATUS.md`：文档更新。

关键入口：

- `src/paper_copilot/shared/pdf_cache.py`（`_collect_slot_bboxes` / `slot_bbox`）
- `src/paper_copilot/agents/formula_ocr_tool.py`（`_lookup_slot_bbox` / `_render_formula_crop`）
- 会话 `~/.paper-copilot/papers/conversation-20260806T185806-ac8182997d/`
