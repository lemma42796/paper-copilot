# Runtime 页面证据与最终输出合同 Codex 源码映射

状态：按 Codex 默认行为修订；论文专用结束拦截已删除
日期：2026-07-29
Codex source ref：`fe01054a28fa4bd04716d9ceadb410f2443a50ce`
Codex worktree：`/Users/a123/Documents/agent学习/codex`

## 1. 目标与范围

冻结 Query 1 的旧运行曾引入论文专用完成校验。随后对固定 Codex 源码重新核对，确认
Codex 默认并不校验论文覆盖率或论文页码引用；它提供的是可选 Stop hook 和前端链接
渲染。因此当前实现调整为：

1. 用独立 `read_page` 取代模型通过 `library_exec` 调用 `paper-cache` broker；
2. `read_page` 和 `inspect_page` 成功后由 Runtime 自动登记页证据；
3. 保留 append-only 页面证据，供审计、恢复和范围变更使用；
4. 删除论文专用 `end_turn` 校验、自动重答和 Incomplete 替换；
5. 由模型直接输出安全的应用内 Markdown 链接，Runtime 引用层不改写最终答案；
6. 删除模型可见 `paper_set`。

修订后的冻结 Query 1 已通过。后续曾增加最小 `update_research_scope`，但 Codex
四轮基线没有范围记忆失败，Paper Copilot 实跑又确认模型可能不调用该工具。该机制
现已从工具表面、恢复和上下文注入中删除；既有 session 事件只保留为历史记录。

Trace 不属于本 slice。当前产物的 session 与 trace 均包含相同的 113 个 started call
ID，其中 99 completed、14 failed。

## 2. Codex 源码结论

| 需求 | Codex source | Codex 机制 | 结论 |
|---|---|---|---|
| 工具尝试审计 | `core/src/tools/registry.rs::dispatch_any_with_terminal_outcome`、`tool_dispatch_trace.rs` | dispatch 前启动 trace，early failure 记录 failed | 当前已对齐，不修改 |
| 原始请求持久化 | `core/src/stream_events_utils.rs::handle_output_item_done`、`session/mod.rs::record_conversation_items` | 执行前保存 call，结果继续追加历史 | 当前已对齐 |
| 参数失败反馈 | `tools/handlers/mod.rs::parse_arguments`、`tools/parallel.rs::failure_response` | 失败 output 保留 call ID，模型可修正重试 | 当前已对齐 |
| 工具成功后处理 | `tools/registry.rs` PostToolUse 路径 | 受信任生命周期处理后再把结果交回模型 | 必要适配：持久化结果后登记页证据 |
| 完成前阻断 | `session/turn.rs::run_turn`、`hook_runtime.rs::run_turn_stop_hooks`、`hooks/src/events/stop.rs` | Stop hook 可选；没有 handler 就不阻断 | 通用 loop 保留默认关闭的 Stop hook，产品默认不配置 |
| 页级论文证据 | 固定 Codex ref 无 PDF cache/page artifact 对象 | 无对应机制 | 增加最小 append-only evidence fact |
| 论文集合 coverage | 固定 Codex ref 无论文集合语义 | 无对应机制 | 不增加结束拦截 |
| 跨轮次论文排除 | 固定 Codex ref 依赖同一 session 历史，没有论文范围工具 | 无基线失败 | 不增加产品特定工具，使用 conversation history |
| Markdown 引用展示 | `tui/src/markdown_render.rs` | 标准 Markdown 链接由目标地址解析和展示 | 使用安全应用链接，显示论文标题和页码 |

Paper Copilot 不再把 JSON schema 或页面证据当成默认的最终回答校验器。

## 3. `read_page`

新增模型工具：

```yaml
name: read_page
input:
  pdf_sha256: <64 lowercase hex>
  page: <positive integer>
output:
  status: ok
  pdf_sha256: <64 lowercase hex>
  page: <positive integer>
  text: <bounded page text>
  evidence:
    source_kind: cached_text_page
    artifact_sha256: <64 lowercase hex>
    extractor_fingerprint: <string>
    cache_revision_id: <string>
```

固定边界：

- 只解析本 attempt 的受信任 `research_cache_index`；
- 不接受文件名、相对路径、宿主绝对路径、短 hash 或任意 cache path；
- PDF SHA-256 必须匹配授权论文和 current cache revision；
- 一次只读取一页，页码越界、缓存 stale/partial 或 artifact 校验失败时明确失败；
- 页文本按既有工具输出预算截断，并明确返回 truncation metadata；
- 不执行 cache ensure、全文提取、搜索、OCR、视觉渲染或写操作；
- 成功结果在 trace attributes 携带不含正文的 `page_evidence`；
- `library_exec` 明确拒绝 `paper-cache status/ensure/page`，不提供 alias 或静默回退。

Runtime preflight 继续负责预算内 PDF 的 cache ensure 和 index 注入，因此删除 broker
不会删除内容寻址缓存能力。

## 4. Runtime evidence ledger

新增 `agents/research_evidence.py`，用 Pydantic 定义跨 session 边界的
`research_evidence.page_observed` application event：

- schema version；
- source tool call ID；
- source kind：`cached_text_page | pdf_page_render`；
- 完整 PDF SHA-256 和正整数 PDF 页码；
- artifact SHA-256；
- 文本页的 extractor fingerprint、cache revision ID；
- 视觉页的可选 region、render SHA-256。

事件不保存页文本、图片 data URL、PDF 内容或宿主绝对路径。

只有两个成功路径可以产生事实：

1. `read_page` 成功把页文本返回给模型；
2. `inspect_page` 成功把页面或 region 图像交给模型。

`rg`、`awk`、`sed`、preflight TXT、模型文本、历史 `record_evidence` 和工具内部存在性
检查都不能产生事实。

`run_agent_loop` 增加可选 `on_tool_result_persisted` 回调，顺序固定为：

```text
dispatch
→ append tool result
→ validate trusted page_evidence
→ append page_observed event
→ expose result to next model turn
```

若进程在 tool result 与 evidence event 之间中断，只会形成 incomplete，不会虚假
complete。Resume 从 recovery source session 顺序重放 evidence events。

## 5. 论文范围

本 slice 不建立新的模型集合工具。Runtime 在研究 attempt 启动时将
`research_cache_index` 中成功准备的全部论文冻结为 active set：

- 成员使用完整 PDF SHA-256；
- 保存 cache revision 和 extractor fingerprint 快照；
- preflight 失败或预算截断必须显式进入 incomplete 原因；
- observed-page fact 绑定当前缓存快照，供审计和恢复使用；
- stale、旧 `paper_set` evidence 和 approximate page 不写入该 ledger。

该定义适用于 Query 1 的“当前目录全部论文”任务。后续轮次继续使用同一 conversation
的历史消息表达范围约束，不从既有 `research_scope` 历史事件重建受信任状态。

## 6. Stop hook 与引用链接

通用 `agents/loop.py` 暴露默认关闭的 Stop hook。请求只包含
`stop_hook_active` 和 `last_assistant_message`；handler 可以允许结束，也可以给出原因
并让同一任务继续。若 handler 请求阻断却没有原因，Runtime 忽略该无效结果并结束。
Paper Copilot 当前不配置 handler，所以不存在论文引用检查和自动重答。

Runtime 在 `research_cache_index` 为每篇论文提供本次运行唯一的 `citation_base`。
模型直接生成标准 Markdown 链接，例如
`[《论文题目》第 4 页](paper-copilot://open?ref=324a2128&page=4)`。Runtime 引用层不
解析、验证、替换或清理最终答案，写入 session report、Chat result 和 UI 的引用处理后
文本完全相同。

Chat result 另行携带 Runtime 生成的 `citation ref -> 授权逻辑 locator` 映射。macOS
只通过该可信映射解析模型链接，再执行授权目录边界、PDF 扩展名和文件存在性校验。
未知 ref、无效页码或缺失文件直接丢弃点击操作，不阻断回答或触发模型重试。

## 7. 质量摘要与兼容

- 删除依赖自定义引用解析的 `heuristic_v3_unvalidated` 和 `research_citations`；
- final payload 保存 `citation_targets`，不包含宿主绝对路径；
- 新运行的评测记录页面证据数，引用数和引用 coverage 留空；旧 session 的 quality 字段
  继续兼容读取；
- 旧 `paper_set` application events 继续可重放，但不计为有效 evidence；
- 模型工具表面删除 `paper_set`，Runtime 对调用返回 unsupported；
- `termination_reason` 保持现有值，避免修改 Swift、API 和 MCP transport；
- 旧 `paper_set` 代码与事件 schema 暂不删除，服务历史 session 兼容。

## 8. 实现范围与 Definition of Done

预计修改：

- `agents/loop.py`
- `agents/paper_copilot.py`
- `agents/library_exec_tool.py`
- `agents/inspect_page_tool.py`
- `agents/paper_set_tool.py`
- 新增 `agents/read_page_tool.py`
- 新增 `agents/research_evidence.py`
- research Skill、工具注册和相关状态文档

不修改 API/MCP transport、数据库 schema、PDF cache 格式、模型、依赖或 trace
lifecycle。

完成条件：

- 模型工具表面不含 `paper_set`，`library_exec` 不接受 `paper-cache`；
- `read_page` 只读取 active index 中完整 SHA-256 对应的一页；
- 只有成功 `read_page`/`inspect_page` 产生 observed-page fact；
- recovery 可重建相同 ledger 和 active set；
- 没有 Stop handler 时，模型 `end_turn` 直接结束；
- 可选 Stop handler 的 block 原因会作为 continuation 继续同一任务；
- 模型直接输出可点击论文页链接，Runtime 不改写答案；
- 无效引用不拦截，客户端只解析本次结果中的可信 ref；
- 不新增依赖、模型、LLM call site、网络、OCR 或 embedding；
- 冻结 Query 1 重跑时报告工具调用、页面证据、coverage、引用、LLM 次数、token、费用、
  耗时和所有 failure/partial/unverifiable 字段。

此前 Query 1 和 Query 2 是在论文专用拦截存在时运行，不能与修订后的实现混作同一组
正式评测。若继续四轮对比，应从 Query 1 重新开始记录。
