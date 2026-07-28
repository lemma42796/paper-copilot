# Runtime 页面证据与最终输出合同 Codex 源码映射

状态：已按 `read_page` 方向实施并完成定向验证；待冻结 Query 1 验收
日期：2026-07-28
Codex source ref：`61a44880a85d2fd0d8770908dea5733495e571c8`
Codex worktree：`/Users/a123/Documents/agent学习/codex`

## 1. 目标与范围

冻结 Query 1 证明当前模型可以在未读取 citation-grade 页面时使 `paper_set` complete，
并以短 hash 结束任务。本 bounded slice 只修复 Query 1 的确定性合同：

1. 用独立 `read_page` 取代模型通过 `library_exec` 调用 `paper-cache` broker；
2. `read_page` 和 `inspect_page` 成功后由 Runtime 自动登记页证据；
3. Query 1 active set 固定为 Runtime preflight 的论文预算；
4. Runtime 接受 `end_turn` 前校验完整引用和 active-set coverage；
5. 删除模型可见 `paper_set`。

Query 2–4 的自然语言排除和派生集合不属于本 slice。删除 `paper_set` 后，Runtime 没有
确定性来源自动理解集合变化；在增加经确认的结构化接口前不得用语义猜测补齐。因此
Query 2–4 继续暂停。

Trace 不属于本 slice。当前产物的 session 与 trace 均包含相同的 113 个 started call
ID，其中 99 completed、14 failed。

## 2. Codex 源码结论

| 需求 | Codex source | Codex 机制 | 结论 |
|---|---|---|---|
| 工具尝试审计 | `core/src/tools/registry.rs::dispatch_any_with_terminal_outcome`、`tool_dispatch_trace.rs` | dispatch 前启动 trace，early failure 记录 failed | 当前已对齐，不修改 |
| 原始请求持久化 | `core/src/stream_events_utils.rs::handle_output_item_done`、`session/mod.rs::record_conversation_items` | 执行前保存 call，结果继续追加历史 | 当前已对齐 |
| 参数失败反馈 | `tools/handlers/mod.rs::parse_arguments`、`tools/parallel.rs::failure_response` | 失败 output 保留 call ID，模型可修正重试 | 当前已对齐 |
| 工具成功后处理 | `tools/registry.rs` PostToolUse 路径 | 受信任生命周期处理后再把结果交回模型 | 必要适配：持久化结果后登记页证据 |
| 完成前阻断 | `session/turn.rs::run_turn`、`hook_runtime.rs::run_turn_stop_hooks`、`hooks/src/events/stop.rs` | Stop hook 可 block、注入 continuation 并继续同一 turn | 采用结构，增加默认关闭的 end-turn validator |
| 页级论文证据 | 固定 Codex ref 无 PDF cache/page artifact 对象 | 无对应机制 | 增加最小 append-only evidence fact |
| 论文集合 coverage | 固定 Codex ref 无论文集合语义 | 无对应机制 | Query 1 只使用 preflight set，不猜测派生集合 |
| Markdown 引用合同 | 固定 Codex ref 无 SHA-256/page 引用语义 | 无对应机制 | 增加确定性 validator |

Codex 的 JSON output schema 只能保证结构，不能证明 Markdown 引用对应已观察页面，因此
不用于替代 Runtime validator。

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

## 5. Query 1 active set

本 slice 不建立新的模型集合工具。Runtime 在研究 attempt 启动时将
`research_cache_index` 中成功准备的全部论文冻结为 active set：

- 成员使用完整 PDF SHA-256；
- 保存 cache revision 和 extractor fingerprint 快照；
- preflight 失败或预算截断必须显式进入 incomplete 原因；
- 每个成员至少有一条匹配当前快照的 observed-page fact 才算 evidence covered；
- stale、旧 `paper_set` evidence 和 approximate page 不计入。

该定义适用于 Query 1 的“当前目录全部论文”任务。它不声称能表达后续轮次的排除、
optional/required 或派生集合。恢复 Query 2–4 前必须单独解决结构化 scope transition，
不能从模型自然语言或最终答案反推 active set。

## 6. End-turn validator

通用 `agents/loop.py` 增加默认关闭的 `validate_end_turn` 回调；通用 loop 不导入 PDF、
evidence 或集合类型。模型给出候选 `end_turn` 时：

1. 候选 assistant message继续追加到 session；
2. 应用 validator 检查 evidence 与引用；
3. 通过后才产生 `Terminated(reason="end_turn")`；
4. 未通过时追加有界 issue codes 和修复要求，继续既有 loop。

稳定 issue codes：

- `active_set_preflight_incomplete`
- `active_set_evidence_incomplete`
- `active_set_stale`
- `citation_id_not_full_sha256`
- `citation_not_observed`
- `citation_paper_coverage_incomplete`

有效引用格式为 `[<64-lowercase-hex>:page[<positive-int>]]`。每条引用必须命中 ledger；
Query 1 最终报告必须覆盖 active set 的每个成员。Validator 不判断自然语言 entailment。
任何形似 `[…:page[n]]` 但不满足完整格式的候选都必须拒绝，包括带省略号的短 hash。
验证通过后，Runtime 将用户可见文本中的规范引用渲染为 `《论文题目》第 N 页`；原始
完整引用继续保存在结构化 `evidence_refs`、session 和 trace 中。

失败 continuation 不新增 LLM call site，但可能增加既有 loop turn，仍受总预算、
deadline、context limit 和用户中断约束。若终止前始终未通过，Runtime 不发布最后一个
无效草稿为成功报告，只输出有界 `Incomplete` 结果和 validation issues。

## 7. 质量摘要与兼容

- `heuristic_v2` 只统计 validator 确认的完整引用；
- final payload 保存 validator version、passed、issues 和 active-set coverage；
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

不修改 SwiftUI、API/MCP transport、数据库 schema、PDF cache 格式、模型、依赖、
trace lifecycle、Query 2–4 或旧实现删除范围。

完成条件：

- 模型工具表面不含 `paper_set`，`library_exec` 不接受 `paper-cache`；
- `read_page` 只读取 active index 中完整 SHA-256 对应的一页；
- 只有成功 `read_page`/`inspect_page` 产生 observed-page fact；
- recovery 可重建相同 ledger 和 active set；
- approximate page、搜索命中和旧 evidence 不能完成 coverage；
- 短 hash、未观察页面和未覆盖 active set 的报告不能成功结束；
- 合法完整引用和非论文直接回答按各自策略通过；
- `heuristic_v2` 不统计无效引用；
- 不新增依赖、模型、LLM call site、网络、OCR 或 embedding；
- 冻结 Query 1 重跑时报告工具调用、页面证据、coverage、引用、LLM 次数、token、费用、
  耗时和所有 failure/partial/unverifiable 字段。

代码已按本映射实施。定向验证已覆盖工具表面、broker 拒绝、真实页读取、evidence
recovery、引用 validator、end-turn continuation、预算降级和非论文直答。按照仓库规则，
冻结 Query 1 重跑仍需单独授权。
