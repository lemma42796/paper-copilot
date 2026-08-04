# STATUS

> 当前任务的跨会话接力快照。每次更新覆盖旧内容，不追加历史流水；详细设计与实验结果
> 保存在各自产物中。

更新于 2026-08-05。

## 新会话从这里继续

“无论文数据库 + 按需 TXT 缓存 + 可选本地公式 OCR”的 Helper 构建、真实公式推理、ad-hoc
Release 发布和 App 内安装闭环已经跑通。当前重点转为剩余验证项：真实 `cache_slot`
乱码公式的 `recognize`/`accept` 回填与跨会话命中、工具暴露矩阵、按需缓存一致性、
主客户端静态依赖与网络门控；最后完成 Developer ID 签名、公证和正式发布复核。

工具超时已从 45 秒调整为 120 秒（`src/paper_copilot/agents/formula_ocr_tool.py`），安装版
Helper 冷启动实测 74 秒、热启动 4.25 秒。正式对外发布仍缺 Developer ID 证书与公证，
当前 ad-hoc 发布仅用于测试下载安装链路。

## 当前已实现与已验证

### Helper 构建（已完成）

- 2026-08-05 重建成功，产物已包含受限异常因果输出（最多四层、每层 400 字符）。用空
  模型目录触发失败时返回具体原因
  `No such file or directory: .../inference.yml`，不再是旧的通用 `DependencyError`。
- 构建脚本新增 `--collect-all pypdfium2` 与 `--collect-all pypdfium2_raw`，本次构建已
  实际使用且 hook 正常处理。
- 产物：runtime zip 327,224,225 B，SHA-256
  `5a50dae71cb288a00ece732fe64808decd363937a4380a89e4bcc87f1dc0e95f`；模型 zip
  200,176,509 B，SHA-256
  `38414c5ed744e556730804de37bdcbe813cdf4e2eaf32b3a7a4dc0ea6c0630a3`；schema v2 manifest。
- zip 完整性、`codesign --verify --deep --strict`、`libgomp.1.dylib` /
  `libgcc_s.1.1.dylib` / `pandas` 入口均通过。
- PyInstaller 仍有 transformers/huggingface_hub 兼容警告、GCC 运行库分析期缺失（构建后
  注入）与 `libblas`/`liblapack` SDK 版本警告；真实推理已成功，暂无功能性影响。

### GitHub Release（ad-hoc 测试发布，已完成）

- Release `formula-ocr-v1` 已发布，包含 runtime、模型、manifest 三个资产，大小与本地
  完全一致；远程 manifest 与本地逐字一致；三个下载 URL 均返回 200。
- 资产 URL 与 `FormulaOCRManager.swift` 中固定的 manifest URL 完全匹配。
- 注意：这是 ad-hoc 签名测试版，浏览器手动下载会受 Gatekeeper quarantine 影响；
  正式对外发布仍需 Developer ID 签名和公证。

### App 内安装闭环（已验证）

- 设置页点击下载后完整走通：获取 manifest → 下载 runtime zip（327 MB）→ `ditto` 解压 →
  全树 SHA-256 → 模型从本机 `~/.paddlex/official_models/PP-FormulaNet_plus-S` 复用（未下载
  模型 zip）→ 组装 `versions/1.0.0` → 签名校验 → 原子写入 schema v2 `active.json`。
- `downloads/` 只保留 runtime zip；模型复用成立依据是本机 PaddleX 目录树哈希与
  `manifest.model.tree_sha256` 一致。
- 安装版 Helper 真实推理成功：`c_{i}=\sum_{j=1}^{T_{x}}\alpha_{i j}h_{j}` 与 softmax
  对齐公式均正确识别，多次运行结果确定性一致。
- 计时：构建目录 Helper 冷 9.19 s / 热 4.23 s；安装版 Helper 首次冷启动 74.2 s / 热
  4.25 s。因此 `_HELPER_TIMEOUT_SECONDS` 45.0 → 120.0（`recognize`/`accept` 共用）。
- UI 在下载+校验期间只有 `ProgressView` 转圈，没有阶段/进度提示；安装完成后显示
  “已安装 · 1.0.0”。进度提示可作为后续体验改进。

### 已知观察

- 裁剪包含公式编号时，OCR 尾部会读出 `(text5)` 或 `\eq(6)` 噪声；`accept` 前可能需要
  裁掉编号或人工修正尾部。
- 沙箱环境运行 Helper 时有 `sysctl ... Operation not permitted` 与 ccache 提示，均非致命。
- 安装版 Helper 首次冷启动受 I/O 影响可达 74 s；120 s 超时应覆盖，但 App 实际调用中的
  首次耗时尚未验证。

## 下一步（按顺序验证）

1. 选取带真实 `cache_slot` 的乱码公式执行 `recognize`（确认缓存 revision 不变）；人工
   检查候选后执行 `accept`（只替换目标 slot、保留其他正文和页边界、旧 revision 被清理），
   并验证跨会话命中。
2. 验证工具暴露矩阵：纯文本模型 + 已安装 Helper 可见；纯文本 + 未安装不可见；图像模型
   不可见且继续暴露 `inspect_page`。
3. 验证按需缓存一致性：启动/预检只生成 inventory manifest；仅对选中的论文执行
   `paper-cache ensure`；新增、删除、查询和替换 PDF 后缓存与哈希保持一致；失败扫描不清理。
4. 主客户端静态依赖检查（不含 Paddle 组件/权重）与 UI 网络门控验证（未点击下载无网络行为）。
5. 生产发布：Developer ID 签名 + 公证；复核固定 GitHub Release 资产与 manifest 哈希；
   正式发布后重跑一次安装闭环。

## 验证边界与剩余风险

- 尚未完成：`recognize`/`accept` 真实回填、跨会话命中、暴露矩阵、缓存一致性、Swift
  构建、Python 测试、静态依赖与网络门控验证。
- 120 秒超时尚未在 App 实际调用中验证；安装版冷启动 74 s 是本机首次 I/O 数据，其他
  机器可能不同。
- 原 PDF 始终是公式权威证据；`accept` 只授权写派生 TXT，不等于公式数学正确。
- 开发构建使用 ad-hoc 签名，不等同于 Developer ID 签名、公证或发布验证。
- 未请求或未接受任何付费模型/API 调用；测试裁剪图只用于推理验证，未持久化为论文证据。

## 工作树事实

- 当前分支为 `main`。本状态更新提交包含：`TASKS.md`、`STATUS.md`、
  `src/paper_copilot/agents/formula_ocr_tool.py`（超时 45 → 120）、
  `scripts/build_formula_ocr_component.sh`（pypdfium2 收集，本次构建已使用）。
- 构建产物位于 Git 忽略目录 `build/`，未提交。测试裁剪图在 `/tmp/formula-test/`。
- 尚未运行 Swift 构建、pytest、Ruff 或 mypy。

关键入口：

- `src/paper_copilot/shared/pdf_cache.py`
- `src/paper_copilot/agents/paper_copilot.py`
- `src/paper_copilot/agents/library_exec_tool.py`
- `src/paper_copilot/agents/formula_ocr_tool.py`
- `src/paper_copilot/formula_ocr_helper.py`
- `apps/macos/PaperCopilot/Runtime/FormulaOCRManager.swift`
- `apps/macos/PaperCopilot/Views/SettingsView.swift`
- `scripts/build_formula_ocr_component.sh`
- `docs/design/formula_ocr_optional_component.md`
