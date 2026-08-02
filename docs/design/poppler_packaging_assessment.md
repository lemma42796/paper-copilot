# Poppler 打包与许可证评估

状态：已选择用户授权后单独安装，不随 `.app` 分发  
日期：2026-07-27  
保真度复核：2026-08-02  
范围：工具系统 v2 Slice 1

## 结论

当前不能把 Homebrew Poppler 或基于同一许可证构建的 `pdfinfo`、`pdftotext` 直接加入
Paper Copilot `.app`。

Paper Copilot 当前使用 MIT License。Poppler 26.04.0 随附的上游 `README.md` 明确说明
Poppler 使用 GPL 而不是 LGPL，并声明调用 Poppler 的程序也需要采用 GPL。随附
`COPYING` 是 GPL v2；Homebrew 公式元数据把当前版本标记为
`GPL-2.0-only OR GPL-3.0-only`。

Paper Copilot 通过独立进程和命令行参数调用 Poppler，而不是把 `libpoppler` 链接进
Python Runtime。GNU GPL FAQ 将简单 `fork`/`exec` 和命令行通信视为通常保持程序分离的
因素，但是否构成一个组合程序仍取决于通信语义和整体设计。将两个程序一起放入单个
`.app` 并把 Poppler 作为核心内建能力分发，不能在没有明确许可证决策或法律审查时假定
仍属于 mere aggregation。

因此本结论是工程发布门，不是法律意见：在项目所有者明确选择分发策略前，不修改
`scripts/build_macos_app.sh`，不复制 Poppler 二进制或动态库，也不改变项目许可证。

## 本机打包证据

评估版本：

- Poppler 26.04.0；
- Apple Silicon；
- Homebrew bottle；
- `pdfinfo` 和 `pdftotext` 均为 ad-hoc 签名。

两个命令都动态链接 `libpoppler.159.dylib`。该库继续依赖 Freetype、Fontconfig、
JPEG Turbo、OpenJPEG、Little CMS、libpng、libtiff、NSS、NSPR、GPGME 及其传递依赖。
Homebrew Poppler keg 本身约 33 MB，动态库 install name 指向
`/opt/homebrew/opt/...`。直接复制两个命令不会形成可运行的独立包；需要收集依赖、
重写 install name、固定配置文件和字体发现行为，并对完整闭包重新签名。

现有 `scripts/build_macos_app.sh` 使用 PyInstaller 收集 Python Runtime 和
`sqlite_vec`，并按固定 Codex package manifest 下载、校验和打包自包含的 `rg`。
这不提供 Poppler 的第三方 Mach-O 依赖闭包收集、install-name 重写或对应源码发布
流程，也不改变本评估的 Poppler 分发结论。

## 已完成的运行时验证

未打包的本机 Poppler adapter 已验证：

- 首次查询为 cache miss；
- `ensure` 生成完整 TXT revision；
- 第二次查询命中同一 revision；
- 页级文本可以按 manifest 边界读取；
- artifact hash 损坏后状态为 corrupt，并生成新 revision；
- PDF 内容变化生成新的内容 hash；
- 原始 PDF 未被修改；
- 临时验收缓存已随临时目录删除。

该验证只证明缓存接口和本机命令行为，不证明 `.app` 分发合规或打包完整。

## 缓存保真度复核

2026-08-02 对一篇代表性论文同时检查原始 PDF 页面和 `pdftotext -layout` 缓存，已经
足以否定“TXT 可作为所有论文内容的唯一模型可见证据源”：

- 张耀斌论文的公式密集页在原始 PDF 渲染中可读；对应 `layout.txt` 中 GraphSAGE、
  相似度、损失函数和动量更新公式的大量变量变成 `�` 或私用区字形
  （private-use glyph）；
- 正文段落和物理分页仍可用于搜索与定位，但公式的变量、上下标、求和范围和矩阵符号
  已无法可靠恢复；
- 数值表格的主体数值有时仍能保留，但符号表头、复杂层级、合并单元格和勾叉标记不具备
  同等保证。不能从“数值行可读”推断整张表语义完整。

该问题发生在 PDF 到文本缓存的提取阶段，不是原始 PDF 损坏。后续遇到同类保真度问题，
一篇代表性 PDF 的原页/缓存对照即可证明机制缺陷；只有要估计发生率、受影响论文比例或
回归覆盖时才需要全量扫描。

因此当前证据层级为：

1. `layout.txt` 继续承担批量发现、普通正文搜索和物理页定位；
2. 原始 PDF 是公式、复杂表格和视觉布局的权威来源；
3. 图像输入模型可通过 `inspect_page` 检查原页；纯文本（text-only）模型当前没有可靠
   回退，必须显式报告证据限制；
4. 不能只把 TXT 改名为 Markdown，也不能把损坏字符直接替换成 LaTeX。PDF 通常只保存
   字形和坐标而非源 LaTeX；识别器还可能生成“语法合法但数学含义错误”的公式。

目标缓存若采用 Markdown，应是带结构和来源映射（provenance）的派生物：普通正文使用
Markdown，公式使用可核验 LaTeX，复杂表格使用 HTML 或结构化 cells，并保留物理页、
bbox、提取器版本和置信度。低置信度、Unicode 替换字符（replacement character）、
公式区或复杂表格区必须回退到原 PDF 页面或更高保真解析器。该目标尚未实现；引入新
解析器（parser）、外部依赖或独立视觉模型调用前，仍需单独设计、许可证审查、成本估算
和冻结论文质量评测。

### Codex 源码对照

在 Codex 源码 `6751b54cae32b23786001e2414d749a9916201e1` 中：

- `codex-rs/protocol/src/user_input.rs` 的 `UserInput` 支持 text、image、audio、Skill 和
  mention，没有 PDF 输入类型；
- `codex-rs/core/src/tools/handlers/view_image.rs` 只读取本地图像，并在模型不支持
  `InputModality::Image` 时直接返回不支持错误；
- 当前 Codex PDF Skill 建议先用 `pdftoppm` 把 PDF 页面渲染成 PNG，再交给图像模型
  视觉检查；`pdfplumber`/`pypdf` 只用于文本提取和快速检查，并明确不能承担布局保真。

因此 Codex 核心（core）没有内建通用的 Mathpix/Nougat/Marker 式公式转 LaTeX 工具。
它的一般高保真路径是“PDF 页面渲染为图像 -> `view_image` -> 支持图像输入的模型”，
这条路径对当前纯文本 V4 Flash 不可用。

## 可选方向

### A. 解决现有 PyMuPDF 许可证后复用 Python PDF 底座

使用仓库已经依赖的 PyMuPDF 实现相同的确定性全文 TXT、换页边界和 extractor
fingerprint，不增加新依赖，也不修改公开工具。

PyMuPDF 官方文档说明其采用 AGPL 或商业双许可证。因此它不是当前 MIT 分发的自动安全
替代品；项目需要确认已有商业许可，或决定满足 AGPL。现有 `.app` 已内嵌 PyMuPDF，
所以这是当前分发就已存在的问题，不是 v2 才引入的问题。

许可证边界解决后，PyMuPDF 的文本布局仍与 Poppler 不完全相同，需要使用冻结论文重新
做缓存和证据定位验收。

### B. 保留 Poppler，建立 GPL 合规分发方案

明确项目整体许可证策略，并实现许可证文本、版权声明、对应源码、构建脚本、依赖清单
和可重建发布流程。该方向会改变当前 MIT 分发政策，需要项目所有者明确批准，并建议先
获得专业法律意见。

### C. 要求用户自行安装 Poppler

代码只发现系统中的 `pdfinfo`/`pdftotext`，`.app` 不分发它们。环境缺少 Poppler 时，
Skill 先询问用户是否同意执行 `brew install poppler`；只有明确同意后才安装。Homebrew
本身缺失时不自动安装 Homebrew。

### D. 选择其他 PDF substrate

单独评估 macOS PDFKit、BSD-3-Clause 的 pypdf、MIT 的 pdfminer.six、其他许可兼容的
实现或商业许可证。pypdf/pdfminer.six 都是新依赖；PDFKit helper 会新增 Swift/Python
边界。任一方向都需要项目所有者批准、质量对比和分发审查。

## 建议

项目所有者已选择 C：Poppler 不随 `.app` 分发，只在环境缺失且用户明确同意后通过
Homebrew 单独安装。当前 Slice 1 不实现通用系统安装工具，也不放宽 `library_exec` 的
无网络和只读边界；安装执行能力留到论文研究 Skill 落地时按当时宿主能力接入。

现有 PyMuPDF 的 AGPL/商业双许可证仍是独立的既有分发问题，不因 Poppler 改为单独安装
而自动解决。

## 依据

- Poppler 26.04.0 随附 `README.md` 和 `COPYING`；
- Poppler 官方文档中的 GPL 版权声明：
  <https://poppler.freedesktop.org/api/cpp/poppler-image_8h_source.html>；
- GNU GPL v2 FAQ 对独立进程、命令行通信、mere aggregation 和组合程序的说明：
  <https://www.gnu.org/licenses/old-licenses/gpl-2.0-faq.html>；
- GNU GPL FAQ 对二进制分发和对应源代码的说明：
  <https://www.gnu.org/licenses/gpl-faq.en.html>；
- PyMuPDF 官方许可证说明：
  <https://pymupdf.readthedocs.io/en/latest/about.html>；
- pypdf 官方许可证说明：
  <https://pypdf.readthedocs.io/en/latest/meta/faq.html>；
- pdfminer.six 官方文档与包元数据：
  <https://pdfminersix.readthedocs.io/en/master/>、
  <https://pypi.org/project/pdfminer.six/>；
- 本机 `brew info --json=v2 poppler`、`otool -L`、`codesign -dvvv` 和 `du` 输出；
- `LICENSE`、`pyproject.toml` 与 `scripts/build_macos_app.sh`。
