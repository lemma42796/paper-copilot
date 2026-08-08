# STATUS

> 当前任务的跨会话接力快照。每次更新覆盖旧内容，不追加历史流水；详细设计与实验结果
> 保存在各自产物中。

更新于 2026-08-09。

## 新会话从这里继续

PDF 字体乱码恢复已完成源码实现，并通过一篇 65 页真实学位论文验证 Cambria Math 的
源码缓存路径。原始 `pdftotext -layout` 中的 851 个 `U+FFFD` 全部恢复，变化只出现在
物理页 21、22、24；已逐页对照原 PDF，数学字母、希腊字母和公式结构一致。实际
`PdfTextCache.ensure` 首次生成完整缓存，第二次命中同一 revision，临时修复 PDF 已清理。

这仍不是产品级验收：Symbol MT、ReaderEx、普通 PDF 不修改路径和打包后的 macOS App
均未验证。当前提取链只为满足确定性条件的字体生成临时修复副本，原 PDF 不修改；公式
定位算法、槽位结构和缓存 schema 均未改动。

公式定位方法由用户明确延期，后续将重新设计。不要继续给现有三级定位链打补丁，也不要
把本轮字体恢复与公式定位重构混在一起。

## PDF 字体乱码恢复实现

新增 `src/paper_copilot/shared/pdf_font_repair.py`，入口为
`repair_pdf_font_unicode_maps`。所有修复同时要求 Type0、Identity-H 且
`CIDToGIDMap` 为 Identity，因此 PDF 字符码可确定地沿 CID 找到同号 GID。

当前支持三条窄路径：

- Cambria Math：验证 PDF 字体名与内嵌字体身份后，从内嵌字体自身的 Unicode `cmap`
  恢复普通字形，并用 OpenType `MATH` 变体表恢复完整的伸缩字形；拼装括号、拼装积分号
  和未知字形保留为 `U+FFFD`，不把局部轮廓冒充完整字符。
- Symbol MT：把内嵌字体的 `uniF0XX` 字形名还原为 Adobe Symbol 字节码，再通过预置的
  Adobe Symbol 标准编码和 fontTools Adobe Glyph List 恢复 α、β、∑、≠、∈ 等 Unicode
  字符；未定义编码和公式拼装件保留为 `U+FFFD`。
- ReaderEx：不根据下载来源判断，只处理基字体名精确为 `B3+SimSun`、`ToUnicode` 目标
  位于私用区且对应内嵌 GID 没有任何字形轮廓的映射。命中的空控制字形先映射到内部
  非字符标记，`pdftotext` 完成后再从文本产物删除。普通汉字、非空私用区字形和其他字体
  不处理。

`src/paper_copilot/shared/poppler.py` 已接入上述修复：

1. 在输出目录创建临时 Unicode 修复 PDF；
2. 有确定性修复时让现有 `pdftotext -layout` 读取临时副本，否则读取原 PDF；
3. 清理 ReaderEx 内部标记；
4. 无论成功或失败都删除临时 PDF。

提取器 fingerprint 已加入
`font_unicode_repair=embedded-cmap-math-symbol-readerex-v2`，旧缓存不会冒充新结果。
`pyproject.toml` 和 `uv.lock` 已加入 fontTools，当前锁定解析版本为 `4.63.0`；macOS
PyInstaller 构建脚本已加入 `--collect-all fontTools`。

## Cambria Math 真实论文验证

验证论文为 65 页的《基于低秩融合与动态增强的多模态行人重识别研究》（何子玲，2023）：

- 原 PDF：
  `/Users/a123/paper-copilot-test-pdfs/硕士学位论文/基于低秩融合与动态增强的多模态行人重识别研究_何子玲_2023.pdf`；
- 字体修复命中 1 个 Cambria Math 字体，重建 7,613 条 Unicode 映射；
- 原始文本有 851 个 `U+FFFD`，修复后为 0；私用区字符、C0 控制字符和公式乱码
  `cache_slot` 均为 0；
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

## 本轮文件边界

- `src/paper_copilot/shared/pdf_font_repair.py`：确定性字体识别、内嵌字体读取及
  `ToUnicode` 重建。
- `src/paper_copilot/shared/adobe_symbol_encoding.py`：Adobe Symbol 标准编码表。
- `src/paper_copilot/shared/poppler.py`：临时修复副本接入和 ReaderEx 标记清理。
- `pyproject.toml`、`uv.lock`：fontTools 依赖。
- `scripts/build_macos_app.sh`：macOS Helper 打包收集 fontTools。
- `ARCHITECTURE.md`：同步字体恢复边界。
- `TASKS.md`：公式定位任务标记为用户延期。

本轮没有修改公式检测、bbox、`cache_slot`、`locate_page_text`、`equation_label`、Formula
OCR Skill 或 accept 流程。

## 尚未验证

按仓库规则，本次只执行了用户要求的单篇论文窄验证，没有运行 Ruff、mypy、pytest 或
macOS App 构建。以下事项仍待完成：

1. 用 Symbol MT 论文验证希腊字母和标准数学符号，同时确认拼装件仍保持未解析；
2. 用含 `B3+SimSun` ReaderEx 空控制字形的知网论文验证控制字符被删除而正文汉字不变；
3. 用普通期刊或会议 PDF 验证不符合条件的字体完全不修改；
4. 构建 macOS App，确认 PyInstaller 包含 fontTools 所需模块，并在产品缓存目录复现结果。

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

当前实现仍是 `cache_slot` bbox → `locate_page_text` 双锚点 → `equation_label` 三级链，但
用户认为多个定位方法会干扰模型，而且论文公式不一定带编号。该任务状态为
`deferred_by_user`：后续应重新拆分公式发现、区域定位、OCR、核实和 accept，再选择唯一或
最小定位方法；方案确认前不修改现有实现。

## Git 与下一步

- 分支：`main`。
- 本次状态更新只提交 `TASKS.md` 和 `STATUS.md`。
- 不提交 PDF、临时修复副本、生成缓存、权重、凭据、构建产物或私有实验产物。

建议下一步：选择一篇确实满足确定性条件的 Symbol MT 论文做同样的源码缓存与原 PDF
对照；之后再验证 ReaderEx、普通 PDF 和打包 App。验证结果不通过时只修字体恢复，不
顺带调整公式定位。
