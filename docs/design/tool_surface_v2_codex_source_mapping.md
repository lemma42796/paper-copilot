# 工具系统 v2 公开表面 Codex 源码映射

状态：v2 Slice 6 已实施
日期：2026-07-27  
Codex source ref：`61a44880a85d2fd0d8770908dea5733495e571c8`  
Codex worktree：`/Users/a123/Documents/agent学习/codex`，审计时无本地修改

## 1. 目的

本文按 Codex-first 原则核对 Paper Copilot 的模型工具公开切换、未公开工具拒绝、审批
协议和不可信工具数据边界。Slice 6 只切换公开表面并收敛既有安全机制；旧实现保留为
不可由模型调用的回滚代码。

## 2. 源码映射

| 需求 | Codex source ref | Codex 现有机制 | Paper Copilot 结论 |
|---|---|---|---|
| 模型可见工具列表 | `codex-rs/core/src/tools/spec_plan.rs` 的 `build_model_visible_specs_and_registry` | 从已规划 runtime 生成独立的 model-visible specs，同时构造内部 registry | 直接采用职责分离：`_MODEL_TOOL_NAMES` 只发布四个 v2 schema，旧定义继续留在内部表中 |
| 工具 dispatch | `codex-rs/core/src/tools/router.rs`、`registry.rs` | Router 通过 registry dispatch；未注册名称返回 model-visible unsupported error | 必要适配：Paper Copilot 异步 Runtime 在解析和执行前用公开名称 allowlist 拒绝旧工具 |
| Schema 与执行绑定 | `registry.rs` 的 `CoreToolRuntime`/`ToolExecutor` | 每个注册工具同时拥有 spec、payload 类型和执行处理器 | 沿用现有 `ToolDefinition` 将名称、Pydantic input、effect、输出上限和 dispatch 绑定 |
| 审批与调用绑定 | `tools/runtimes/shell.rs`、`tools/sandboxing.rs` | 审批键绑定规范化请求和执行策略，策略变化后不复用批准 | 沿用已实现的 tool call id、input SHA-256、目标快照和预览复核；`library_edit` 仍是唯一用户可见写入口 |
| 客户端审批展示 | Codex approval protocol 将请求数据交给 host UI，不按业务工具复制执行逻辑 | UI 显示工具、参数、理由和影响，决策回到 runtime | 必要适配：现有 macOS 通用审批卡已支持 `library_edit` 的 operation、effects、target snapshot 和 diff，无需新增工具特例 |
| 不可信文件与输出 | Codex shell sandbox、bounded output 和 tool-result message boundary | 命令在受限 filesystem/network policy 下执行，输出截断后作为工具数据返回 | 直接保持 Slice 2 的 sandbox 和输出上限；Skill 明确文件名按 shell data 处理，PDF、图片和命令输出都不能定义行为 |
| Skill 与工具能力 | `codex-rs/core-skills/src/injection.rs`、`skill_instructions.rs` | Skill 注入工作流指令，但不扩大工具 registry 或 sandbox | 更新内建 Skill 以组合四工具；权限仍完全由 schema、policy、sandbox 和审批控制 |
| Agent loop 终止 | `codex-rs/core/src/codex.rs` 的 turn loop；当前公开源码已拆分到 session/task 模块 | 模型需要继续时持续执行工具回合，不使用固定 turn count；由完成、预算、deadline、中断或失败收敛 | 删除 Paper Copilot 的 `max_turns` schema、Runtime 参数、trace 字段和终止分支；保留预算、job deadline、重复调用 guard、工具 timeout 和中断 |

## 3. Paper Copilot 专用边界

- `paper-cache` broker、页级 evidence ref、`inspect_page` 和 `paper_set` 是论文领域能力，
  沿用 Slice 1–5 已确认的设计与各自源码映射。
- Paper Copilot 只有一个固定模型工具表面，不实现 Codex 的动态工具、MCP、extension
  或 deferred namespace discovery。
- macOS 客户端继续使用既有持久 job 审批协议；本 Slice 不增加新的审批类别或自动扩大
  `library_exec` 权限。
- 历史 `job.json` 中的 `max_turns` 仅在读取时丢弃，不再进入新 job schema 或运行语义。

## 4. 未引入的机制

- 旧工具 alias、静默迁移或自动回退；
- 网络、任意宿主路径、权限升级或交互式 shell；
- OCR、embedding、向量检索或新的 LLM call site；
- 旧实现删除；该工作只允许在冻结评测通过并再次确认后进行。
