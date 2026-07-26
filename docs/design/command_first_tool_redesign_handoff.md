# Command-first 工具重设计交接

更新日期：2026-07-24

## 用户目标

Paper Copilot 借鉴 Codex 的工具设计：以少量通用原语为主，由模型组合完成复杂任务，
避免为“分类论文”“删除重复论文”“详细解析论文”等场景分别增加专属工具。

不使用 Paper Copilot MCP 作为内部 Agent 工具，也不依赖多模态能力。

## 已确认的模型工具表面

模型只应看到四个工具：

1. `library_exec`
   - 固定工作目录为用户论文库。
   - 负责只读 Shell 操作，例如统计 PDF、列文件、哈希查重和批量分析目录。
   - 使用 macOS `sandbox-exec`；禁止网络、论文库写入和库外读取。
   - 清理用户环境变量，限制执行时间、CPU、临时文件和输出。

2. `library_edit`
   - 负责所有论文库写操作。
   - 支持 `mkdir`、`copy`、`move`、`trash`、`restore` 和
     `write_document`。
   - `move` 同时用于重命名 PDF。
   - `write_document` 接受完整 Markdown 新文档，不做章节级编辑。
   - 写操作进入既有审批状态机；Markdown 写入展示 unified diff，并绑定输入、
     文件快照、文件哈希和修改预览。

3. `paper_search`
   - 统一原来的全库搜索、单篇查询和多篇查询。
   - 不指定 `papers`：全库浏览或语义发现。
   - 指定一篇：单篇原文证据检索。
   - 指定多篇：候选论文排序 → 单篇局部召回 → 章节多样化证据。
   - 全库结果使用 `page_size + cursor` 分页；用户要求“所有”时必须调用到
     `next_cursor = null`，不能把单页 20 篇当成总结果。

4. `read_paper`
   - 处理尚未入库的本地 PDF。
   - 执行章节提取、结构化字段提取、分块、embedding 和索引写入。
   - 入库后再由 `paper_search` 回答内容问题。

旧的 `search_papers`、`query_paper`、`query_papers`、`compare_papers`、
`find_related_papers`、Composer 工具、`library_files` 和 `notes_patch` 实现暂时保留，
但不再出现在模型工具列表中。Agent 异步调度会拒绝未公开的旧工具名称。

## 典型任务路由

- “当前目录有多少篇论文”
  - `library_exec`
- “列出所有论文标题”
  - 文件级标题可由 `library_exec` 获取；结构化完整标题由 `paper_search` 分页获取。
- “列出 XXX 方向的所有论文”
  - `paper_search`，持续分页到 `next_cursor = null`。
  - 内容级结论只能覆盖已索引论文；未索引 PDF 必须明确作为缺口。
- “删除重复论文”
  - `library_exec` 使用 SHA-256 找完全相同文件。
  - 同标题但不同 PDF 版本可用 `paper_search` 辅助核对。
  - `library_edit.trash` 将多余副本移入 macOS 废纸篓并请求审批。
- “详细解析 XXXX 论文”
  - 已索引：`paper_search` 限定一篇并围绕不同问题多轮取证。
  - 未索引：`read_paper` 后再调用 `paper_search`。
- “结合讨论做笔记”
  - `library_exec` 读取既有 Markdown。
  - 模型生成完整新文档。
  - `library_edit.write_document` 展示 diff，审批后原子写入。

## 数据事实

- `fields.db` 的结构化字段保存完整论文标题：`meta.title`。
- `embeddings.db` 的 `chunks` 表不重复保存标题，只保存：
  `paper_id`、`ord`、`section`、页码和 `text`。
- 检索结果通过 `paper_id` 从 `fields.db` 取得完整标题。
- 缺少对应 fields row 的 chunk 会被视为陈旧索引并跳过。

## 当前问题：短论文与长论文

用户刚提出：

> 对于短论文和长论文处理方式有区别吗

已形成但尚未实现的结论：

- 不新增“短论文工具”和“长论文工具”，仍由 `paper_search` 统一处理。
- 是否为长论文应根据提取后的全文 token 数、页数、章节数、chunk 数和当前模型可用
  上下文判断，而不是根据“博士论文”等文档类型判断。
- 全文能安全放入工作上下文的短论文，应优先直接读取有界全文，减少 RAG 遗漏跨章节
  关系的风险。
- 超出全文预算的长论文，应采用目录/结构化摘要 → 相关章节 → chunk 的分层策略。
- 多篇长论文应采用论文 → 章节 → chunk 的三级召回。

当前实现尚未真正做到长度自适应：已索引单篇论文仍主要使用 chunk RAG。下一步应在
`paper_search` 内部加入 `auto` 策略，而不是新增模型工具。

建议下一步先确认并设计：

1. 在哪里持久化 `page_count`、全文字符/token 估计、章节数和 chunk 数。
2. 全文直读的动态 token 预算如何从模型工作上下文中计算。
3. 全文返回仍需保持引用定位，不能只返回无来源的大段文本。
4. 长论文的章节级粗排是否复用现有 section/chunk 元数据，避免新增 embedding 类型。
5. 多篇论文场景如何限制总全文预算并保持每篇覆盖公平。

## 当前工作区修改

本轮尚未提交的相关文件包括：

- `src/paper_copilot/agents/library_exec_tool.py`
- `src/paper_copilot/agents/library_edit_tool.py`
- `src/paper_copilot/agents/notes_patch_tool.py`
- `src/paper_copilot/agents/paper_copilot.py`
- `src/paper_copilot/agents/tool_security.py`
- `src/paper_copilot/knowledge/hybrid_search.py`
- `apps/macos/PaperCopilot/API/Models.swift`
- `apps/macos/PaperCopilot/Views/ConversationDetailView.swift`
- `TASKS.md`

## 验证状态

尚未运行：

- 手动真实论文流程
- 命令沙箱攻击测试
- Ruff
- mypy
- pytest
- macOS 客户端构建
- 真实论文检索评估

尚未 commit 或 push。

根据仓库 `AGENTS.md`，后续开始长度自适应这一非平凡改动前，应先读 `TASKS.md`、
`ARCHITECTURE.md` 和相关模块，提出具体计划并等待确认；除非用户明确要求，否则不要
主动运行或新增验证测试。
