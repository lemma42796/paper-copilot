# STATUS

> 当前任务的跨会话接力快照。每次更新覆盖旧内容，不追加历史流水；详细设计与实验结果
> 保存在各自产物中。

更新于 2026-08-05。

## 新会话从这里继续

“无论文数据库 + 按需 TXT 缓存 + 可选本地公式 OCR”的 Helper 构建、真实公式推理、ad-hoc
Release 发布和 App 内安装闭环已经跑通。本次新增：公式定位逻辑
（`_locate_numbered_formula`）已从“按编号猜栏边界”改为“按文本层几何聚类”，修复了单栏
居中公式被切左半导致 OCR 乱码的问题；已用真实 Helper 直接调用验证 `recognize` 返回干净
LaTeX。剩余验证项：在客户端完成 `recognize`/`accept` 回填与跨会话命中、工具暴露矩阵、
按需缓存一致性、主客户端静态依赖与网络门控。生产发布（Developer ID 签名/公证）已按用户
要求移出任务范围。

## 当前已实现与已验证

### 公式定位逻辑修复（2026-08-05，已完成）

- 问题：旧逻辑取编号矩形后，若编号在右半页就假设公式在右栏，从页面中线（x≈51%）开始
  裁剪；中文单栏居中公式的左半被切掉，OCR 输出乱码（何子玲 p21 公式 2.1 实测）。
- 修复：`_locate_numbered_formula` 改为几何定位——以编号矩形为锚点，收集纵向中心在
  ±编号高度内的字符矩形，从编号向左做连续聚类得到公式主体；再用 PyMuPDF dict 视觉行做
  整体 x 包含性扩展（只有整行水平范围都在公式框内才并入，避免正文行内数学片段污染）；
  无文本字形时回退旧启发式。
- 验证：
  - 何子玲 p21 (2.1)：新 region (0.322, 0.693, 0.651, 0.735)，真实 Helper OCR 输出
    `\left\|f(A)-f(P)\right\|_{2}^{2}\leq\left\|f(A)-f(N)\right\|_{2}^{2},`（干净，非乱码）。
  - 何子玲 (2.2)、NIPS-2006 p3 (1)/p4 (3)（分式+下方含数学片段的正文行）、NMT p3 (2)
    （连乘上下限）、ResNet p3 双栏左栏公式 (1)：包围盒均正确；NIPS p4 正文行被正确排除。
  - recognize 不改缓存：revision 保持 `4d14795091824f5d8b9f911be2dffe13`，
    `formula_ocr_records=0`。
- 已知遗留：编号歧义（`search_for` 取最右匹配，`Eqn.(1)` 这类正文引用可能被误当编号）；
  超高多行公式/纯矢量公式可能仍不完整（回退旧逻辑）。

### Helper 构建（已完成）

- 2026-08-05 重建成功，产物已包含受限异常因果输出（最多四层、每层 400 字符）。
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
  正式对外发布仍需 Developer ID 签名和公证（已移出任务范围）。

### App 内安装闭环（已验证）

- 设置页点击下载后完整走通：获取 manifest → 下载 runtime zip（327 MB）→ `ditto` 解压 →
  全树 SHA-256 → 模型从本机 `~/.paddlex/official_models/PP-FormulaNet_plus-S` 复用（未下载
  模型 zip）→ 组装 `versions/1.0.0` → 签名校验 → 原子写入 schema v2 `active.json`。
- 安装版 Helper 真实推理成功：`c_{i}=\sum_{j=1}^{T_{x}}\alpha_{i j}h_{j}` 与 softmax
  对齐公式均正确识别，多次运行结果确定性一致。
- 计时：构建目录 Helper 冷 9.19 s / 热 4.23 s；安装版 Helper 首次冷启动 74.2 s / 热
  4.25 s。因此 `_HELPER_TIMEOUT_SECONDS` 45.0 → 120.0（`recognize`/`accept` 共用）。
- UI 在下载+校验期间只有 `ProgressView` 转圈，没有阶段/进度提示；安装完成后显示
  “已安装 · 1.0.0”。进度提示可作为后续体验改进。

### 已知观察

- 裁剪包含公式编号时，OCR 尾部会读出 `(text5)` 或 `\eq(6)` 噪声；`accept` 前可能需要
  裁掉编号或人工修正尾部。新几何裁剪已把编号排除在框外，该噪声应在多数场景消失。
- 沙箱环境运行 Helper 时有 `sysctl ... Operation not permitted` 与 ccache 提示，均非致命。
- 安装版 Helper 首次冷启动受 I/O 影响可达 74 s；120 s 超时应覆盖，但 App 实际调用中的
  首次耗时尚未验证。

## 下一步（按顺序验证）

1. 在客户端用简洁提示词跑何子玲 p21 公式 (2.1)：模型应自主 ensure → 找到 `cache_slot` →
   `recognize`（自动裁剪现在可用）→ 展示候选；人工对照 PDF 确认后 `accept`（只替换目标
   slot、保留其他正文和页边界、旧 revision 被清理），并验证跨会话命中。
2. 验证工具暴露矩阵：纯文本模型 + 已安装 Helper 可见；纯文本 + 未安装不可见；图像模型
   不可见且继续暴露 `inspect_page`。
3. 验证按需缓存一致性：启动/预检只生成 inventory manifest；仅对选中的论文执行
   `paper-cache ensure`；新增、删除、查询和替换 PDF 后缓存与哈希保持一致；失败扫描不清理。
4. 主客户端静态依赖检查（不含 Paddle 组件/权重）与 UI 网络门控验证（未点击下载无网络行为）。

## 验证边界与剩余风险

- 尚未完成：客户端内 `accept` 回填、跨会话命中、暴露矩阵、缓存一致性、Swift 构建、
  Python 测试、静态依赖与网络门控验证。
- `recognize` 已通过直接调用层面验证干净候选；App 内尚未重跑。
- 编号歧义与超高/纯矢量公式的定位局限见“公式定位逻辑修复”节。
- 120 秒超时尚未在 App 实际调用中验证；安装版冷启动 74 s 是本机首次 I/O 数据。
- 原 PDF 始终是公式权威证据；`accept` 只授权写派生 TXT，不等于公式数学正确。
- 开发构建使用 ad-hoc 签名，不等同于 Developer ID 签名、公证或发布验证。

## 工作树事实

- 当前分支为 `main`。本次改动包含：`TASKS.md`、`STATUS.md`（删除生产发布第 5 项）、
  `src/paper_copilot/agents/formula_ocr_tool.py`（公式定位逻辑，+142 行）。
- 构建产物位于 Git 忽略目录 `build/`，未提交。测试裁剪与 OCR 输出在 `/tmp`。
- 尚未运行 Swift 构建、pytest、Ruff 或 mypy。
- 本次已按用户要求 git add + commit + push。

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
