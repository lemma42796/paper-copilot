# PDF 字体 Unicode 恢复验证

更新于 2026-08-09。

## 目的与边界

本文长期记录 PDF 字体 Unicode 恢复的确定性门槛与代表性源码缓存验证结果。它验证的是
`PdfTextCache` 中显式乱码信号的变化，不把文本缓存视为公式原文，也不替代原 PDF 的视觉
或结构化核对。

当前修复版本进入 Poppler extractor fingerprint：

`font_unicode_repair=embedded-cmap-math-symbol-readerex-v3`

实现只处理 Type0、Identity-H 字体，并要求字符码到内嵌 GID 的关系可以证明：

- 解析直接数组或指向单元素数组的间接 `DescendantFonts`；
- 接受 `/CIDToGIDMap /Identity` 或显式 `CIDToGIDMap` 映射流；
- 映射缺失时，Cambria Math 不处理；Symbol MT 必须由页面实际 GID 与内嵌字形名逐项
  验证；ReaderEx 还必须满足实际 GID 唯一、空轮廓及码点跨字体独占。

ReaderEx 验证码点直接从原始 `pdftotext` 产物删除，不通过临时 CMap 标记重映射，避免
改变 `-layout` 的普通字符阅读顺序。源码永不修改原 PDF。

## 代表样本与整体结果

验证集由 7 篇代表性学位论文组成，覆盖 Cambria Math、Symbol MT、缺失
`CIDToGIDMap` 的 ReaderEx 和不修改对照；这是有目的的代表性抽查，不是全部论文的全量
统计。

显式乱码信号统一定义为：

`PUA 字符数 + U+FFFD 数 + 异常 C0 字符数`

整体结果：

| 阶段 | 显式乱码字符 | 文本总字符 | 显式乱码率 |
|---|---:|---:|---:|
| 修复前 | 12,035 | 2,918,226 | 0.412408% |
| 修复后 | 202 | 2,908,673 | 0.006945% |

显式乱码字符总数减少 `98.32%`。

最终 v3 代表样本均通过实际 `PdfTextCache.ensure` 生成：第一次为 `generated`，第二次命中
同一 revision；原 PDF 的 SHA-256 未变化，没有遗留 `.unicode-repaired.pdf`。ReaderEx
样本修复后的文本逐字等于原始提取文本仅删除 4 个已验证 PUA 码点，共 8,779 个字符，
普通字符及顺序不变。

定向测试 `tests/shared/test_pdf_font_repair.py` 共 8 项通过，覆盖完整 ToUnicode CMap 展开、
间接后代数组、显式 CID 到 GID 映射、观测 GID 门槛、空轮廓删除及正文顺序保持。没有运行
Ruff、mypy、完整 pytest 或 macOS App 构建。

## 指标不能代表公式准确率

显式乱码率只能回答“缓存里有多少可见乱码信号”，不能回答“公式与原 PDF 是否完全
一致”：

- 合法 PUA 也会被计入。例如代表样本中有 26 个 `U+F06C` 实际是正文项目符号，会高估
  乱码率；
- 根号、范数竖线等符号可能在文本层静默消失，不留下 PUA、`U+FFFD` 或 C0，会低估公式
  错误；
- 上下标、分式和求和上下限即使字符齐全，也可能因二维布局被压平而产生结构歧义。

无 OCR 的视觉抽查中，4 个没有显式乱码信号的公式有 2 个仍丢失关键结构：一处交叉注意力
公式缺少 `√d` 的根号，一处余弦相似度公式缺少范数竖线和分母根号。因此，本结果不能写成
“公式准确率 99.993055%”或“公式已全部恢复”。精确转写、算法复现和关键公式核对仍需原
PDF 视觉证据或按需 Formula OCR。

## 审计与后续验证

最终隔离审计目录：

`tmp/pdfs/font-repair-gid-validation-final-20260809/`

其中 `summary.json` 的 SHA-256 为：

`2c919f3138ed9f8e75db1a931c837038f02959f638ab7b98e27f6310449458d1`

该目录受仓库 `/tmp/` 规则忽略，不属于提交内容；以上关键口径与结论保存在本文，避免依赖
可清理的本地缓存才能理解结果。

尚未完成：

- 用真实采用显式 `CIDToGIDMap` 映射流的 PDF 做集成验证；
- 构建 macOS App，验证 PyInstaller 中的 fontTools 和产品缓存路径结果一致；
- 如需正式公式准确率，冻结视觉 Gold、公式样本边界和评分规则后另做评测，不能从本显式
  乱码率反推。
