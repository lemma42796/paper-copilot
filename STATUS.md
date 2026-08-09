# STATUS

> 当前任务的跨会话接力快照。每次更新覆盖旧内容，不追加历史流水；详细设计与实验结果
> 保存在各自产物中。

更新于 2026-08-10。

私有历史实验已迁移为单层当前值结构：每个实验根目录直接保存 `experiment.md`、Query、
私有标签、rubric、metrics、包含逐项裁决的 `scores.yaml` 与 `evidence.yaml`。相同协议的
正式重跑只保留最新值；2026-08-08 的 PC V4 Flash 单系统重跑已拆成独立实验
`pc-v4flash-current-max`。旧 `_audit/` 与 `raw/` 包装层已移出活动 `experiments/`，可恢复地
保存在私有根目录 `legacy_experiment_artifacts/`；原始 runs、session、job 和 trace 未删除。

## 新会话从这里继续

主动坐标探索式公式 OCR 已完成第一次真实 recognize 长链路验证。随后按用户批准简化
accept：模型不再提交 `repair_span_id`、`replacement_text` 或乱码原文，只负责从原 PDF
确定物理页与 `region`、检查候选并接受。cache manifest 源码已升到 v4，每个 revision 新增
`formulas.jsonl`；accept 追加已接受 LaTeX 记录，原 `layout.txt` 不变，页面读取自动在末尾
附加该页公式。多数有编号公式把编号作为辅助 `formula_ref`；无编号公式用附近短语，定位
仍绑定 PDF SHA、页码和 region。它是按需积累的公式文档，不是全文预 OCR。

新 overlay 已在张耀斌论文的正式 Q2/Q3 重跑中验证。Q2 完成 4 次 recognize 和 2 次
`refined=false` accept；Q3 在全新 conversation 中直接读取两条 accepted 记录，OCR 为 0。
两个最终答案各 12/12 标签正确，但缓存原始 LaTeX 仍含 `m a x` / `e x p`，所以跨会话复用
有效而缓存公式精确匹配 Gold 失败。当前私有评分与逐项裁决保存在实验根目录
`scores.yaml`，原始回答和 trace 由 `evidence.yaml` 索引。

同模型 Codex CLI 基线也已交付并完成正式评分。Q1 为 6 correct、4 partial、2 incorrect，
weighted 66.67%；主要错误是公式（3-4）时间差方向和公式（3-9）条件概率锚点/候选方向。
Q2、Q3 均为 12/12，三个 query 的 macro weighted 为 88.89%。Q2 前误发的 Q1 在任何工具
调用或可用答案产生前即终止，没有向 Q2 注入论文证据，按用户裁决只作为排除运行计入
运营损耗；正式跨系统比较已经完成。

正式运营汇总（均排除各系统已明确标记的非正式运行）：Paper Copilot 用时 387.708 秒、
736,319 Token、36 次模型调用、55 次工具调用且 0 次失败，成本 ¥0.16953724；Codex CLI
用时 1,947.231 秒、19,271,592 Token、216 次模型调用、227 次工具调用尝试且 27 次失败，
成本 ¥1.04421308。相对 Codex CLI，Paper Copilot 在本次实验减少约 80.1% 耗时、96.2%
Token 和 83.8% 成本。结论只适用于当前论文、模型与完整 Agent 配置，不是 OCR 组件的
单变量因果结论。

Apple Silicon App 开发预览
[`v0.1.0-preview.1`](https://github.com/lemma42796/paper-copilot/releases/tag/v0.1.0-preview.1)
已公开发布，包含 70,614,645 字节的 `PaperCopilot-arm64.dmg` 和 SHA-256 文件；GitHub API
报告的 DMG 摘要
`9f7f0d09b70b73c24870b66302ed46b95924762a3f3ab1d592ea4898fb08b540` 与公开校验文件一致。
这只验证了 Release 元数据和资产存在，尚未从 GitHub 全新下载安装并运行。

Plus-M 可选组件 `1.1.0` 已在本机构建、ad-hoc 签名并安装，`active.json` 当前指向
`versions/1.1.0/FormulaOCRHelper/FormulaOCRHelper`。公开
[`formula-ocr-v1`](https://github.com/lemma42796/paper-copilot/releases/tag/formula-ocr-v1)
已包含 schema-v2 manifest、`1.1.0` ARM64 Runtime 和 `PP-FormulaNet_plus-M-1.0.0`
模型归档；manifest 的 URL、字节数和 SHA-256 与 GitHub Release 资产一致。旧 Plus-S
`1.0.0` 只作为本机回滚版本保留。当前没有 Developer ID，App 与 Formula OCR 均为
ad-hoc 签名、未经 Apple 公证的开发预览；设置页全新下载与安装仍未验证。

真实运行首次暴露两个协议错误，当前工作区源码已修复：

- `formula_ocr_tool.py` 将工具 schema 2 错写为 `PageEvidence.schema_version`，导致首次 OCR
  后在证据校验阶段中断；现在证据 schema 独立固定为 1。
- `page_geometry_tool.py` 可能从 PyMuPDF 收到孤立 UTF-16 surrogate，JSON/UTF-8 序列化会
  中断；现在在提取边界统一替换为 `U+FFFD`。

用于 README 后续展示的详细案例与 6 张稳定图片已经建立：

- [主动公式定位案例](docs/stories/active_formula_localization.md)
- [案例图片目录](docs/assets/formula-ocr-active-localization/)

文档明确区分缓存文本、模型实际裁图、原始 OCR LaTeX 与整理后的可读渲染；不宣称“零
算法定位”或“任意公式都能一次成功”。两张模型裁图的文件 SHA-256 与真实 trace 中的
`render_sha256` 完全一致。

## 主动公式 OCR 真实验证

成功任务：`job-20260809T092725-b68b814a53`。

- 状态：`completed`，单次 attempt，终止原因 `end_turn`；
- 费用：`0.07822684 CNY`；事件数：49；
- 报告：
  `/Users/a123/.paper-copilot/papers/conversation-20260809T092725-a73177d1a1/research-report.md`；
- Trace：
  `/Users/a123/.paper-copilot/jobs/job-20260809T092725-b68b814a53/attempts/1/trace.jsonl`；
- 没有失败的工具调用，未调用 accept，当前 v3 缓存没有 accepted formula OCR record。

### 公式 (2-9)

论文：《基于多模态信息融合的行人轨迹追踪方法研究》（项莘泽，2025），物理页 28。

- 当时旧协议记录了 `repair_span_id=page-0028-repair-0001`；新协议不再使用该字段；
- region：`{"x1":0.38,"y1":0.09,"x2":0.73,"y2":0.148}`；
- 第 1/3 次成功，用时 8.7 秒；
- candidate：`formula-candidate-77c211087abb4fd3bb2e5e21b166ed3d`；
- render SHA-256：
  `dd2b793aa171b651e36ca67e1f6e70af5bfcd61c979528ed9d9a2fe5e6de0a0b`；
- OCR 恢复向量箭头、根号、求和上下限和平方上标；原始输出的 `\boxed` / `array` 是包装
  产物，裁图顶部横线可能是诱因；
- 候选属于旧 Runtime 进程，后续需重新 recognize，再验证 overlay accept 与缓存回读。

### Rank-3 内联式

论文：《基于多粒度特征融合的多模态行人重识别研究》（彭思懿，2025），物理页 39。

- 通过上下文、`60%` 文本锚点和逐字符坐标确认
  `Rank-3 = 3 / 5 × 100% = 60%`；
- 属于正文内联表达式，缓存信息足够，没有调用 OCR，也没有 candidate 或裁图。

### 公式 (4.10)

论文：《基于低秩融合与动态增强的多模态行人重识别研究》（何子玲，2023），物理页 46。

- region：`{"x1":0.36,"y1":0.545,"x2":0.88,"y2":0.63}`；
- 第 1/3 次成功，用时 3.126 秒；
- candidate：`formula-candidate-4cec34d2168f41419e805509f1d9eeaa`；
- render SHA-256：
  `1ae5b33808fdab6a3e67a431f2454603312904d8cc1de630834da980af2c212a`；
- OCR 恢复两组分段左花括号和二维结构，裁图包含编号，所以原始结果尾部带 `(4.10)`；
- 旧协议因没有写入目标快照而不能 accept；新协议已取消该前提，但旧进程 candidate 不复用。

## Plus-M 本机组件状态

- Runtime/模型组件版本：`1.1.0`；manifest schema：2；
- Helper：ARM64，ad-hoc 签名，已通过 `codesign --verify --deep --strict`；
- 当前激活配置：
  `/Users/a123/Library/Application Support/Paper Copilot/optional-components/formula-ocr/active.json`；
- 当前 Helper：
  `/Users/a123/Library/Application Support/Paper Copilot/optional-components/formula-ocr/versions/1.1.0/FormulaOCRHelper/FormulaOCRHelper`；
- 回滚版本：同目录 `versions/1.0.0/`，另有 `active.plus-s-1.0.0.json` 备份；
- 两次连续真实调用均使用 `PP-FormulaNet_plus-M`，分别 8.7 秒、3.126 秒。

这只验证了本机正常启动、连续调用和真实识别。公开 manifest、Runtime 与模型归档的元数据和
摘要已核对，但尚未从全新 App 安装中执行设置页下载、校验、安装、激活与首次识别。Helper
超时、崩溃重启和一小时空闲退出也未专项验证。

## PDF 字体乱码恢复

Cambria Math、Symbol MT 和缺失 `CIDToGIDMap` 的 ReaderEx 三条源码缓存路径已通过代表性
真实论文验证。7 篇代表样本的显式乱码信号从 12,035 / 2,918,226 降为
202 / 2,908,673，即减少 98.32%；这不是公式准确率，不能发现根号或分段括号等静默结构
丢失。

提取器 fingerprint 为 `embedded-cmap-math-symbol-readerex-v3`。定向 pytest 8 项通过，
覆盖完整 CMap、间接后代数组、显式 CID→GID 解析与应用、观测 GID 门槛、空轮廓删除和
正文顺序保持。

仍未完成：

- 找到真实使用显式 `CIDToGIDMap` 流的代表 PDF 做集成验证；现有真实样本覆盖
  `/Identity` 与映射缺失 ReaderEx，显式流目前只有定向测试；
- 构建包含 Python Helper 的完整 macOS App，确认 PyInstaller 收集 fontTools 并在产品
  缓存目录复现源码结果。

长期记录见 [PDF 字体 Unicode 恢复验证](docs/design/pdf_font_unicode_repair_validation.md)。

## 报告数学排版与客户端性能

SwiftMath `1.7.3` 已锁定，Debug/Release arm64 构建通过；完成报告支持常用展示/行内数学
定界符，解析失败保留原始 LaTeX。仍需 App 内视觉核对深浅色、长公式横向滚动、链接与
失败降级。生成中的活动文本按设计继续使用轻量纯文本。

客户端长流性能修复已按用户接受的 3,278 条、10,000 条和 500 公式边界通过；不再把
50,000 条耐久、停止/强退恢复和重复长跑列为本轮待办。现有结果不证明真实模型长期运行
无内存泄漏。

## 下一步

1. 从 GitHub Release 全新下载安装 App，验证 Gatekeeper 手动放行、内嵌 Runtime、产品缓存
   字体恢复、SwiftMath 视觉效果，以及设置页 Formula OCR 下载与首次识别；
2. 决定 `m a x` / `e x p` 等局部 OCR 拼写间距的安全处理方式，不允许模型重写完整公式；
3. 用无编号公式覆盖 v4 accept 与跨会话复用；
4. 验证三次 recognize 上限、失败计数、Helper 超时/崩溃重启和一小时空闲退出；
5. 继续寻找真实显式 `CIDToGIDMap` 流 PDF，补上字体修复集成覆盖。

## 本次文件边界与验证

本轮只同步发布状态文档：`README.md`、`README.en.md`、`TASKS.md`、`STATUS.md` 与
`docs/design/formula_ocr_optional_component.md`。没有修改产品代码，也没有运行 Python 测试、
Ruff、mypy、App 构建或发布后安装。公开状态通过 GitHub Release API 与 manifest 读取核对；
没有下载 70.6 MB DMG 做本地独立哈希，只确认 GitHub API 报告的摘要与公开 SHA-256 文件一致。
`output/` 中两张重复的临时裁图仍不是交付文件，不应提交。
