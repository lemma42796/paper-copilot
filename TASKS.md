# TASKS

> 本文件保存所有未完成任务，可以同时存在多个任务；已完成任务删除，未完成任务保留或
> 更新。实验记录不得写入这里；历史实验入口统一见
> [实验索引](docs/design/experiment_index.md)。工程规则见 [AGENTS.md](AGENTS.md)，
> 当前接力状态见 [STATUS.md](STATUS.md)，当前架构见
> [ARCHITECTURE.md](ARCHITECTURE.md)。

更新于 2026-08-16。

## 未完成任务

### 1. 完成 PDF 字体乱码恢复产品级验证

状态：`source_cache_validation_all_three_paths_complete_preview_published_product_path_pending`，
Cambria Math、Symbol MT 和 ReaderEx 三条源码缓存路径均已用代表性真实学位论文验证；
预览 DMG 已公开发布，但安装后产品缓存路径仍未验证。

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
- Apple Silicon App 开发预览
  [`v0.1.0-preview.1`](https://github.com/lemma42796/paper-copilot/releases/tag/v0.1.0-preview.1)
  已公开发布；Release 包含 70,614,645 字节的 `PaperCopilot-arm64.dmg` 和 SHA-256 文件，
  GitHub API 报告的 DMG 摘要与校验文件一致。

尚未完成：

- 找到真实使用显式 `CIDToGIDMap` 流的代表 PDF 做集成验证；当前流解析与 CID→GID 应用
  已有定向测试，但本轮真实样本覆盖的是间接数组中的 `/Identity` 与缺失映射的 ReaderEx；
- 从 GitHub Release 全新下载、安装并运行 macOS App，确认内嵌 Python Runtime 包含
  fontTools，且产品缓存路径结果与源码验证一致。

### 2. 验证主动坐标探索式公式 OCR

状态：`formula_overlay_warm_reuse_valid_cache_exactness_pending`。主动定位、真实 accept、
overlay 页面回读和新会话零 OCR 复用均已验证；原样 OCR 缓存仍有运算符拼写间距问题。

已完成：

- 删除缓存完整 bbox 自动裁剪、双正文锚点推框和 `equation_label` 自动裁剪；
- 新增 `query_page_geometry`，模型可搜索编号/正文并在限定区域读取行与逐字符坐标；
- 缓存只对损坏且无中英正文的连续行预埋首尾损坏字符弱提示；损坏块只显示通用乱码标记，
  不再向模型暴露替换跨度 ID；
- `recognize_formula` 只接受模型明确给出的 region，并用稳定 `formula_ref` 归并同一公式；
- 同一任务同一公式最多三次 recognize，次数写入 session application event，accept 不计；
- `recognize_formula` 已移除 `repair_span_id` 和 `replacement_text`；模型只负责从原 PDF
  确定页码与 region、检查 OCR 候选并接受，不再记忆乱码或管理缓存写入目标；
- cache manifest 升级为 v4；每个 revision 新增 `formulas.jsonl`，accept 追加页码、region、
  `formula_ref`、LaTeX 与证据哈希，保留原 `layout.txt`；页面读取自动附加该页已接受公式；
- 有编号公式优先以编号作为辅助 `formula_ref`；无编号公式用附近短语，持久定位仍绑定 PDF
  SHA、物理页与明确 region；不执行全文公式 OCR；
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
- 已在 `docs/assets/formula-ocr-active-localization/` 保存两组缓存文本、实际模型裁图和可读
  OCR 渲染；两张裁图文件 SHA-256 与 trace 中 `render_sha256` 完全一致。
- Skill v3 重跑 Q2 完成 4 次 recognize 和 2 次 `refined=false` accept；manifest v4 的
  `formulas.jsonl` 保存 2 条记录，原 `layout.txt` 哈希保持不变；
- Q3 在全新 conversation 中直接读到 accepted overlay，recognize/accept 均为 0，证明
  跨会话零 OCR 复用有效；Q2/Q3 最终答案各 12/12 标签正确；
- 原样记录仍含 `\operatorname*{m a x}` 与 `e x p`，因此缓存公式精确匹配 Gold 为 false；
  当前不能把最终回答的正确规范化反推成缓存 LaTeX 已正确。
- 同模型 Codex CLI 基线已完成正式评分：Q1 weighted 66.67%，Q2/Q3 均为 12/12，macro
  weighted 88.89%；Q2 前误发的 Q1 在工具调用或可用答案前即终止，只作为排除运行计入
  运营损耗。跨系统比较已完成。

尚未完成：

- 未运行 Python 测试、Ruff 或 mypy；
- 未核对旧 v3 缓存在 v4 中按需重建时的产品提示和重新识别体验；
- 未验证同一公式三次重裁剪后的次数拒绝、Helper 失败计数和重试恢复；
- 尚未决定如何在不允许模型重写完整公式的前提下，安全处理 `m a x` / `e x p` 等局部
  OCR 拼写间距；缓存公式精确性仍未达到产品验收条件；
- 尚未用无编号公式覆盖 v4 accept 与跨会话复用。

### 3. 构建并验证 Plus-M Formula OCR 可选组件

状态：`public_adhoc_assets_published_fresh_install_validation_pending`。

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
- [`formula-ocr-v1`](https://github.com/lemma42796/paper-copilot/releases/tag/formula-ocr-v1)
  已公开发布 schema-v2 manifest、`1.1.0` ARM64 Runtime 和
  `PP-FormulaNet_plus-M-1.0.0` 模型归档；公开 manifest 的 URL、字节数和 SHA-256 与
  GitHub Release 资产一致；
- 当前没有 Developer ID；公开资产明确使用 ad-hoc 签名并定位为开发测试版本，不把 Apple
  公证列为本地验收前提。

尚未完成：

- 尚未从全新 App 安装中点击设置页下载，验证公开 manifest、Runtime 和模型归档的下载、
  校验、安装、原子激活及首次识别全链路；
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

### 5. 发布并补全 PDF 工具链自动恢复验证

状态：`poppler_recovery_with_existing_homebrew_validated_homebrew_bootstrap_and_release_pending`。

已完成：

- `library_exec` 支持单次精确审批的附加网络/文件权限与 sandbox 外执行；审批绑定命令、
  固定 cwd、权限和输入哈希，默认 sandbox 边界不变；
- 管理员路径使用受限 `SUDO_ASKPASS` 与 macOS 隐藏输入框，密码不进入模型、session 或
  trace；所有命令具有硬超时，取消和超时终止原进程组；
- Research Skill v29 在首次论文读取前检查 `pdfinfo`、`pdftotext`、`pdftoppm`；缺少
  Poppler 时先恢复 Homebrew，再安装 Poppler，随后回到默认 sandbox 复验；
- 已有工具链路径由 `trace-5287b51caa264d7eae63cfe065cd7521` 验证，不重复安装或申请权限；
- 卸载 Poppler 后，`trace-ce7fccb047d24934b9ffa339bbeda742` 通过独立自动审批，在 sandbox
  外执行 `brew install poppler`，安装 26.07.0，并在默认 sandbox 用真实 PDF 验证元数据
  读取、文本提取和页面渲染；未使用管理员权限；
- 自动审批输出预算已从 300 提高到 1000 Token；三次真实审批分别使用 601、686、838
  Token 并返回 `allow`；shell wrapper 已启用 `pipefail`，默认和升级包装器的失败/成功
  管道退出码定向验证为 1/0。

尚未完成：

- 在完全没有 Homebrew 的 macOS 上验证官方安装脚本、管理员密码输入和取消路径；
- 构建新的 Apple Silicon DMG，验证内嵌 Runtime 后发布下一版 Preview；
- 从新 Release 下载并运行，复验 Poppler 自动恢复和论文解析；
- 未运行 Python 测试、Ruff 或 mypy；`pipefail` 修复目前只有定向命令验证。

### 6. 验证 macOS 中英本地化与模型配置界面

状态：`implementation_complete_xcode_build_and_visual_validation_pending`。

已完成：

- 新增简体中文/英文界面切换，语言偏好保存在 `UserDefaults`，切换后由根视图注入 locale；
- 覆盖聊天、设置、模型配置、审批、诊断与常见运行状态的动态文案；模型系统提示要求回答
  跟随用户提问语种，不绑定界面语言；
- 删除不再需要的 Composer proposal/plan 生产代码、协议字段、测试和评测脚本依赖，并保留
  旧 session/config 中相关字段的兼容清理；
- 添加模型页改为服务预设优先：DeepSeek V4 Flash、DeepSeek V4 Pro、Qwen 3.7 Flash 和
  自定义；预设自动填写 Model ID、Base URL、能力与价格，只要求用户填写 API Key；
- Qwen 3.7 Flash 使用 `qwen3.7-flash`，北京区不超过 32K Token 的公开价为输入 0.2、
  输出 0.8、显式缓存创建 0.25、显式缓存命中 0.02 元/百万 Token；
- 聊天输入区模型菜单直接显示当前模型和当前思考强度/思考预算；API Key 继续保存到权限为
  `0600` 的 Application Support `auth.json`，与 Codex 默认文件存储语义一致。

尚未完成：

- 尚未执行本轮 Swift 变更后的 Xcode build；
- 尚未在运行中的 App 里逐页检查中英文切换、添加模型表单、菜单宽度及当前值显示；
- Python 全量 pytest 在删除 Composer 后曾通过 199 项并产生 5 条 SWIG 警告，但该结果早于
  后续仅限 macOS SwiftUI/本地化的修改。
