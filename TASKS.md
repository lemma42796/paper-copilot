# TASKS

> 本文件保存所有未完成任务，可以同时存在多个任务；已完成任务删除，未完成任务保留或
> 更新。实验记录不得写入这里；历史实验入口统一见
> [实验索引](docs/design/experiment_index.md)。工程规则见 [AGENTS.md](AGENTS.md)，
> 当前接力状态见 [STATUS.md](STATUS.md)，当前架构见
> [ARCHITECTURE.md](ARCHITECTURE.md)。

更新于 2026-08-06。

## 未完成任务

### 按需论文缓存与可选本地公式 OCR

- 主客户端不得包含任何 Paddle 组件或公式模型权重。
- 客户端启动和 Agent 预检不得批量生成论文正文缓存；manifest 只建立授权论文清单。
- 不保存论文结构化字段数据库、全文索引、向量索引或 embeddings。
- 启动后的完整 inventory 扫描成功时清理没有现存 PDF 哈希对应的缓存；失败时不删除。
- 模型可见命令为 `paper read/search`（内部按需生成内容寻址 `layout.txt`），必须用 PDF
  相对路径，并在读取前由 agent 自动校验当前 PDF SHA-256。
- 模型只对当前任务需要的论文发起 `paper read/search`；缓存由 agent 按需自动生成，模型
  不接触缓存键、哈希或 revision。
- TXT 中包含 Unicode 替换字符或私用区字形的行生成稳定公式 OCR
  `cache_slot`。
- 纯文本模型在悬浮提示中说明可选能力，但悬浮、选择模型和启动应用均不得联网。
- 用户仅在设置中点击下载后解析 Formula OCR manifest；Helper Runtime 与权重按内容哈希
  分别复用或下载，全部校验通过后才激活组件。
- `recognize_formula` 仅在纯文本模型、论文库可用且 helper 已安装时暴露。
- 只有任务确实需要理解或引用某个乱码公式时才调用 `recognize_formula`，不得仅因发现乱码
  就识别；`recognize` 只返回候选，模型检查后调用 `accept` 才把 LaTeX 写入新 revision、
  原子发布为 current，并自动删除同一缓存键下的旧 revision。
- 已完成：`paper read/search` 模型可见输出已去哈希化（`paper read` 只返回
  `page`/`text`，`paper search` 只返回 `query`/`matches`/`truncated`，不再含
  `cache_ref`、revision_id、paper_id 或 artifact_sha256）；客户端一致性四轮重跑
  ALL PASS（2026-08-06，deepseek-v4-flash，会话
  `conversation-new-surface-20260806183148`，成本约 ¥0.054）。
- 已完成：Helper 重建（含受限异常因果输出与 pypdfium2 收集）、真实论文公式推理、
  ad-hoc Release `formula-ocr-v1` 发布、App 内安装与模型复用闭环、工具超时 45 → 120 秒。
  公式定位逻辑修复（`_locate_numbered_formula` 几何裁剪，单栏居中公式 OCR 乱码问题
  解决，recognize 直接调用验证干净 LaTeX）；客户端真实乱码公式 `recognize`/`accept`
  回填与跨会话命中（2026-08-05：accept 成功发布修复 revision，后续会话直接命中
  recognized 标记不再 OCR；该修复随后随缓存一致性清理删除，机制已验证）；工具暴露
  矩阵四场景复跑 PASS；按需缓存一致性（新增/查询/替换/删除 PDF）客户端真机验证
  ALL PASS，删除会连外层空目录一起清掉；缓存从模型可见面隐藏
  （`paper read/search`，SKILL v22）；新命令面客户端一致性重跑 ALL PASS
  （2026-08-06，deepseek-v4-flash，会话 `conversation-new-surface-20260806181858`，
  四轮成本约 ¥0.08，含未请求论文不生成缓存磁盘复核）；主客户端静态依赖与网络门控
  核查 PASS（import 图无 paddle、打包 App 无 Paddle 文件；联网仅限设置下载按钮，
  运行时 `network=denied`）；`docs/design/` 与 `ARCHITECTURE.md` 中旧 `paper-cache`
  文案已同步为 `paper read/search`；模型可见 read/search 输出去哈希化并四轮复跑
  ALL PASS（2026-08-06，会话 `conversation-new-surface-20260806183148`，约 ¥0.054）。
