# Agent 工具与注入安全边界

## 信任边界

- 用户输入、PDF 文本、文件名、检索片段和普通工具输出都按不可信数据处理。
- 只有应用构造并放在固定消息边界的 `runtime_context` 才是运行时状态。
- 工具 schema、Pydantic 参数校验和应用策略决定是否允许调用；来源文本不能修改这些规则。
- 每个工具输出有应用侧字符上限。超限内容替换为包含预览、原长度和 SHA-256 的截断信封。

Prompt 指令用于帮助模型正确理解边界，但不承担最终授权。真正的安全边界位于路径校验、工具策略和审批流程中。

## 工具定义与权限

`ToolDefinition` 统一声明工具名、输入模型、副作用和输出上限。当前副作用包括：

- `read_library`
- `write_library`
- `write_index`
- `spend_llm_budget`
- `update_job_state`

策略结果为 `allow`、`deny` 或 `require_approval`。所有工具先完成 schema 校验和策略判断，再进入具体实现。

## library_files 原语

`library_files` 提供可组合操作：`list`、`inspect`、`mkdir`、`copy`、`move`、`trash`、`restore`。

- 路径必须相对论文库根目录，解析后仍须位于根目录内。
- 文件操作只接受 PDF；隐藏的回收区不能被普通路径操作访问。
- 不覆盖现有文件；批量操作先检查重复路径和目标冲突。
- 不提供永久删除。`trash` 返回回执，`restore` 根据回执恢复。
- `list` 和 `inspect` 默认允许；所有修改操作需要本次用户批准。

## 审批生命周期

修改操作把任务切换为 `waiting_for_approval`，并把工具名、原因、副作用和已校验参数保存到 job 记录。客户端通过 HTTP 批准或拒绝。批准后执行一次原调用；拒绝后向 Agent 返回工具错误，磁盘不发生修改。中断、失败和服务恢复都会清除悬空审批。
