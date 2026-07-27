# `paper_set` Codex 源码映射

状态：Slice 5 实现完成
日期：2026-07-27  
Codex source ref：`61a44880a85d2fd0d8770908dea5733495e571c8`  
Codex worktree：审计时使用该 commit 的 GitHub archive，无本地修改

## 1. 目的

本文按仓库的 Codex-first 原则，逐项核对 Paper Copilot `paper_set` 与固定 Codex
源码。分类只有三种：

- **直接采用**：Codex 已有对应机制，Paper Copilot 保持其结构和语义；
- **必要适配**：Codex 有基础机制，但论文集合或本地授权边界要求收窄；
- **Codex 缺失**：固定 source ref 中没有论文领域对应能力，只增加最小专用设计。

未列入本文的自定义机制不得进入 Slice 5。

## 2. 源码映射

| 需求 | Codex source | Codex 机制 | Paper Copilot 分类 | 结论 |
|---|---|---|---|---|
| 追加事实记录 | `protocol/src/protocol.rs::RolloutItem`、`rollout/src/recorder.rs` | rollout 以带类型的 JSONL item 追加保存，恢复读取原始 item，不反向覆盖历史 | 直接采用 + 必要适配 | session 增加通用 `application_event`，`paper_set` 只追加 created、derived、evidence_recorded 和 completed 事件 |
| 恢复重建 | `core/src/session/mod.rs::apply_rollout_reconstruction`、`core/src/session/rollout_reconstruction.rs` | 保持 rollout 不变，按记录重放并安装派生状态；compaction checkpoint 和后续 item 分离 | 直接采用 + 必要适配 | 从 recovery source session 到当前 session 顺序重放 `paper_set` 事件；不把派生集合写入 runtime_state 或 compaction summary |
| 派生状态快照 | `protocol/src/protocol.rs::WorldStateItem`、`core/src/session/rollout_reconstruction.rs` | full/patch item 建立可重建 world-state baseline | 必要适配 | `paper_set` 不复制通用 world-state patch；集合 created/derived 事件保存完整不可变成员快照，evidence 事件只追加覆盖事实 |
| 损坏记录处理 | `rollout/src/recorder.rs::load_rollout_items`、`core/src/session/rollout_reconstruction.rs` | loader/reducer 在恢复边界校验记录形状并以完整前缀重建 | 直接采用 + 必要适配 | 复用现有 torn-tail 处理；`paper_set` reducer 额外校验集合 ID、父子分区、PDF/cache revision 和 evidence ref 形状 |
| 论文集合 | 固定 Codex source ref 无论文集合、PDF revision 或 evidence coverage | 无对应领域机制 | Codex 缺失 | 增加 create、derive、record_evidence、status 四个确定性操作 |
| revision 与 stale | 固定 Codex source ref 无授权论文库或内容寻址 PDF cache | 无对应领域机制 | Codex 缺失 | 成员快照绑定 PDF SHA-256、兼容的 cache ref 和授权相对 locator；PDF 缺失/变化或 current cache ref 变化时返回 stale |
| 覆盖完成性 | 固定 Codex source ref 无逐论文证据覆盖语义 | 无对应领域机制 | Codex 缺失 | 只有每篇成员至少有一个可解析到快照 cache revision 的页级 evidence ref，且没有 stale 成员时，coverage 才为 complete |

## 3. Slice 5 固定边界

- 输入只接受授权论文库中可唯一解析的 12 位旧 ID 或完整 PDF SHA-256，输出统一使用
  完整 PDF SHA-256；
- `ingest_revision` 在当前无独立 v2 ingest store 的条件下等于原始 PDF SHA-256；
  `cache_ref` 单独保存 extractor fingerprint 和 revision ID；
- create 只读取已有 cache revision；cache 不存在时明确要求先运行 `paper-cache ensure`，
  不在 `paper_set` 内执行 PDF 提取；
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
