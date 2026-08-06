# `paper_set` Codex 源码映射

状态：历史接口映射；模型可见 `paper_set` 已移除，代码与事件仅保留兼容
日期：2026-07-28
Codex source ref：`61a44880a85d2fd0d8770908dea5733495e571c8`  
Codex worktree：当前固定为 `/Users/a123/Documents/agent学习/codex`；Slice 5 审计时
使用该 commit 的 GitHub archive，无本地修改

## 1. 目的

本文按仓库的 Codex-first 原则，逐项核对 Paper Copilot `paper_set` 与固定 Codex
源码。分类只有三种：

- **直接采用**：Codex 已有对应机制，Paper Copilot 保持其结构和语义；
- **必要适配**：Codex 有基础机制，但论文集合或本地授权边界要求收窄；
- **Codex 缺失**：固定 source ref 中没有论文领域对应能力，只增加最小专用设计。

未列入本文的自定义机制不得进入 Slice 5。

本文不再作为新接口设计依据。不可变集合、revision、stale 和 append-only 恢复语义仍
用于兼容当前代码与历史 session；新的证据与 active-set 设计以
`runtime_research_evidence_codex_source_mapping.md` 为准。

## 2. 源码映射

| 需求 | Codex source | Codex 机制 | Paper Copilot 分类 | 结论 |
|---|---|---|---|---|
| 追加事实记录 | `protocol/src/protocol.rs::RolloutItem`、`rollout/src/recorder.rs` | rollout 以带类型的 JSONL item 追加保存，恢复读取原始 item，不反向覆盖历史 | 直接采用 + 必要适配 | session 增加通用 `application_event`，`paper_set` 只追加 created、derived、evidence_recorded 和 completed 事件 |
| 恢复重建 | `core/src/session/mod.rs::apply_rollout_reconstruction`、`core/src/session/rollout_reconstruction.rs` | 保持 rollout 不变，按记录重放并安装派生状态；compaction checkpoint 和后续 item 分离 | 直接采用 + 必要适配 | 从 recovery source session 到当前 session 顺序重放 `paper_set` 事件；不把派生集合写入 runtime_state 或 compaction summary |
| 派生状态快照 | `protocol/src/protocol.rs::WorldStateItem`、`core/src/session/rollout_reconstruction.rs` | full/patch item 建立可重建 world-state baseline | 必要适配 | `paper_set` 不复制通用 world-state patch；集合 created/derived 事件保存完整不可变成员快照，evidence 事件只追加覆盖事实 |
| 损坏记录处理 | `rollout/src/recorder.rs::load_rollout_items`、`core/src/session/rollout_reconstruction.rs` | loader/reducer 在恢复边界校验记录形状并以完整前缀重建 | 直接采用 + 必要适配 | 复用现有 torn-tail 处理；`paper_set` reducer 额外校验集合 ID、父子分区、PDF/cache revision 和 evidence ref 形状 |
| 论文集合 | 固定 Codex source ref 无论文集合、PDF revision 或 evidence coverage | 无对应领域机制 | Codex 缺失 | 增加 create、derive、record_evidence、status 四个确定性操作 |
| revision 与 stale | 固定 Codex source ref 无授权论文库或内容寻址 PDF cache | 无对应领域机制 | Codex 缺失 | 成员快照绑定 PDF SHA-256、兼容的 cache ref 和授权相对 locator；PDF 缺失/变化或 current cache ref 变化时返回 stale |
| 覆盖完成性 | 固定 Codex source ref 无逐论文证据覆盖语义 | 无对应领域机制 | Codex 缺失 | 当前实现只证明每篇成员至少登记一个可解析到快照 cache revision 的页码且没有 stale；Query 1 已证明这不足以表示模型读取过 citation-grade 页面，不能作为正式 coverage 合同 |

## 3. Slice 5 固定边界

- 输入只接受授权论文库中可唯一解析的 12 位旧 ID 或完整 PDF SHA-256，输出统一使用
  完整 PDF SHA-256；
- `ingest_revision` 在当前无独立 v2 ingest store 的条件下等于原始 PDF SHA-256；
  `cache_ref` 单独保存 extractor fingerprint 和 revision ID；
- create 只读取已有 cache revision；cache 不存在时由 `paper read/search` 首次访问
  自动按需生成，不在 `paper_set` 内执行 PDF 提取；
- derive 保存父集合、完整成员快照、被排除成员和排除原因，不修改父集合，也不继承父集合
  的 evidence coverage；
- evidence ref 初版只接受 `[<pdf_sha256>:page[<page>]]`，并通过快照 cache artifact
  验证页码和 revision；
- status 返回 expected、completed、missing、stale 和 complete；历史 completed 事件
  不覆盖当前 stale 检查；
- recovery source 必须仍位于同一应用 session 根，不能通过被篡改的 session 记录读取
  任意路径；
- 当前只注册内部 schema 和 dispatcher，实现不加入模型可见工具列表；公开切换、
  Skill 更新和 macOS 兼容仍属于 Slice 6；
- 不加入搜索、RAG、PDF 提取、回答生成、TTL 回收、新依赖或旧工具删除。

## 4. Query 1 验收后的已知缺口

简化重构后的冻结 Query 1 没有调用 `paper read` 或 `inspect_page`，模型明确使用
approximate pages，却仍通过 14 次 `record_evidence` 得到 14/14 coverage complete。
现有 `_validate_evidence_ref` 会读取 cache page 以确认页码和 revision 可用，但不会证明
该页内容已经作为 citation-grade evidence 返回给模型，也没有把 evidence 绑定到先前
受信任页面读取产生的 artifact。

因此 Slice 5 的不可变集合、revision、stale 和恢复语义仍成立，但“coverage complete”
目前只能解释为登记完整性，不能解释为研究证据完整性。下一 bounded slice 必须先完成
新的 Codex-first 源码映射，再让 Runtime 持有并校验页面证据事实。模型可见
`paper_set` 已从模型表面删除；旧事件保持可重放，但不再作为 citation-grade coverage
真源。
