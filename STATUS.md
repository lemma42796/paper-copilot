# STATUS

> 当前任务的跨会话接力快照。每次更新覆盖旧内容，不追加历史流水；详细设计与实验结果
> 保存在各自产物中。

更新于 2026-08-06。

## 新会话从这里继续

“无论文数据库 + 按需 TXT 缓存 + 可选本地公式 OCR”的缓存一致性（新增/查询/替换/删除
PDF）已在客户端真机验证全部通过，删除逻辑现在会连外层空目录一起清掉。缓存已从模型
可见面隐藏：模型只使用 `paper read/search`，哈希核对、删除与重建全部由 agent 工具层
自动完成（SKILL v22）。剩余验证项：用新命令面在客户端重跑一遍、`recognize`/`accept`
回填与跨会话命中、未请求论文不生成缓存、主客户端静态依赖与网络门控；`docs/design/`
中仍引用旧 `paper-cache` 命令名，尚未同步。

## 当前已实现与已验证

### 按需缓存一致性（2026-08-06，客户端真机验证完成）

- 同一会话四轮（增/查/改/删）8 项断言全 PASS，模型为 deepseek-v4-flash：
  - 增：新会话预检清单包含新增 PDF，清单键=PDF SHA-256；首次 `page` 读取按需生成
    A 键缓存（revision 为新生成）。
  - 查：第二轮再读同一页，命中同一 revision，revision 不变，缓存仍在。
  - 改：同名不同内容 PDF（何子玲→张振宇）替换后，旧键 A 缓存被删、新键 B 缓存生成。
  - 删：PDF 删除后读取报 “PDF no longer exists in the library”，B 键缓存被删。
- 磁盘复核：运行期间只有 A/B 两个键目录变化，测试 PDF 已清理；删除后键内容清空。
- 验证脚本 `/private/tmp/paper_copilot_cache_verify.py`（仓库外）：修过三个问题——
  LLM 端点瞬时断连（加重试）、`max_papers=14` 导致清单只收录 14/50 篇（改 60）、
  脚本检查路径把 `paper-cache` 重复拼接（修正）。
- 四轮模型成本合计约 ¥0.038。

### 缓存表面去暴露（2026-08-06，已完成）

- `library_exec` 模型可见命令改为 `paper read <pdf> <page>` / `paper search <pdf> <query>`；
  `paper-cache ensure/status/page/search` 不再路由。
- 错误文案去缓存化（删除后只报论文不存在，不再提 stale cache）；SKILL 升 v22。
- `PdfTextCache._delete_key` 删除 `<sha>/<fingerprint>` 后，外层 `<sha>/` 为空时一并
  `rmdir`（非空或并发写入时自动跳过）。
- 直接工具层验证通过：read/search 正常、参数错误明确、旧命令失效、缓存后台照常生成。
- 已知保留：公式 OCR `cache_slot` 标记仍模型可见（待单独决策）；工作区 `cache/` 目录
  仍在但不再写入工具描述。

### 公式 OCR 与 Helper（此前已完成）

- 公式定位逻辑改为几何裁剪（`_locate_numbered_formula`），单栏居中公式 OCR 乱码解决；
  `recognize` 真实 Helper 验证返回干净 LaTeX；`accept` 与跨会话命中尚未在客户端执行。
- Helper 构建（受限异常因果输出、pypdfium2 收集）、ad-hoc Release `formula-ocr-v1`
  发布、App 内安装闭环、超时 45→120 秒均完成；正式发布仍需 Developer ID 签名与公证。
- 工具暴露矩阵三场景此前 PASS；代码面变化后建议复跑。

## 下一步（按顺序）

1. （可选）用新的 `paper read/search` 命令面在客户端重跑缓存一致性验证。
2. 客户端完成真实乱码公式 `recognize`/`accept` 回填与跨会话命中。
3. 验证未请求论文不生成缓存；复核工具暴露矩阵。
4. 主客户端静态依赖检查（不含 Paddle 组件/权重）与 UI 网络门控验证。
5. 同步 `docs/design/` 中旧 `paper-cache` 文案；如需再把 `cache_slot` 语义化。

## 验证边界与剩余风险

- `accept` 回填、跨会话命中、Swift 构建、pytest/Ruff/mypy、静态依赖与网络门控尚未验证。
- 原 PDF 始终是公式权威证据；`accept` 只授权写派生 TXT，不等于公式数学正确。
- 开发构建使用 ad-hoc 签名，不等同于 Developer ID 签名、公证或发布验证。

## 工作树事实

- 当前分支 `main`；未提交改动（本次将提交并推送）：
  - `src/paper_copilot/shared/pdf_cache.py`（删除清空外层目录、按需缓存相关）
  - `src/paper_copilot/agents/library_exec_tool.py`（`paper read/search` 命令面）
  - `src/paper_copilot/agents/paper_copilot.py`、`chat/jobs.py`、`chat/runtime.py`
    （新会话预检与会话内复用清单）
  - `src/paper_copilot/agents/skills/research-papers/SKILL.md`（v22）
  - `src/paper_copilot/agents/paper_set_tool.py`、`mcp/server.py`（文案）
  - `src/paper_copilot/agents/formula_ocr_tool.py`（公式定位逻辑）
  - `TASKS.md` / `STATUS.md`（本文档）
- 验证脚本 `/private/tmp/paper_copilot_cache_verify.py` 在仓库外，未提交。
- 未运行 Swift 构建、pytest、Ruff 或 mypy。

关键入口：

- `src/paper_copilot/shared/pdf_cache.py`
- `src/paper_copilot/agents/library_exec_tool.py`
- `src/paper_copilot/agents/paper_copilot.py`
- `src/paper_copilot/agents/skills/research-papers/SKILL.md`
- `src/paper_copilot/agents/formula_ocr_tool.py`
- `apps/macos/PaperCopilot/Runtime/FormulaOCRManager.swift`
- `scripts/build_formula_ocr_component.sh`
