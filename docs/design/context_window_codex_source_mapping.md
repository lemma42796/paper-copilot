# 上下文窗口 Codex 源码映射

状态：已实施  
日期：2026-07-27  
Codex source ref：`61a44880a85d2fd0d8770908dea5733495e571c8`
Codex worktree：`/Users/a123/Documents/agent学习/codex`，审计时无本地修改

## 目的

将 Paper Copilot 的固定上下文窗口、压缩阈值和 macOS 工作窗口显示收敛到该固定 Codex
配置的计算口径；不新增模型调用、模型配置字段或 provider 探测。

## 源码映射

| 需求 | Codex source ref | Codex 现有机制 | Paper Copilot 采用方式 |
|---|---|---|---|
| 原始模型窗口 | `codex-rs/models-manager/models.json` | 默认模型配置 `context_window: 272000` | `MODEL_CONTEXT_WINDOW_TOKENS = 272_000` |
| 有效窗口 | `core/src/session/turn_context.rs` | `context_window × effective_context_window_percent`；默认 95% | `272000 × 95% = 258400`，作为工作窗口和硬门槛 |
| 自动压缩 | `protocol/src/openai_models.rs` | 未显式配置时为原始窗口的 90% | `272000 × 90% = 244800`，在下一次模型调用前按估算值触发压缩 |
| 窗口使用量 | `protocol/src/protocol.rs`、`tui/src/token_usage.rs` | 使用最近调用的 `total_tokens`；百分比计算从分子和分母均扣除 12K baseline | 聊天 job 返回主 Agent 最近调用的原始 `total_tokens` 和 258.4K 有效窗口；客户端仅在百分比计算中从分子和分母扣除 12K |

## 必要适配

Codex 在采样后根据实际 token 使用量决定是否开始新的上下文窗口；Paper Copilot 现有 loop
在下一次模型调用前依据估算值压缩。后者保留，以免把超出 provider 上限的请求发出；数值和
显示公式与 Codex 对齐。

macOS 客户端把同一 conversation 的每次用户追问持久化为独立 job/session。正常追问从
上一轮已完成 session 重建完整 rollout history，注入最新 Runtime context 后将追问追加为
新的 user turn；它不恢复上一轮的 cost 或其他 attempt 运行时状态。这样最近一次模型调用
看到的是追加后的活动历史，其 `total_tokens` 可直接作为工作窗口读数。只有 compaction
替换工作历史后，该读数才允许下降。中断后恢复同一 job 仍使用原 attempt 的 recovery
history 和 runtime state。

## 保持不变

- 压缩目标仍为 80K；
- 近期完整历史预算仍为 40K；
- 不新增模型配置字段、provider 元数据请求或 LLM call site；
- 不改变 append-only session 与 compaction trace。
