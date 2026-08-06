# STATUS

> 当前任务的跨会话接力快照。每次更新覆盖旧内容，不追加历史流水；详细设计与实验结果
> 保存在各自产物中。

更新于 2026-08-06。

## 新会话从这里继续

“无论文数据库 + 按需 TXT 缓存 + 可选本地公式 OCR”的仓库内验证项已全部完成：
新命令面（`paper read/search`）缓存一致性客户端重跑 ALL PASS，未请求论文不生成缓存
磁盘复核通过，工具暴露矩阵四场景复跑 PASS，主客户端静态依赖与网络门控代码级核查
PASS，`paper read/search` 模型可见输出去哈希化并四轮复跑 ALL PASS，
`docs/design/` 与 `ARCHITECTURE.md` 旧命令文案已同步。无剩余待办。

## 当前已实现与已验证

### 新命令面缓存一致性客户端重跑（2026-08-06 完成）

- 同一会话四轮（增/查/改/删）12 项断言 ALL PASS，模型 deepseek-v4-flash
  （api.deepseek.com），四轮成本合计约 ¥0.08；会话
  `conversation-new-surface-20260806181858`。
- 增：新会话清单包含测试 PDF，清单键=PDF SHA-256（A=`324a2128…`）；模型使用
  `paper read`，首次读取按需生成 A 键 revision（`fbb65467…`）。
- 查：第二轮重读命中同一 revision，revision 不变。
- 改：同名不同内容替换后旧键 A 删除、新键 B（`ed3a3bc7…`）生成。
- 删：删除后 `paper read` 报 “PDF no longer exists in the library”，B 键与外层
  空目录删除。
- 磁盘复核：全程只有 A/B 键变化，未请求论文零缓存生成；无旧键被清理。
- 表面断言：整场会话无 `paper-cache` 命令被路由；world state 不出现 paper-cache。
- 验证脚本 `/private/tmp/paper_copilot_new_surface_verify.py`（仓库外，未提交）。

### 模型可见输出去哈希化（2026-08-06 完成）

- `paper read` 模型可见输出仅含 `page`/`text`；`paper search` 仅含
  `query`/`matches`/`truncated`；不再出现 `cache_ref`、revision_id、paper_id 或
  artifact_sha256。
- 同一脚本四轮客户端重跑 ALL PASS（会话
  `conversation-new-surface-20260806183148`，成本约 ¥0.054），含脱敏断言：每轮
  read 输出字段集合严格等于 `{page, text}`。
- 实现：`library_exec_tool.py` 新增 `_model_visible_page()`，在返回前剥离缓存身份
  字段；search 输出原本就只有 query/matches/truncated。

### 工具暴露矩阵复跑（2026-08-06 PASS）

- 四场景注册表断言 + 客户端 world_state 交叉验证：
  - text-only + 库 + helper → `recognize_formula` 暴露，`inspect_page` 不暴露；
  - 无 helper → `recognize_formula` 不暴露；
  - 有图模型 → `inspect_page` 暴露，`recognize_formula` 不暴露；
  - 无库 → library 工具全部不暴露。

### 主客户端静态依赖与网络门控（2026-08-06 代码级核查）

- 主 `dependencies` 不含 Paddle；`paper_copilot.api.runtime` import 图不含
  paddle/paddleocr/torch；已构建 App（`dist/macos/PaperCopilot.app`）内无 Paddle/
  PP-FormulaNet 文件。Paddle 组件与权重仅存在于可选 helper 组件目录
  （`~/Library/Application Support/Paper Copilot/optional-components/formula-ocr/…`）
  与构建脚本产物中。
- Swift 网络调用点仅两处：`PaperCopilotAPI` → 本地 runtime（127.0.0.1）；
  `FormulaOCRManager.downloadAndInstall` → GitHub manifest/下载，仅由设置页
  “下载本地公式 OCR…”按钮触发。悬浮、选模型、启动路径无网络调用；运行时 world
  state `network=denied`，library sandbox 默认拒绝网络。

### 缓存表面去暴露与旧命令面一致性（此前已完成）

- `library_exec` 模型可见命令改为 `paper read/search`；`paper-cache …` 不再路由；
  SKILL v22；`_delete_key` 会清理空外层目录。旧命令面四轮验证 ALL PASS 已随
  `a97d700` 提交推送。

### 公式 OCR 与 Helper（此前已完成）

- 几何裁剪定位修复；客户端 recognize/accept 回填与跨会话命中已于 2026-08-05 验证
  （会话 `conversation-20260805T133620-7d4e2c06c7` 等，accept 发布 revision
  `dadd8d9d…`，后续会话直接命中 recognized 标记）。
- 注意：该修复 revision 在 08-06 缓存一致性清理时随 `324a2128…` 键删除（测试 PDF
  与真实论文同哈希），实时缓存中不再存在；机制已验证。
- Helper v1.0.0 已安装（`active.json` schema_version=2）。

## 已知保留与决策点

- `cache_slot` 标记保持模型可见（OCR 定位必需），未改动。

## 下一步

无剩余待办（仓库内验证与文档同步均已收口）。

## 验证边界与剩余风险

- 本次未运行 Swift 构建、pytest、Ruff 或 mypy（未请求）；网络门控为代码级核查，
  未做 GUI 级抓包复测。
- 原 PDF 始终是公式权威证据；`accept` 只授权写派生 TXT，不等于公式数学正确。

## 工作树事实

- 当前分支 `main`；本次提交推送包含：
  - `ARCHITECTURE.md` 与 `docs/design/` 4 个文件：旧 `paper-cache` 文案 →
    `paper read/search`；
  - `src/paper_copilot/agents/library_exec_tool.py`：`paper read` 模型可见输出剥离
    缓存身份字段（只返回 `page`/`text`）；
  - `STATUS.md` / `TASKS.md`：本文档。
- 验证脚本 `/private/tmp/paper_copilot_new_surface_verify.py` 在仓库外，未提交；
  旧脚本 `/private/tmp/paper_copilot_cache_verify.py` 已不存在（已清理）。

关键入口：

- `src/paper_copilot/shared/pdf_cache.py`
- `src/paper_copilot/agents/library_exec_tool.py`
- `src/paper_copilot/agents/paper_copilot.py`
- `src/paper_copilot/agents/skills/research-papers/SKILL.md`
- `src/paper_copilot/agents/formula_ocr_tool.py`
- `apps/macos/PaperCopilot/Runtime/FormulaOCRManager.swift`
- `scripts/build_formula_ocr_component.sh`
