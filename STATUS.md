# STATUS

> 当前任务的跨会话接力快照。每次更新覆盖旧内容，不追加历史流水；详细设计与实验结果
> 保存在各自产物中。

更新于 2026-08-09。

## 新会话从这里继续

主动坐标探索式公式 OCR 已完成第一次真实长链路验证：新 fingerprint 缓存、公式弱提示、
`repair_span_id`、`query_page_geometry`、模型主动选择 `region`、本机 Plus-M Helper 和
`recognize_formula` 均在真实论文任务中工作。公式 (2-9) 与 (4.10) 都在第一次裁剪中恢复
完整主体；无编号 Rank-3 内联式通过文本与逐字符几何确认，没有调用不必要的 OCR。

本轮严格按验证提示只 recognize、未 accept，因此不能把“识别成功”写成“写回验证完成”。
(2-9) 已冻结 `repair_span_id`，具备后续安全写回条件；(4.10) 本次没有冻结唯一完整
`replacement_text`，不能直接 accept，必须重新 recognize 并绑定完整替换目标。

Plus-M 可选组件 `1.1.0` 已在本机构建、ad-hoc 签名并安装，`active.json` 当前指向
`versions/1.1.0/FormulaOCRHelper/FormulaOCRHelper`。旧 Plus-S `1.0.0` 只作为回滚版本保留。
当前没有 Developer ID；本地验收不要求 Developer ID 或 Apple 公证，对外发布路径仍需
单独决定。

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

- `repair_span_id=page-0028-repair-0001`；
- region：`{"x1":0.38,"y1":0.09,"x2":0.73,"y2":0.148}`；
- 第 1/3 次成功，用时 8.7 秒；
- candidate：`formula-candidate-77c211087abb4fd3bb2e5e21b166ed3d`；
- render SHA-256：
  `dd2b793aa171b651e36ca67e1f6e70af5bfcd61c979528ed9d9a2fe5e6de0a0b`；
- OCR 恢复向量箭头、根号、求和上下限和平方上标；原始输出的 `\boxed` / `array` 是包装
  产物，裁图顶部横线可能是诱因；
- 已冻结 repair span 与目标哈希，后续可单独验证 accept、revision 更新和缓存回读。

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
- 本次没有 `repair_span_id`、`replacement_text` 或写入目标快照，`cache_write_pending=false`；
  该 candidate 不能直接安全 accept。

## Plus-M 本机组件状态

- Runtime/模型组件版本：`1.1.0`；manifest schema：2；
- Helper：ARM64，ad-hoc 签名，已通过 `codesign --verify --deep --strict`；
- 当前激活配置：
  `/Users/a123/Library/Application Support/Paper Copilot/optional-components/formula-ocr/active.json`；
- 当前 Helper：
  `/Users/a123/Library/Application Support/Paper Copilot/optional-components/formula-ocr/versions/1.1.0/FormulaOCRHelper/FormulaOCRHelper`；
- 回滚版本：同目录 `versions/1.0.0/`，另有 `active.plus-s-1.0.0.json` 备份；
- 两次连续真实调用均使用 `PP-FormulaNet_plus-M`，分别 8.7 秒、3.126 秒。

这只验证了本机正常启动、连续调用和真实识别。尚未专项验证 Helper 超时、崩溃重启、
一小时空闲退出，也没有把 manifest/归档发布到公开下载端。

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

1. 单独验证 (2-9) accept：确认 `repair_span_id` 整段写回、manifest/artifact 哈希更新与
   下一次缓存命中，公式不消失；
2. 为 (4.10) 重新 recognize 并冻结唯一完整 `replacement_text`，再验证非乱码公式整段
   替换；不要复用当前无写入目标的 candidate；
3. 验证三次 recognize 上限、失败计数、Helper 超时/崩溃重启和一小时空闲退出；
4. 做完整 App 打包与 SwiftMath 视觉验证；
5. 继续寻找真实显式 `CIDToGIDMap` 流 PDF，补上字体修复集成覆盖。

## 本次文件边界与验证

当前变更包含：

- `src/paper_copilot/agents/formula_ocr_tool.py`：分离 PageEvidence schema 版本；
- `src/paper_copilot/agents/page_geometry_tool.py`：净化孤立 surrogate；
- `docs/stories/active_formula_localization.md`：真实主动定位展示与边界；
- `docs/assets/formula-ocr-active-localization/`：6 张稳定证据图片；
- `TASKS.md`、`STATUS.md`：同步最新任务与接力状态。

本轮没有运行 Python 测试、Ruff、mypy 或新 App 构建。验证证据来自已完成的真实 Paper
Copilot 任务、trace、组件激活配置、裁图哈希复核和文档图片目视检查。`output/` 中两张
重复的临时裁图不是交付文件，不应提交。
