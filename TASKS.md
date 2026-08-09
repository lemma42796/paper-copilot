# TASKS

> 本文件保存所有未完成任务，可以同时存在多个任务；已完成任务删除，未完成任务保留或
> 更新。实验记录不得写入这里；历史实验入口统一见
> [实验索引](docs/design/experiment_index.md)。工程规则见 [AGENTS.md](AGENTS.md)，
> 当前接力状态见 [STATUS.md](STATUS.md)，当前架构见
> [ARCHITECTURE.md](ARCHITECTURE.md)。

更新于 2026-08-09。

## 未完成任务

### 1. 完成 PDF 字体乱码恢复产品级验证

状态：`source_cache_validation_all_three_paths_complete_packaging_pending`，Cambria Math、
Symbol MT 和 ReaderEx 三条源码缓存路径均已用代表性真实学位论文验证；打包 App 仍未
验证。

已完成：

- 对 65 页学位论文《基于低秩融合与动态增强的多模态行人重识别研究》执行隔离缓存重建；
- 命中 1 个 Cambria Math 字体并重建 7,613 条 Unicode 映射，原始文本中的 851 个
  `U+FFFD` 在修复后降为 0；
- 变化只出现在物理页 21、22、24，已与原 PDF 逐页核对数学字母、希腊字母和公式结构；
- 首次 `PdfTextCache.ensure` 生成 65 页缓存，第二次命中同一 revision，临时修复 PDF 已清理。
- 从其余 13 篇学位论文做字体资格预筛，只对 6 篇代表样本重建隔离缓存；6 篇均首次生成、
  第二次命中同一 revision，原 PDF 和 App 当前缓存未修改；
- 项莘泽论文命中 1 个 Cambria Math 字体，`U+FFFD` 从 317 降为 37，剩余 37 个集中在
  带箭头/横线的向量符号，缓存保留 13 个公式槽；
- 张耀斌论文命中 1 个 Cambria Math 字体，`U+FFFD` 从 1,590 降为 0；残留 26 个
  `U+F06C` 经原页核对是正文项目符号，却被现有乱码检测生成 26 个公式槽；
- 修复了 `DescendantFonts` 指向间接单元素数组时被误当成无 `CIDToGIDMap` 的解析缺陷；
  彭思懿与闵青青的实际 Symbol MT 后代字体均明确声明 `/Identity`；
- 彭思懿 Symbol MT 的私用区字符从 337 降为 33，公式槽从 90 降为 7；闵青青从 104
  降为 0，公式槽从 17 降为 10；未定义 Symbol 编码和拼装件转成 `U+FFFD`，没有猜测；
- 张振宇的 `B3+SimSun` 确实缺少 `CIDToGIDMap`；4 个私用区映射经页面唯一 GID、空轮廓
  和跨字体独占三重验证后，从原始提取文本精确删除 8,779 个控制字符，公式槽从 1,947
  降为 0；删除结果逐字等于原文本仅移除这 4 个码点，正文顺序不变；
- 张兴帅论文不命中修复规则，修复前后文本哈希完全一致，验证了不修改路径；其 31 个
  私用区字符是分段公式括号拼装件，现有缓存保留 3 个公式槽。
- 提取器 fingerprint 已升级到 `embedded-cmap-math-symbol-readerex-v3`；5 篇最终代表样本
  均首次生成、第二次命中同一 revision，原 PDF 未修改且没有遗留临时修复 PDF；
- 定向测试 `tests/shared/test_pdf_font_repair.py` 共 8 项通过，覆盖完整 CMap 展开、间接
  后代数组、显式 CID→GID 映射、观测 GID 门槛、空轮廓删除和正文顺序保持。

尚未完成：

- 找到真实使用显式 `CIDToGIDMap` 流的代表 PDF 做集成验证；当前流解析与 CID→GID 应用
  已有定向测试，但本轮真实样本覆盖的是间接数组中的 `/Identity` 与缺失映射的 ReaderEx；
- 构建并运行 macOS App，确认 PyInstaller 打包 fontTools 且产品缓存路径结果一致。

### 2. 验证主动坐标探索式公式 OCR

状态：`real_recognize_complete_accept_validation_pending`。旧三级定位代码已经删除，新协议
和独立 Skill 已实现；新 fingerprint 缓存、逐字符坐标查询、模型主动选框和 Plus-M 真实
recognize 长链路已经用三篇代表论文验证，写回与失败恢复仍待验证。

已完成：

- 删除缓存完整 bbox 自动裁剪、双正文锚点推框和 `equation_label` 自动裁剪；
- 新增 `query_page_geometry`，模型可搜索编号/正文并在限定区域读取行与逐字符坐标；
- 缓存只对损坏且无中英正文的连续行预埋首尾损坏字符弱提示并建立独立
  `repair_span_id`；混合正文行两者均不生成，避免整行误替换；
- `recognize_formula` 只接受模型明确给出的 region，并用稳定 `formula_ref` 归并同一公式；
- 同一任务同一公式最多三次 recognize，次数写入 session application event，accept 不计；
- 乱码公式通过 `repair_span_id` 整段替换，疑似静默漏符号的非乱码公式通过唯一完整
  `replacement_text` 冻结；accept 只写显示 LaTeX，不做单字符补丁；
- `research-papers` Skill 已删除 OCR 流程，新增独立 `formula-ocr` Skill 负责触发门槛、
  编号/无编号/非乱码定位、重裁剪和 LaTeX 发布；未加载该 Skill 时 Runtime 拒绝坐标与
  OCR 工具调用；
- 已在 `docs/design/formula_ocr_validation_prompt.md` 保存后续验证提示词，覆盖有编号乱码
  公式、无编号行内公式和疑似静默丢结构的分段公式；提示词不向执行模型泄露评测目的、
  预期页码或正确结构，首轮只 recognize、不 accept，并要求报告每次 region、候选与哈希。
- 已用新 fingerprint 缓存执行真实任务 `job-20260809T092725-b68b814a53`：模型通过
  `query_page_geometry` 定位物理页 28、39、46；无编号 Rank-3 内联式直接使用字符几何，
  没有不必要地调用 OCR；
- 公式 (2-9) 与 (4.10) 均由模型明确给出 region，并在第一次 recognize 中恢复完整数学
  结构；分别用时 8.7 秒和 3.126 秒，模型均为 `PP-FormulaNet_plus-M`，没有重裁剪；
- 首次运行暴露并修复两个真实协议边界：公式 OCR tool schema 2 不能直接充当
  `PageEvidence` schema 版本；PyMuPDF 可能返回孤立 UTF-16 surrogate，现已在几何提取
  边界替换为 `U+FFFD`，保证工具结果可序列化；
- 已在 [主动公式定位案例](docs/stories/active_formula_localization.md) 保存两组缓存文本、
  实际模型裁图、原始 OCR LaTeX、可读渲染、region、candidate 与渲染哈希；两张裁图文件
  SHA-256 与 trace 中 `render_sha256` 完全一致。

尚未完成：

- 未运行 Python 测试、Ruff 或 mypy；
- 未核对旧 v2 accepted OCR revision 在 v3 中不自动迁移时的产品提示和重新识别体验；
- 未验证同一公式三次重裁剪后的次数拒绝、Helper 失败计数和重试恢复；
- 本次按提示只 recognize、未 accept：尚未验证 (2-9) 的 `repair_span_id` 整段写回和缓存
  回读；(4.10) 本次没有冻结唯一 `replacement_text`，不能直接安全写回，仍需重新识别并
  冻结完整替换目标后验证非乱码整段替换。

### 3. 构建并验证 Plus-M Formula OCR 可选组件

状态：`local_adhoc_install_and_real_ocr_complete_release_validation_pending`。

生产源码默认模型已从 `PP-FormulaNet_plus-S` 切换为
`PP-FormulaNet_plus-M`。Runtime 已改为首次请求按需启动 Helper、串行复用同一已加载模型，
连续一小时无请求后由 Helper 退出释放内存；旧版单次调用 Helper 保留兼容降级。

已完成：

- 使用本地 Plus-M 权重构建 `1.1.0` Runtime 与模型组件归档及 schema-v2 manifest；ARM64
  Helper 已 ad-hoc 签名，并通过 `codesign --verify --deep --strict`；
- 已安装到 macOS 可选组件目录，`active.json` 当前明确指向
  `versions/1.1.0/FormulaOCRHelper/FormulaOCRHelper`；旧 `1.0.0` 只作为本机回滚版本保留；
- 同一真实任务连续调用两次 Plus-M Helper，公式 (2-9) 与 (4.10) 均首次识别成功，证明
  当前本机安装与主动 region OCR 主链路可用；
- 当前没有 Developer ID，不把 Developer ID 签名或 Apple 公证列为本地验收前提；正式
  对外分发如需绕过 Gatekeeper，必须另行设计可承担的签名或用户自构建方案。

尚未完成：

- 未把 `1.1.0` manifest 与归档发布到公开下载端；
- 未专项验证 Helper 超时、崩溃重启和一小时空闲释放；本次两次连续真实调用只覆盖正常
  启动、复用与识别路径；
- 尚未决定何时删除旧 Plus-S 兼容代码；本机旧 `1.0.0` 暂时保留为可恢复版本。

### 4. 渲染报告中的 LaTeX 数学公式

状态：`build_complete_visual_validation_pending`。用户已批准新增原生 SwiftMath；工程依赖
和报告数学排版源码已经实现，Debug/Release arm64 构建通过，尚未在 App 中视觉验证。

已实现：

- Swift Package 依赖锁定 SwiftMath `1.7.3`，只在本地通过 AppKit/CoreText 排版，不使用
  WebView 或运行时联网；
- `MarkdownReportView` 将 `latex`、`tex`、`math` fenced code block，以及 `$$...$$`、
  `\[...\]` 和完整 `\begin{...}...\end{...}` 识别为展示公式；
- 段落、标题、列表、引用和表格单元格识别 `$...$` 与 `\(...\)` 行内公式，同时保留
  Markdown 链接、强调、代码和删除线样式；
- 公式图片按 LaTeX、字号和显示模式缓存；单个公式解析失败时降级显示原始 LaTeX，不让
  整份报告变空或失败；
- 为避免重新引入流式滚动卡顿，模型生成中的活动文本仍使用轻量纯文本，任务完成后的正式
  报告才启用数学排版。

待验证：SwiftMath 已由 Xcode 自动解析并生成 `Package.resolved`；修复
`CGFloat.greatestFiniteMagnitude` 类型歧义后，Debug/Release arm64 构建均通过。仍需在
完成报告中检查上述定界符、现有多行 `latex` 代码块、深浅色、长公式横向滚动、链接点击和
解析失败降级。
