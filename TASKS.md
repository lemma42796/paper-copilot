# TASKS

> 本文件保存所有未完成任务，可以同时存在多个任务；已完成任务删除，未完成任务保留或
> 更新。实验记录不得写入这里；历史实验入口统一见
> [实验索引](docs/design/experiment_index.md)。工程规则见 [AGENTS.md](AGENTS.md)，
> 当前接力状态见 [STATUS.md](STATUS.md)，当前架构见
> [ARCHITECTURE.md](ARCHITECTURE.md)。

更新于 2026-08-05。

## 未完成任务

### 按需论文缓存与可选本地公式 OCR

- 主客户端不得包含任何 Paddle 组件或公式模型权重。
- 客户端启动和 Agent 预检不得批量生成论文正文缓存；manifest 只建立授权论文清单。
- 不保存论文结构化字段数据库、全文索引、向量索引或 embeddings。
- 启动后的完整 inventory 扫描成功时清理没有现存 PDF 哈希对应的缓存；失败时不删除。
- `paper-cache page/search` 必须用 PDF 相对路径，并在读取前校验当前 PDF SHA-256。
- 模型只对当前任务需要的论文调用 `paper-cache ensure`，按需生成内容寻址 `layout.txt`。
- TXT 中包含 Unicode 替换字符或私用区字形的行生成稳定公式 OCR
  `cache_slot`。
- 纯文本模型在悬浮提示中说明可选能力，但悬浮、选择模型和启动应用均不得联网。
- 用户仅在设置中点击下载后解析 Formula OCR manifest；Helper Runtime 与权重按内容哈希
  分别复用或下载，全部校验通过后才激活组件。
- `recognize_formula` 仅在纯文本模型、论文库可用且 helper 已安装时暴露。
- 只有任务确实需要理解或引用某个乱码公式时才调用 `recognize_formula`，不得仅因发现乱码
  就识别；`recognize` 只返回候选，模型检查后调用 `accept` 才把 LaTeX 写入新 revision、
  原子发布为 current，并自动删除同一缓存键下的旧 revision。
- [ ] 下一步：在客户端完成真实乱码公式 `recognize`/`accept` 回填与跨会话命中
  （`recognize` 已用真实 Helper 直接调用验证干净候选；`accept` 与跨会话尚未在客户端
  执行），随后验证工具暴露矩阵、按需缓存一致性（新增/删除/查询/替换 PDF）、未请求论文
  不生成缓存、主客户端无 Paddle 静态检查与未点击下载无网络行为。
- 已完成：Helper 重建（含受限异常因果输出与 pypdfium2 收集）、真实论文公式推理、
  ad-hoc Release `formula-ocr-v1` 发布、App 内安装与模型复用闭环、工具超时 45 → 120 秒。
  公式定位逻辑修复（`_locate_numbered_formula` 几何裁剪，单栏居中公式 OCR 乱码问题
  解决，recognize 直接调用验证干净 LaTeX）。正式发布仍需 Developer ID 签名与公证。
