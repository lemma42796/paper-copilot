# Paper Copilot 面试亮点：按需论文缓存一致性与可选本地公式 OCR

> 记录日期：2026-08-06
> 当前状态：仓库内实现与端到端验证均已收口。
> 验证结果：客户端四轮缓存一致性 ALL PASS（12 项断言）、模型可见输出去哈希化四轮
> ALL PASS、工具暴露矩阵四场景 PASS、主客户端静态依赖与网络门控代码级核查 PASS、
> OCR recognize/accept 真实乱码公式闭环与跨会话命中已验证。
> 准确边界：并发安全由设计与端到端验证支持，未经多进程压力测试；不宣称分布式
> 一致性、数据库级事务或跨写入业务无丢失。

## 一句话定位

为本地论文研究 Agent 设计内容寻址的按需 TXT 缓存：以 PDF SHA-256 和提取器指纹为键，
用不可变 revision + current 指针原子发布，用跨进程文件锁串行化读写，并在每次读取前
自检 artifact 完整性；乱码公式走 recognize/accept 两阶段提交，模型确认后才在独占锁内
替换槽位、发布新 revision 并清理旧 revision，保证并发与崩溃下读者只会拿到完整旧版本
或完整新版本，而不是半写状态。

## 问题与约束

论文研究 Agent 需要把 PDF 正文按需提供给纯文本模型，但仓库有硬性约束：

- 主客户端不得包含任何 Paddle 组件或公式模型权重；不保存结构化论文数据库、全文索引、
  向量索引或 embeddings；
- manifest 只建立授权论文清单，客户端启动和 Agent 预检不得批量生成正文缓存；
- 模型可见命令只有 `paper read/search`，模型不接触缓存键、哈希或 revision；
- 缓存由 agent 按需自动生成，且必须能检测 PDF 被替换、删除或提取器版本变化；
- 公式 OCR 是带副作用的写操作，必须由模型显式确认后才写入，且写入不能破坏物理分页
  和正文；
- 多个会话、多个 Runtime 进程可能共享同一个缓存目录，不能依赖单一事件循环假设；
- 不新增第三方依赖、不引入数据库，保持单机桌面应用的最小实现。

## 为什么这是一个工程亮点

普通缓存把“生成结果”和“读取结果”当作两个独立动作，但这个场景有三个容易出错的地方：

1. **缓存和权威 PDF 必须绑定**。同名 PDF 可能被替换成不同内容，缓存键不能只靠文件名；
   如果键只记文件名，读者会拿到旧论文的正文。PDF 在提取过程中也可能被改动，必须先
   记录提取时的 SHA-256，再用读前重哈希验证。
2. **OCR 修复是模型可见的写入**。把 LaTeX 直接写回正在被读取的 layout.txt 会产生
   撕裂读；不确认就写会污染模型证据。因此需要“候选 → 确认 → 原子替换”而不是原地改。
3. **写者不止一个**。并发 `paper read` 首次生成、OCR accept、删除、孤儿清理都可能同时
   发生，且分布在不同的 Runtime 进程里。事件循环内锁只保护同实例协程，跨进程必须依赖
   文件锁和原子发布。

## 核心设计决策

### 1. 内容寻址缓存键

缓存键 = `pdf_sha256 / extractor_fingerprint`：

- PDF SHA-256 让“文件被替换”天然变成新键，旧键可安全清理；
- extractor fingerprint 让不同 Poppler 版本、参数产生的文本互不复用；
- revision 使用 UUID，一旦发布不可变。

### 2. 不可变 revision + current 指针

```text
cache/<pdf_sha256>/<extractor_fingerprint>/
  current.json
  revisions/<revision_id>/layout.txt + manifest.json
```

`current.json` 只存 revision ID。读取总是从 current 指向的 revision 取内容；OCR 修复
生成新 revision 并切换指针，而不是改写旧文件。读者要么看到旧 revision 的完整内容，
要么看到新 revision 的完整内容。

### 3. 原子发布

写入先在 `key_dir` 下创建 staging 目录，生成完整 layout.txt 与 manifest 后：

1. `os.replace(staging_path, revisions/<id>)` 原子换入 revision；
2. `current.json` 用临时文件写入、`flush`、`fsync` 后再 `os.replace` 切换指针；
3. 发布成功后删除同一缓存键下的其他 revision。

manifest 写入同样带 `flush` + `fsync`，避免崩溃后出现“指针已切、内容没落盘”之外的
不一致形状。

### 4. 两层锁

- **跨进程锁**：每个缓存键目录下 `.paper.lock`，用 `fcntl.flock` 共享/独占锁。读取
  （lookup、读页）持共享锁，发布、OCR 写入、删除、孤儿清理持独占锁。这是跨调用、跨
  Runtime 实例的真实互斥保证。
- **进程内锁**：`PdfTextCache` 内按缓存键维护 `asyncio.Lock`，用于同一实例内并发
  `ensure`/`record_formula_ocr` 去重（double-checked lookup）。

注意：生产调用路径每次工具调用都会新建 `PdfTextCache` 实例，因此进程内锁只对“同一实例
被并发复用”的场景生效，真正的跨调用/跨进程保护来自 flock。面试时要主动说清这层边界。

### 5. 读侧完整性自检

每次 lookup/read 都做确定性校验：

- current 指向的 revision 必须存在且 manifest 可解析；
- manifest.pdf_sha256 必须等于请求键、extractor_fingerprint 必须匹配；
- artifact 的 byte_count 与 SHA-256 必须与 manifest 一致；
- 页边界数量必须等于 page_count。

校验失败返回 `corrupt`/`incompatible` 状态并触发重建，而不是把脏数据交给模型。

### 6. TOCTOU 防护

在三个关键时点重新计算 PDF SHA-256：

- 提取完成、发布之前（`ensure` 内）：PDF 在提取期间变化则拒绝发布；
- `page_for_pdf` 返回页面前：当前 PDF 哈希必须仍等于缓存 ref；
- OCR `recognize` 完成、`accept` 之前：PDF 哈希必须仍等于识别时快照。

这样“读缓存”永远先绑定到 PDF 当前字节，不会拿旧哈希当新内容。

### 7. OCR 两阶段提交

`recognize_formula` 的 `recognize` 只返回候选，并把候选绑定到 `pdf_sha256`、page、
render_sha256、model、显式 region 和冻结替换目标，存于进程内受 `threading.Lock` 保护的
字典；`accept`
校验 paper/page 与 PDF 哈希匹配后，在独占锁内执行：

```text
读 current revision 的 layout.txt
  → 校验 repair_span_id 或唯一整段 replacement_text 的哈希
  → 把整个目标替换为 verified=false 标记 + 显示 LaTeX
  → 重算页边界
  → 写 staging 并原子发布新 revision
  → 删除同一缓存键旧 revision
```

因此模型未确认时零写入；确认后写入是原子的；修复在单一 current 中累积。

### 8. 清理安全

- `prune_orphans` 只在 inventory 全量扫描无失败时执行，部分失败绝不删除；
- 每个候选键先持独占锁再 `rmtree`，只删除 64 位 hex 目录且不在 live 集合中的键；
- `_delete_key` 删除键目录后尝试 `rmdir` 外层 sha 目录，失败说明还有其他 fingerprint
  目录，保留是正确的。

## 故障与并发模型

| 场景 | 行为 |
|---|---|
| 两个进程同时首次读同一 PDF | 可能重复提取，但发布串行，最后发布者胜；无撕裂 |
| OCR 写入与读页并发 | 写持独占锁、读持共享锁；读者看到旧完整或新完整 |
| artifact 损坏 | lookup 返回 corrupt，触发重建 |
| PDF 在提取中变化 | 提取后重哈希不一致，拒绝发布 |
| PDF 被删除 | `paper read/search` 报 “PDF no longer exists”，并删除对应缓存键 |
| inventory 扫描部分失败 | 不执行孤儿清理 |
| 识别后 PDF 变化 | `accept` 拒绝 |
| 识别后进程重启 | 内存候选丢失，需重新 recognize（候选不落盘是有意设计） |

## 实现范围

- `src/paper_copilot/shared/pdf_cache.py`：内容寻址键、不可变 revision、原子发布、
  flock 读写锁、完整性自检、孤儿清理；
- `src/paper_copilot/agents/library_exec_tool.py`：`paper read/search` 拦截与按需
  生成，模型可见输出去哈希化；
- `src/paper_copilot/agents/formula_ocr_tool.py`：recognize/accept 两阶段提交与候选
  绑定；
- `src/paper_copilot/agents/paper_copilot.py`：preflight 只建清单，完整扫描后才
  prune；
- `src/paper_copilot/agents/paper_set_tool.py`：论文集合快照绑定 cache ref，current
  变化即标记 stale；
- `apps/macos/PaperCopilot/Runtime/FormulaOCRManager.swift`：可选组件下载与激活；
- `scripts/build_formula_ocr_component.sh`：helper 构建与内容哈希复用。

## 验证方法与真实指标

仓库内端到端验证（2026-08-06）：

1. 同一会话四轮缓存一致性（新增/查询/替换/删除）12 项断言 ALL PASS，模型
   deepseek-v4-flash，会话 `conversation-new-surface-20260806181858`，四轮成本合计
   约 ¥0.08；
2. 磁盘复核：未请求论文零缓存生成，删除后缓存键与外层空目录一起清除；
3. 模型可见输出去哈希化四轮 ALL PASS：`paper read` 输出字段严格等于
   `{page, text}`，`paper search` 为 `{query, matches, truncated}`，会话
   `conversation-new-surface-20260806183148`，成本约 ¥0.054；
4. 工具暴露矩阵四场景复跑 PASS；
5. 主客户端静态依赖与网络门控代码级核查 PASS：import 图无 paddle，打包 App 无
   Paddle 文件，联网仅限设置页下载按钮；
6. OCR 真实乱码公式 recognize/accept 回填与跨会话命中（2026-08-05）：accept 成功
   发布修复 revision，后续会话直接命中 recognized 标记不再 OCR；该修复随缓存一致性
   清理删除，机制已验证。

诚实表述：这是“端到端客户端验证”，不是并发压力测试；并发安全由代码设计与上述
功能闭环支持，没有多进程竞争自动化测试。

## 主要取舍

- **文件系统原子性代替数据库事务**：单机桌面应用规模下，staging + os.replace +
  fsync 已覆盖崩溃和并发；不引入数据库依赖。
- **粗粒度 per-key 文件锁**：简单、跨进程有效，代价是同一缓存键的读读也串行化；
  对单用户桌面场景可接受。
- **last-writer-wins 而不是 CAS**：发布没有对 `current.json` 做乐观并发控制，因此
  极端时序下较旧的 `ensure` 可能在 OCR 修复发布后完成发布并删除该修复。读侧永远
  安全，但业务侧不宣称跨写入强一致。
- **候选不落盘**：recognize 的候选只存在于进程内存，重启即失效；换取的是 accept
  必须发生在同一 Runtime 会话且绑定原始证据，防止跨会话误接受。

## 简历表述

### 推荐版本

> 为本地论文库设计内容寻址的按需 TXT 缓存与可选公式 OCR：以 PDF SHA-256 和提取器
> 指纹为键，用不可变 revision + current 指针原子发布（staging + fsync + os.replace），
> 以跨进程文件锁串行化读写，读取前自检 artifact 完整性并重算 PDF 哈希防 TOCTOU；
> 公式 OCR 采用 recognize/accept 两阶段提交，模型确认后才在独占锁内替换乱码槽位并
> 发布新 revision，保证并发与崩溃下读者只会拿到完整旧版或完整新版。

### 更偏后端可靠性

> 实现跨进程并发安全的本地缓存：per-key flock 共享/独占锁、staging + 原子替换发布、
> SHA-256 内容寻址与 artifact 完整性校验、PDF 重哈希 TOCTOU 防护、孤儿缓存仅在完整
> 扫描后加锁清理；并发写采用 last-writer-wins，不虚构数据库级事务。

### 不要这样写

> 实现分布式缓存强一致性 / 高并发缓存 / 保证所有写入 exactly-once。

系统是单机桌面应用，没有多机协调；并发写入是最后发布者胜，不是多写者事务；OCR
候选丢失、极端时序丢失更新都没有被消除。

## 30 秒面试回答

> 我给论文研究 Agent 做了一个按需缓存。缓存键是 PDF 的 SHA-256 加提取器指纹，
> 内容是内容寻址的不可变 revision，通过 staging 目录加 os.replace 原子发布，
> current.json 用临时文件加 fsync 后原子切换，读之前会校验 manifest 和 artifact 的
> 哈希。多进程之间用 flock 的共享锁和独占锁串行化读写。公式 OCR 不是直接写文件，
> 而是 recognize 返回候选，模型确认后 accept 才在锁内替换乱码槽位并发布新 revision。
> 这样并发或崩溃时读者要么拿到完整旧版本，要么拿到完整新版本，不会读到半写状态。

## 2 分钟 STAR 讲法

### Situation

纯文本模型读论文需要按需生成 PDF 正文 TXT，缓存被多个会话和多个 Runtime 进程共享；
PDF 可能被替换或删除；公式乱码需要本地 OCR 修复并写回缓存，但写入不能污染模型证据。

### Task

在不引入数据库、不把 Paddle 放进主客户端、不暴露缓存键给模型的前提下，保证缓存
一致性与并发安全。

### Action

1. 用 PDF SHA-256 + 提取器指纹做内容寻址键；
2. 用不可变 revision + current 指针 + staging/fsync/原子替换实现无撕裂发布；
3. 用 flock 共享/独占锁串行化跨进程读写；
4. 读取前校验 manifest 与 artifact，提取后、读页前、OCR 后重算 PDF 哈希；
5. 让 OCR 走 recognize/accept 两阶段提交；
6. 只在完整 inventory 扫描成功后加锁清理孤儿缓存；
7. 用客户端四轮增/查/改/删和真实乱码公式做端到端验证。

### Result

四轮缓存一致性 12 项断言 ALL PASS，未请求论文零缓存生成，输出去哈希化四轮 ALL PASS，
OCR 真实公式回填与跨会话命中验证通过；主客户端静态依赖与网络门控核查 PASS。代价是
粗粒度锁和 last-writer-wins，已知但已写清边界。

## 高频追问

### asyncio.Lock 和 flock 各解决什么问题？

asyncio.Lock 是 `PdfTextCache` 实例内的按键锁，防止同一实例上并发 ensure/record 重复
构建；flock 是缓存键目录下的跨进程锁，读取持共享锁、写入持独占锁。生产工具调用每次
都新建实例，所以真正的跨调用保证来自 flock。

### 原子发布具体怎么做？

先生成 staging 目录，`os.replace` 整体换入 `revisions/<id>`；`current.json` 先写
临时文件、flush、fsync，再 `os.replace` 切换指针；最后删除被取代的 revision。发布与
清理都在独占锁内。

### 读页时为什么还要校验？

读取动作和发布/删除可能并发。`_read_page` 持共享锁并再次核对 cache_ref 与 manifest
匹配、artifact 大小和 SHA-256，校验不过就报错，而不是把残缺内容返回给模型。

### 两个写者同时写会发生什么？

发布和 OCR 记录都持独占锁，因此写入本身串行。`ensure` 的提取在锁外，两个进程可能
重复提取，但发布只有一个能成为 current。最终是 last-writer-wins，没有撕裂文件。

### 会不会丢 OCR 修复？

理论上有边缘时序：较早开始的 `ensure` 在 OCR 修复发布后才完成发布，并删除该修复
revision。因为发布没有 CAS，业务侧不宣称无丢失；单用户桌面场景概率很低，读侧一致性
不受影响。

### 崩溃后能保证持久吗？

文件写入都 fsync，指针切换是原子替换，所以不会出现半写内容。没有对目录做 fsync，
极端掉电后可能回退到旧 revision，但旧 revision 本身是完整的。

### 为什么不用数据库？

单机桌面应用没有多实例协调需求，文件系统原子替换加 flock 已经覆盖当前故障模型；
引入数据库会增加部署和维护成本。只有多机或多 worker 才需要把锁和一致性迁移到
数据库/队列。

### 为什么 recognize 候选不落盘？

候选绑定识别时的 PDF 哈希、页面、渲染哈希和模型，accept 必须发生在同一 Runtime
进程内，避免跨会话误接受过期证据。进程重启后重新识别成本很低。

### 为什么坐标提示和替换锚点必须分开？

`formula_hint` 只是首尾损坏字符的弱坐标，模型可忽略或调整；`repair_span_id` 只限定
`layout.txt` 中允许整体替换的范围，不能自动生成 OCR crop。非乱码公式则冻结唯一匹配的
完整原文。这样模型拥有主动定位能力，同时 Runtime 仍能拒绝错位写入。

## 尚未完成与不可宣称内容

- 没有多进程/多线程并发压力测试；可宣称“设计覆盖并发场景 + 端到端功能验证通过”，
  不要宣称“并发压测通过”；
- 冻结目标带内容哈希，accept 会拒绝目标变化；尚未做多进程并发压力测试；
- 跨进程锁基于 POSIX flock，仅适用于 macOS/Linux；
- 未运行 Swift 构建、pytest、Ruff 或 mypy（本次任务未请求）；网络门控为代码级核查，
  未做 GUI 级抓包复测；
- OCR 输出是候选，不是数学 ground truth；原 PDF 始终是公式权威证据；
- 复杂表格恢复与无法探索出可靠 region 的公式仍不送整页 OCR。

## 面试前快速检查清单

- 能画出 `pdf_sha256/fingerprint → revisions/<id> → current.json` 的目录结构；
- 能解释 staging + os.replace + fsync 为什么避免撕裂读；
- 能说清共享锁和独占锁各用于哪些操作；
- 能准确说明 asyncio.Lock 的实例边界和 flock 的跨进程边界；
- 能解释 recognize 和 accept 为什么分开；
- 能主动说出 last-writer-wins、无 CAS、无并发压力测试三个边界；
- 能报出验证证据：四轮 12 断言 ALL PASS、去哈希化四轮 ALL PASS、真实公式闭环。
