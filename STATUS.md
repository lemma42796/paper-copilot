# STATUS

> 当前任务的跨会话接力快照。每次更新覆盖旧内容，不追加历史流水；详细设计与实验结果
> 保存在各自产物中。

更新于 2026-08-09。

## 新会话从这里继续

PDF 字体乱码恢复三条源码路径均已通过代表性真实学位论文缓存验证。Cambria Math 既有
结果保持不变；彭思懿和闵青青的 Symbol MT 私用区字符分别从 337 降到 33、从 104 降到
0；张振宇 ReaderEx 的 8,779 个空字形控制字符全部删除，公式槽从 1,947 降到 0，且删除
后的文本逐字等于原提取文本仅移除 4 个已验证码点。

旧结论“Symbol MT 为非 Identity”已纠正：两篇论文的 `DescendantFonts` 指向间接单元素
数组，数组内真实后代字体明确声明 `/CIDToGIDMap /Identity`，旧解析查错对象才误判为
`null`。张振宇的 `B3+SimSun` 才是真的缺失映射；现在只在页面实际 GID 唯一、内嵌字形
为空轮廓、码点不由其他字体输出时删除。打包后的 macOS App 仍未验证，所以尚未完成产品
级验收。

公式定位已经按用户确认的方案重构：缓存仅预埋弱坐标提示，模型主动查询逐字符坐标并明确
给出 OCR region；三个旧自动定位入口已经删除。OCR 流程从 `research-papers` 拆到独立
`formula-ocr` Skill，同一任务同一公式最多三次 recognize，accept 写回显示 LaTeX。实现尚未
跑 Python 测试或真实论文重建验证，不能宣称产品可用。后续真实验证提示词已经冻结在
`docs/design/formula_ocr_validation_prompt.md`；客户端性能修复已通过本地合成压测，但公式
OCR 长链路本身仍未执行验证。

macOS 长 reasoning 流第三轮 3,278 条回归和历史上强退的 10,000 条突发均已通过：两次
事件、顺序和全文哈希完整，最大主 actor 超期分别为 0.462 秒和 0.505 秒，且都发生在冷却
阶段；回放阶段最大约 0.222 秒和 0.210 秒，均无超过 1 秒的样本。10,000 条峰值 CPU
74.68%、冷却平均 21.19%、最后采样 23.31%，未复现持续满核。模型、Runtime 请求和凭据
读取计数均为 0。用户接受以 3,278、10,000 和 500 公式三项为本轮验收边界，不再运行
50,000 条耐久或追加压测，因此客户端满核假死修复与压测入口任务已关闭。该结论不覆盖
真实模型长流、长时间重复运行或内存泄漏证明。

报告公式直接显示 LaTeX 源码的原因已经确认并完成源码修复：原视图没有 TeX 排版引擎，
报告又主要使用 `latex` fenced code block。用户已批准原生 SwiftMath，工程现锁定 `1.7.3`；
完成报告会识别常用展示和行内数学定界符，解析失败保留原始 LaTeX。为避免重新放大流式
重绘，生成中的活动文本仍保持轻量纯文本。修复 `CGFloat.greatestFiniteMagnitude` 类型歧义
后，Debug/Release arm64 构建均通过；尚未做 App 内公式视觉验证。

设置页现已加入客户端本地压测入口：可选 3,278 条回归、10,000 条突发、50,000 条耐久和
500 个公式预设。事件、推理文本、回答和公式全部由 Swift 确定性生成，压测路径不调用
`PaperCopilotAPI`、Python Runtime、模型或凭据存储；本地压测会话也拒绝真实提交。运行会
复用生产事件发布和 UI 渲染路径，并把完整性哈希、CPU、常驻内存和主 actor 采样间隔写入
`~/.paper-copilot/stress-tests/<run_id>/`。用户首次运行三个预设：3,278 条与 500 公式写出
完整产物，10,000 条突发卡死后强退。旧版把内容完整误显示为绿色成功且只在结束时落盘；
现在已把 1 秒主 actor 响应阈值纳入通过判定，并在开始前写 `run.json`、运行中检查点更新
`samples.json`。第二轮 3,278 条被正确判为失败；第三轮 3,278 条与 10,000 条已分别以
最大超期 0.462 秒和 0.505 秒通过。此前 500 公式也通过。50,000 条耐久、停止/强退恢复
和重复长跑未执行；用户已明确本轮不再继续压测，它们不是本次交付的待办项。

## PDF 字体乱码恢复实现

`src/paper_copilot/shared/pdf_font_repair.py` 的入口为
`repair_pdf_font_unicode_maps`。所有修复要求 Type0、Identity-H，并逐项证明 PDF 字符码
对应的内嵌 GID：解析直接或间接单元素 `DescendantFonts`，接受 `/Identity` 或显式
`CIDToGIDMap` 流；映射缺失时只允许下面列出的观测证据路径。

当前支持三条窄路径：

- Cambria Math：验证 PDF 字体名与内嵌字体身份后，从内嵌字体自身的 Unicode `cmap`
  恢复普通字形，并用 OpenType `MATH` 变体表恢复完整的伸缩字形；拼装括号、拼装积分号
  和未知字形保留为 `U+FFFD`，不把局部轮廓冒充完整字符。
- Symbol MT：把内嵌字体的 `uniF0XX` 字形名还原为 Adobe Symbol 字节码，再通过预置的
  Adobe Symbol 标准编码和 fontTools Adobe Glyph List 恢复 α、β、∑、≠、∈ 等 Unicode
  字符；映射缺失时还要求 `get_texttrace()` 的实际 GID 唯一并与 `uniF0XX` 精确相符；未
  定义编码和公式拼装件保留为 `U+FFFD`。
- ReaderEx：不根据下载来源判断，只处理基字体名精确为 `B3+SimSun`、`ToUnicode` 目标
  位于私用区、页面实际 GID 唯一且内嵌字形没有轮廓的映射；并验证同一码点不由其他字体
  输出。命中后直接从原始 `pdftotext` 产物删除该码点，不改 CMap，避免改变正文阅读顺序。
  普通汉字、非空私用区字形和其他字体不处理。

`src/paper_copilot/shared/poppler.py` 已接入上述修复：

1. 只有 Cambria Math 或 Symbol MT 的 `ToUnicode` 需要重建时，才在输出目录创建临时
   Unicode 修复 PDF 并让 `pdftotext -layout` 读取；
2. 只有 ReaderEx 控制符时直接读取原 PDF，再删除已验证且跨字体独占的码点；
3. 无论成功或失败都清理临时 PDF。

提取器 fingerprint 已加入
`font_unicode_repair=embedded-cmap-math-symbol-readerex-v3`，旧缓存不会冒充新结果。
`pyproject.toml` 和 `uv.lock` 已加入 fontTools，当前锁定解析版本为 `4.63.0`；macOS
PyInstaller 构建脚本已加入 `--collect-all fontTools`。

## Cambria Math 真实论文验证

验证论文为 65 页的《基于低秩融合与动态增强的多模态行人重识别研究》（何子玲，2023）：

- 原 PDF：
  `/Users/a123/paper-copilot-test-pdfs/硕士学位论文/基于低秩融合与动态增强的多模态行人重识别研究_何子玲_2023.pdf`；
- 字体修复命中 1 个 Cambria Math 字体，重建 7,613 条 Unicode 映射；
- 原始文本有 851 个 `U+FFFD`，修复后为 0；私用区字符、C0 控制字符和旧缓存 schema 的
  公式槽均为 0；
- 只有物理页 21、22、24 的提取文本发生变化；原 PDF 视觉核对确认三元组损失、四元组
  损失和 mAP 公式中的 `A/P/N`、`alpha/beta`、`N/i/AP_i` 恢复正确；
- 隔离缓存首次 `ensure` 返回 `generated`，第二次直接命中同一 revision；65 个物理页边界
  完整，构建后没有残留临时修复 PDF；
- 保留供人工查看的 `layout.txt` 位于
  `tmp/pdfs/font-repair-validation-he-ziling-2023/layout.txt`，SHA-256 为
  `dc773d5cdb7828b82e761cd43ccaad97cd9cec156dad5945abdff07676fe43a3`。该路径受仓库根
  `/tmp/` 规则忽略，不提交或推送。

验证使用仓库 `.venv` 中的当前源码和隔离缓存，没有构建或启动 macOS App，也没有修改
App 当前缓存或原论文。因此结论仅覆盖源码 `PdfTextCache` 的 Cambria Math 路径。

## 其余学位论文代表性缓存抽查

2026-08-09 对其余 13 篇学位论文先做只读字体资格预筛，再选择 6 篇代表样本重建隔离缓存，
没有批量重建全部论文。结果如下：

| 论文 | 代表类型 | 字体修复 | 原始→修复后乱码 | 最终公式槽 | 结论 |
|---|---|---:|---:|---:|---|
| 项莘泽，2025，134 页 | 可修复 Cambria Math | 1 字体 / 7,613 映射 | `U+FFFD` 317→37 | 13 | 有效但不完整；残留集中在向量箭头/横线字符 |
| 张耀斌，2024，78 页 | 可修复 Cambria Math | 1 字体 / 7,613 映射 | `U+FFFD` 1,590→0 | 26 | 公式字符恢复；26 个 `U+F06C` 实为项目符号假阳性 |
| 彭思懿，2025，120 页 | 间接数组中的 Identity Symbol MT | 1 字体 / 191 映射 | PUA 337→33，新增 `U+FFFD` 23 | 7 | 标准 Symbol 数学字符恢复；其他字体 PUA 与拼装件仍保留 |
| 张振宇，2024，66 页 | 缺失映射的 ReaderEx | 1 字体 / 删除 4 映射 | PUA 8,779→0 | 0 | 4 个码点的实际 GID 唯一、空轮廓且跨字体独占；正文顺序不变 |
| 闵青青，2024，73 页 | 间接数组中的 Identity Symbol MT | 1 字体 / 191 映射 | PUA 104→0，新增 `U+FFFD` 52 | 10 | 标准字符恢复；未定义编码和拼装件显式保留为未解析 |
| 张兴帅，2024，72 页 | 不修改对照 | 未修改 | PUA 31→31 | 3 | 修复前后文本哈希一致；PUA 是分段括号拼装件 |

人工原页抽查未调用 OCR：项莘泽物理页 28、39 显示剩余 `U+FFFD` 对应带箭头或横线的
向量符号；张耀斌物理页 23 的标签平滑公式恢复后与原页结构一致，物理页 38 的
`U+F06C` 是黑色项目符号而非公式；彭思懿与闵青青的标准 Symbol 字符现在按内嵌字体
编码恢复，未定义编码和拼装件显式转为 `U+FFFD`；张振宇删除后的 `layout.txt` 逐字等于
原提取文本仅移除 `U+E5CE/U+E5CF/U+E5D2/U+E5E5`，没有普通字符丢失或重排。

原 6 篇抽查之外，最终 v3 又选彭思懿、张振宇、闵青青、张兴帅和何子玲 5 篇执行实际
`PdfTextCache.ensure`：均在新隔离根中首次生成，第二次直接命中同一 revision；没有遗留
`.unicode-repaired.pdf`，5 份原 PDF 的 SHA-256 与验证前记录一致。最终审计产物位于
`tmp/pdfs/font-repair-gid-validation-final-20260809/`，其中 `summary.json` 的 SHA-256 为
`2c919f3138ed9f8e75db1a931c837038f02959f638ab7b98e27f6310449458d1`。

按上述 7 篇代表样本合并计算，显式乱码信号定义为 PUA、`U+FFFD` 与异常 C0 字符之和：
修复前为 12,035 / 2,918,226，即 `0.412408%`；修复后为 202 / 2,908,673，即
`0.006945%`，显式乱码字符总数减少 `98.32%`。这是代表性抽查的整体结果，不是全部论文
的全量统计；它会把合法 PUA 项目符号计入乱码，也无法发现根号、范数竖线等静默丢失，
因此不能解释为公式准确率。长期记录见
[PDF 字体 Unicode 恢复验证](docs/design/pdf_font_unicode_repair_validation.md)。

此前 v2 抽查审计产物仍保留于 `tmp/pdfs/font-repair-survey-20260809/`，其中：

- 首批 4 篇摘要 `summary.json`，SHA-256
  `a65e3f2a773382dd178f212b94c9df963764b82552acfb0637312f3f64d6b28c`；
- 两篇实际命中摘要 `eligible-summary.json`，SHA-256
  `17176d2e9327ca89dd53189bb374e05aa9e31f533d98adff4656ea863d67d973`。

上述两个目录均受仓库根 `/tmp/` 规则忽略；未写入 App 当前缓存，也未修改原 PDF。

## 无 OCR 的公式理解验证

使用上述缓存对物理页 33、34、44、46 的 (3.3)、(3.5)、(3.6)、(4.3)、(4.4)、
(4.10) 做了一次真实 Paper Copilot 验证。prompt 明确禁止 `recognize_formula`、
`inspect_page`、OCR、视觉工具、联网和外部版本；任务只读取文本缓存，job
`job-20260808T180219-3bfaa96a8a` 单次 attempt 正常完成，终止原因为 `end_turn`，费用
为 0.07550792 元。报告位于：

`/Users/a123/.paper-copilot/papers/conversation-20260808T180219-a36c1a373a/research-report.md`

当前人工复核结论：

- (3.3)、(3.6) 的关键变量、运算符、界限和结构在缓存中保留得较充分，模型给出的重建
  有说服力；
- (4.3)、(4.4) 的损失语义大概率能理解，但范数竖线不在缓存中，L2 平方和 L1 范数仍
  含结构推断，不能表述为文本层精确恢复；
- (3.5) 存在 `R/r`、`⊗/⋀` 和跨页归属冲突，(4.10) 缺分段大括号且 `N` 未定义；模型
  正确保留了互斥候选和不可确定边界，没有静默统一；
- 结论是“模型能理解多数公式的语义和骨架，并能识别关键歧义”，不是“扁平文本足以
  精确恢复所有公式”。严格引用或复现算法时，(3.5)、(4.10) 仍需视觉原页或其他独立证据，
  (4.3)、(4.4) 也必须注明范数结构来自推断。

## macOS 长推理流满核假死

同一 job 生成的客户端 `events.jsonl` 共 3,278 行、1,176,218 字节，其中 reasoning
2,749 条、assistant 511 条。trace 与 job 终态表明模型调用、四次文本读取和最终回答均
正常结束，流式期间也没有长时间无事件，因此不是模型、网络或 Python Runtime 卡死。

任务结束后于 2026-08-09 02:13:59–02:14:01 连续三次读取进程状态：macOS
`PaperCopilot` 为 100.0%、99.0%、100.1% CPU，`uv run paper-copilot-runtime` 与 Python
Runtime 均为 0.0%，`WindowServer` 为 48.5%–49.4%。直接症状是客户端界面进程持续占满
一个核心并带动窗口合成负载。

修改前源码中的主要问题链：

1. `AppModel` 为 `@MainActor`，每个 SSE payload 都把 fresh events 立即追加到
   `@Published jobEvents`；
2. `JobTurnView` 随最后事件序号变化把完整 events 数组交给 accumulator，并在视图求值时
   再过滤完整事件列表；
3. accumulator 对每个 delta 执行增长字符串追加，live reasoning 标题又反复扫描完整
   reasoning 文本。

第一轮让纯 delta 最多每 200 ms 合并发布一次；活动字符串在数组内原位追加，生命周期事件
和 reasoning 标题增量归约，完成后的 reasoning 展示只计算一次；timeline 使用
`LazyVStack`。服务端事件、SSE 游标、持久化和恢复语义未改。首次 3,278 条回放证明内容
完整但响应性失败：最大主 actor 超期 36.07 秒。该预设逐条发送事件，暴露出 reasoning
完成事件单独发布时先展开布局完整 transcript、下一批 assistant 才折叠的中间状态。第二轮
将 reasoning 默认保持折叠后，最大超期降到 2.55 秒；新曲线剩余高负载集中在后半段流式
回答。第三轮限制生成中回答预览为最近 4,000 字符并关闭选择，完成报告不丢全文；3,278 条
回归与 10,000 条突发均已通过。用户接受当前验证边界，不再运行 50,000 条耐久。

为执行该验证，设置页增加了只在客户端内运行的压测模块。合成任务进入既有 `applyEvents`
和 conversation 视图，但不会进入 API、Runtime、模型或正常持久化。运行中每 0.5 秒采样
进程 CPU、常驻内存和主 actor 延迟，事件完成后继续采样 10 秒；事件总数、序号、文本字符数
和 SHA-256 一并写入 JSON。首次两个完整产物确认模型、Runtime 与凭据计数均为 0。旧版
强退目录为空，现已改为开始前写 `run.json`、运行中每两秒更新 `samples.json`；同时新增
1 秒主 actor 响应阈值，内容完整但卡顿会标红失败。第二轮 3,278 条已正确标红；第三轮样本
新增 `deliveredEvents`，可直接映射 reasoning/assistant 阶段。3,278 条回归和 10,000 条
突发均已通过。

## 本轮文件边界

- `src/paper_copilot/shared/pdf_font_repair.py`：确定性字体识别、内嵌字体读取及
  `ToUnicode` 重建。
- `src/paper_copilot/shared/adobe_symbol_encoding.py`：Adobe Symbol 标准编码表。
- `src/paper_copilot/shared/poppler.py`：临时修复副本接入和 ReaderEx 验证码点清理。
- `tests/shared/test_pdf_font_repair.py`：CMap、后代字体、GID 与正文顺序的定向测试。
- `pyproject.toml`、`uv.lock`：fontTools 依赖。
- `scripts/build_macos_app.sh`：macOS Helper 打包收集 fontTools。
- `apps/macos/PaperCopilot/AppModel.swift`：delta 事件合并发布、压测编排、本地会话隔离、
  真实提交阻断以及 Runtime 任务刷新隔离。
- `apps/macos/PaperCopilot/Views/ConversationDetailView.swift`：活动增量归约、reasoning 展示
  缓存和 timeline 惰性布局。
- `apps/macos/PaperCopilot/Views/MarkdownReportView.swift`：展示/行内数学解析、SwiftMath
  图片排版缓存和原始 LaTeX 降级。
- `apps/macos/PaperCopilot/Diagnostics/ClientStressTest.swift`：本地事件/公式生成、资源采样、
  完整性摘要和压测产物写入。
- `apps/macos/PaperCopilot/Views/SettingsView.swift`：压测预设、开始/停止、进度与资源指标入口。
- `apps/macos/PaperCopilot.xcodeproj/project.pbxproj` 与 workspace `Package.resolved`：加入并
  锁定 SwiftMath `1.7.3`。
- `ARCHITECTURE.md`：同步字体恢复和客户端本地压测边界。
- `TASKS.md`：保留字体恢复、公式定位、Plus-M 和数学排版的未完成验证；已完成的客户端
  性能与压测入口任务从活动清单移除。

上述字体抽查发生在公式定位重构之前，使用的是旧缓存 schema。当前源码已换成弱提示、
`repair_span_id`、`query_page_geometry`、显式 region OCR 和整段 LaTeX accept；旧验证不能
替代新 schema 的真实论文重建与端到端验证。

## 尚未验证

按仓库规则，本次执行了用户确认的 8 项定向 pytest、5 篇代表性论文缓存验证和
Debug/Release arm64 客户端构建，没有运行 Ruff、mypy、完整 pytest 或包含 Python Helper
的完整分发打包。以下事项仍待完成：

1. 找到真实使用显式 `CIDToGIDMap` 流的 PDF 做集成验证；当前流解析和 CID→GID 应用只有
   定向测试，真实样本覆盖的是间接数组内 `/Identity` 与缺失映射 ReaderEx；
2. 构建 macOS App，确认 PyInstaller 包含 fontTools 所需模块，并在产品缓存目录复现结果；
3. 在完成报告中验证 SwiftMath 的展示/行内公式、现有多行 `latex` block、深浅色、长公式、
   链接和失败降级。流式活动文本按设计不做数学排版；

客户端压测已按用户接受的边界结束，不再把 50,000 条、停止/强退恢复或重复长跑列为本轮
待办。现有单轮产物不能证明真实模型长流表现或长期无内存泄漏。

## 其他未完成工程线

Plus-M Formula OCR 源码已在提交 `16522a8` 完成，但当前安装的 macOS 可选组件仍是
Plus-S。尚未构建、签名、发布或安装 Plus-M `1.1.0` Runtime/模型组件，也未验证冷启动、
连续复用、超时或崩溃重启、一小时空闲退出和真实公式识别。

本地 Plus-M 权重仍位于：

- 目录：`/Users/a123/Downloads/formula-ocr-m/PP-FormulaNet_plus-M_infer/`
- 归档：`/Users/a123/Downloads/formula-ocr-m/PP-FormulaNet_plus-M_infer.tar`
- 归档 SHA-256：`f208430a7ec1079fce53a447b340e0183bf6c5c14e32915886635c37ec4c5fd9`

构建时显式设置上述模型目录；不要覆盖当前已安装组件，也不要在真实验证前发布 manifest。

## 公式定位任务

当前实现已删除旧三级自动定位。缓存构建只对“有损坏字符且没有中文或英文正文词”的连续
视觉行写 `formula_hint`：首行第一个损坏字符 bbox、末行最后一个损坏字符 bbox、行数和
`advisory=true`；混合正文行没有坐标，也不建立覆盖整行的自动替换范围。无正文损坏行由
`repair_span_id` 限定允许替换的范围，但该 ID 不提供 crop。

模型先按编号或上下文语义找页，再用 `query_page_geometry` 搜索正文/编号或枚举限定区域的
行和逐字符坐标，最终自己给出明确 region。`recognize_formula` 不接受编号或缓存框自动
裁剪。同一公式同时按 `formula_ref` 和冻结写入目标归并，任一相同都计入同一上限，
recognize 最多三次；每次真正进入 Helper 推理前写 application event，Helper 失败也计数，
目标或渲染预检失败不计数，accept 不计数。

接受时，乱码公式通过冻结的 `repair_span_id` 整段替换；非乱码但疑似漏运算符或结构符的
公式通过页面内唯一匹配的完整 `replacement_text` 替换。目标哈希变化或不唯一均拒绝写入。
缓存内容是带 `verified=false` 标记的 `$$ ... $$` 显示 LaTeX。原 `research-papers` Skill
只保留公式证据不足边界，全部 OCR 操作步骤位于新 `formula-ocr` Skill；Runtime 会拒绝
未加载该 Skill 的坐标探索和 OCR 调用。

尚未验证：新 fingerprint 的真实论文缓存重建、预埋提示与原页对应、三次重裁剪上限、
乱码和非乱码两条 accept 写回、缓存回读，以及 macOS 打包 App。
缓存 manifest 已升为 v3；旧 v2 accepted OCR revision 不自动迁移，相关公式需要按新锚点
重新识别。尚未验证产品是否应为这种重建提供显式提示。

后续验证采用 `docs/design/formula_ocr_validation_prompt.md` 中已冻结的自然用户请求。目标为
项莘泽公式 (2-9)、彭思懿 CMC 示例中的无编号 Rank-3 计算式和何子玲公式 (4.10)，分别覆盖
有编号乱码、无编号语义定位及非乱码但可能静默丢结构的复杂分段公式。提示词不告诉执行
模型这是评测，也不提供预期物理页或正确公式结构；首轮只 recognize、不 accept，要求把
每次 region、candidate_id、render_sha256 和原始 LaTeX 写入最终报告。当前裁剪 PNG 仅存在
于临时目录并在 Helper 调用后删除，不能把提示词要求误报为图片已持久化。

## Git 与下一步

- 分支：`main`。
- 本次提交包含客户端性能修复、内置压测入口、数学排版、SwiftMath 依赖及状态文档。
- 不提交 PDF、临时修复副本、生成缓存、权重、凭据、构建产物或私有实验产物。

建议下一步：检查完成报告中的常用数学定界符和现有 `latex` 代码块，再按任务 2 重建代表
缓存并发送已经冻结的自然用户提示词；人工复核定位与裁剪证据后，单独验证三次上限和
LaTeX accept/回读。不要把公式定位结果与此前字体恢复验证混为同一验收。Plus-M 打包仍
保持独立任务。
