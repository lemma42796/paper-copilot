# STATUS

> 当前任务的跨会话接力快照。每次更新覆盖旧内容，不追加历史流水；详细设计与实验结果
> 保存在各自产物中。

更新于 2026-08-07。

## 新会话从这里继续

`paper search` 检索归一化修复已完成并通过逻辑验证（未请求不跑仓库门禁）。
公式 OCR 缓存填满测试暴露两个新问题，已记入 TASKS.md：**harness 缺少相似重复
调用防护**、**Skill 指令不够准确导致模型绕开公式识别管线**。下一步按 TASKS.md
顺序做这两项。

## 当前已实现与已验证

### paper search NFKC 归一化修复（2026-08-07 完成）

- `agents/library_exec_tool.py` 新增 `_search_needle()` / `_line_matches()`：
  查询与文本两侧做 `casefold` + NFKC 归一化；两级匹配——空白折叠优先、
  完全去空白兜底（覆盖两端对齐拆字间距，如 `M a r k e t`）。
- 解决全角证据（`ｍＡＰ`/`Ｒａｎｋ－１`）搜不到的问题（Q4 下降诊断的直接
  原因一）；查询归一化后为空时抛 `KnowledgeError`。
- 7 个用例直接调用验证通过：全角命中、字间距命中、无关内容不命中、空查询
  报错。

### 公式 OCR 缓存填满测试（2026-08-06/07，未完成，被人工终止）

- 全库扫描（真实缓存管线，`tmp/scan_garble_slots.py`）：31 篇顶层英文论文中
  仅 5 篇有乱码槽位——AlexNet 2 槽、TokenMatcher 5、Bag of tricks 7、
  ResNet 10、Rewarded Semi-Supervised 3；其余（含最短的 NIPS 超图论文）
  文本层干净。
- 第一次运行（NIPS 超图，8 页）：0 槽位 0 替换字符，模型正确判断无需 OCR，
  正常交付报告，成本 ¥0.054——但测试目标未达成（选篇未先扫乱码）。
- 第二次运行（AlexNet，9 页 2 槽）：`recognize_formula` 已正常暴露
  （world state 工具列表确认），但模型一次未调用，改用 50+ 轮相似但不同的
  shell/python 命令手工解析 PDF 字节；`loop.py` 相同输入重复防护未触发；
  人工终止。产物在 `tmp/formula-fill-check/run-20260806T155312Z/`。
- 历史评估运行复核：14 篇 revision `formula_ocr_records` 全为 0，是
  “从未调用”而非“调用后丢失”，管线无异常；该诊断疑虑闭环。

## 已知保留与决策点

- `cache_slot` 标记保持模型可见（OCR 定位必需），未改动。
- 测试脚本 `tmp/run_formula_fill_check.py`、`tmp/scan_garble_slots.py` 与
  运行产物留在 `tmp/`（不提交），供后续 Skill 优化后复跑。

## 下一步

1. Agent 循环相似重复调用防护（TASKS.md）。
2. 优化 research Skill：精简且指令准确，然后重跑 AlexNet 公式讲解验证
   recognize/accept 填满槽位。

## 验证边界与剩余风险

- 检索修复只做了函数级用例验证；未运行 pytest/Ruff/mypy（未请求），
  未做客户端复跑。
- 去空白兜底匹配接受跨词边界的误命中风险（诊断报告已确认该取舍）。

## 工作树事实

- 分支 `main`；本次提交推送包含：
  - `src/paper_copilot/agents/library_exec_tool.py`：`paper search` NFKC
    归一化与两级空白匹配；
  - `TASKS.md`：新增两项未完成任务；
  - `STATUS.md`：本文档。

关键入口：

- `src/paper_copilot/agents/library_exec_tool.py`
- `src/paper_copilot/agents/loop.py`（重复调用防护，待增强）
- `src/paper_copilot/agents/skills/research-papers/SKILL.md`（待精简）
- `src/paper_copilot/shared/pdf_cache.py`
- `src/paper_copilot/agents/formula_ocr_tool.py`
