# STATUS

> 当前任务的跨会话接力快照。每次更新覆盖旧内容，不追加历史流水；详细设计与实验结果
> 保存在各自产物中。

更新于 2026-08-04。

## 新会话从这里继续

下一步验证“无论文数据库 + 按需 TXT 缓存 + 可选本地公式 OCR”闭环。目标行为是：

1. 客户端启动和 Agent 预检不批量生成论文正文缓存，只建立授权论文 inventory manifest；
2. 模型只对当前任务需要的论文调用 `paper-cache ensure <pdf>`，生成该论文的
   `layout.txt`；
3. 模型读取 TXT，只有任务确实需要理解或引用某个带 `cache_slot` 的乱码公式时才调用
   `recognize_formula` 的 `recognize`，不得仅因发现乱码就识别；
4. `recognize` 只返回 `PP-FormulaNet_plus-S` 候选 LaTeX 和 `candidate_id`，不修改 TXT；
5. 模型判断候选可接受后调用 `accept`，Runtime 才在新 revision 中替换对应乱码区块，
   原子发布为 current，并自动删除同一缓存键下的旧 revision。
6. 论文目录是唯一 inventory；不创建 `fields.db`、`embeddings.db`、
   `embeddings_meta.json` 或 `embedding_cache.sqlite`。
7. `paper-cache page/search` 使用 PDF 相对路径，每次读取前重算 PDF SHA-256；完整启动扫描
   成功后删除没有现存 PDF 哈希对应的孤立缓存，扫描失败时不删除。

## 已实现但尚未验证

- 已物理删除现有四个论文数据库文件；Python Runtime 不再打开论文数据库或预热 embedding
  模型，`sqlite-vec` 依赖和论文索引核心模块已经删除。
- Agent 与 MCP 不再暴露旧的论文数据库检索、读取、比较和 Composer 索引工具；模型工具面
  保留 `load_skill`、受限 shell、页图、OCR 和 library edit。
- `agents/paper_copilot.py` 中不可达的旧索引 schema、分发分支、检索/比较函数和相关 imports
  已清理，不再以死代码保留旧论文索引实现。
- `paper-cache page/search` 已改为以当前 PDF 相对路径定位，并在每次读取前执行 SHA-256
  校验/按需 ensure。替换 PDF 会使用新哈希键，不会返回旧 PDF 的缓存。
- inventory 对全部 PDF 计算哈希；仅在完整扫描无失败时删除孤立缓存。运行期间 Finder 删除
  PDF 后允许缓存保留到下次启动/首轮完整扫描。
- 缓存受控读取使用共享文件锁，OCR 的读取-替换-发布使用独占文件锁；同一 TXT 的多次 OCR
  接受会在最新 current 上累积，并继续只保留当前 revision。

- PDF cache schema 已改为 v2，持久产物恢复为 `layout.txt`，不再使用
  `structured.md`。`pdftotext` 仍由受控缓存层内部调用；模型命令环境不直接暴露它。
- TXT 保留换页符物理页边界。含 Unicode 替换字符或私用区字形的行会被包进稳定
  `page-NNNN-formula-NNNN` OCR slot，同时保留原始提取文本。
- Runtime 预检现在只计算授权 PDF 的 SHA-256 和页数并生成 inventory manifest，不再
  `ensure` 全部论文。manifest 的 `text` 可为空，`cached=false`。
- `library_exec` 提供窄化的 `paper-cache status/ensure/page/search` broker；命令必须独占整个
  `cmd`，禁止管道、循环、命令链、命令替换和越出授权论文库的路径。
- Formula OCR 工具已改为两阶段协议：`recognize` 将冻结候选保存在当前 Runtime 进程；
  `accept` 校验候选、论文、页码和 PDF SHA 后才调用 cache writeback。
- 接受写回替换精确 slot，记录模型、region、render SHA、LaTeX SHA，创建新 revision，
  原子更新 `current.json` 后自动删除同一缓存键下的旧 revision。`verified=false` 仍保留；
  current TXT 会累积已经接受的公式修复。
- 未接受候选不会持久化；Runtime 退出后必须重新识别，TXT 不发生变化。
- 公式 OCR 页面证据类型已允许 `pdf_formula_ocr`，模型身份以 SHA-256 指纹写入证据字段。
- macOS 设置页、独立 Helper、下载校验和工具暴露门控代码仍在工作树：主客户端不设计为
  包含 PaddlePaddle、PaddleOCR、PaddleX、OpenCV 或模型权重；只有用户点击设置中的下载
  按钮才应发起网络请求。
- 当前活动目录中没有遗留 `structured.md`。此前删除的 14 个活动 `layout.txt` 和短论文
  验证产生的 2 个临时 `layout.txt` 尚未重建；以后应由模型按需生成。322 个历史实验副本
  作为审计证据保留。

关键代码入口：

- `src/paper_copilot/shared/pdf_cache.py`
- `src/paper_copilot/agents/paper_copilot.py`
- `src/paper_copilot/agents/library_exec_tool.py`
- `src/paper_copilot/agents/tools/runtimes/library_environment.py`
- `src/paper_copilot/agents/formula_ocr_tool.py`
- `src/paper_copilot/agents/research_evidence.py`
- `src/paper_copilot/formula_ocr_helper.py`
- `apps/macos/PaperCopilot/Runtime/FormulaOCRManager.swift`
- `src/paper_copilot/agents/skills/research-papers/SKILL.md`
- `scripts/build_formula_ocr_component.sh`
- `docs/design/formula_ocr_optional_component.md`

## 下一步：按顺序做最小验证

1. 记录验证前 cache 状态；启动客户端并新建对话，确认只出现 inventory manifest，没有任何
   论文生成 `layout.txt`。
2. 让模型选中一篇论文并调用 `paper-cache ensure`；确认只有这一篇产生 TXT，随后用 PDF
   相对路径调用 `paper-cache page/search`，并确认替换 PDF 后不会沿用旧哈希缓存。
3. 做静态依赖检查：默认 Runtime 和主客户端产物不得包含或导入 Paddle；只有
   `formula-ocr` 依赖组与独立 Helper 可以包含它。
4. 构建开发版 ARM64 Helper。该步骤会写 `build/formula-ocr-component/`，开始前向用户说明
   构建耗时、磁盘写入和不调用付费模型，并取得执行确认。
5. 不走网络下载，用开发环境覆盖变量指向 Helper。选择带真实 `cache_slot` 的乱码公式运行
   `recognize`，保存原始 JSON、裁剪图、候选 LaTeX、耗时，并确认 cache revision 未变化。
6. 人工检查候选后运行 `accept`，保存返回值和新 revision；重新读取 TXT，确认只替换目标
   slot，其他正文和页边界保留，并确认旧 revision 已自动删除。
7. 验证工具暴露矩阵：纯文本模型 + 已安装 Helper 可见；纯文本 + 未安装不可见；图像模型
   不可见且继续暴露 `inspect_page`。
8. 验证 UI 网络门控：启动、选择模型、悬浮均无下载；只有点击设置按钮才请求 manifest。
   固定 GitHub Release 尚无正式产物，因此正式下载链路留到发布后验证。

## 约束与未决事项

- 原 PDF 始终是公式权威证据；“模型接受候选”只授权写入派生 TXT，不代表数学正确性。
- 当前乱码 slot 只由 Unicode 替换字符和私用区字形触发；未编号且没有 region 的行内公式
  以及复杂表格恢复不在当前切片。
- 不自动下载 Paddle 组件，不启动模型/API 调用，不因 OCR 安装重启正在执行的任务。
- 尚未运行 Swift/Python 测试、构建、客户端启动验证或 TXT/OCR 端到端验证。
- 固定 Release URL 尚无可下载产物；Developer ID 签名、公证和正式发布必须在功能验证后
  单独处理，不能把开发用 ad-hoc 签名当作发布验证。

## 工作树事实

- OCR 代码已以 `199cbd2` push 到 `origin/main`；本轮论文数据库删除与缓存一致性改造也已
  完成，并由本文件所在提交 push 到 `origin/main`。
- 工作树同时包含用户此前的实验 runner、Skill、配置、评分文档、`AGENTS.md`、依赖锁文件
  和 `tmp/` 改动；它们不是本验证任务可以清理或覆盖的内容。
- 新会话开始时先读 `TASKS.md`、本文件、`ARCHITECTURE.md` 的研究缓存章节和
  `docs/design/formula_ocr_optional_component.md`，然后只处理上述最小验证范围。
