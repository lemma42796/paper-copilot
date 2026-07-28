# `library_exec` Codex 源码映射

状态：Slice 2 Runtime 与 `.app` 打包验收通过
日期：2026-07-27  
Codex source ref：`61a44880a85d2fd0d8770908dea5733495e571c8`  
Codex worktree：`/Users/a123/Documents/agent学习/codex`，审计时无本地修改

## 1. 目的

本文按仓库的 Codex-first 原则，逐项核对 Paper Copilot `library_exec` 与固定 Codex
源码。分类只有三种：

- **直接采用**：Codex 已有对应机制，Paper Copilot 保持其结构和语义；
- **必要适配**：Codex 有基础机制，但论文库授权边界要求收窄；
- **Codex 缺失**：固定 source ref 中没有论文领域对应能力，才允许增加最小专用设计。

未列入本文的自定义机制不得进入 Slice 2。

## 2. 源码映射

| 需求 | Codex source | Codex 机制 | Paper Copilot 分类 | 结论 |
|---|---|---|---|---|
| 工具输入 | `core/src/tools/handlers/shell_spec.rs`、`unified_exec.rs` | 必填 `cmd`；可选 `workdir`、`shell`、`tty`、`yield_time_ms`、`max_output_tokens` 和权限参数 | 直接采用 + 必要适配 | 保留 `cmd`；输出预算改用 `max_output_tokens`。论文工具不开放 `workdir`、`shell`、`tty` 和权限参数 |
| 命令解析 | `unified_exec.rs::get_command` | 由选定 shell 将 `cmd` 解析为实际 argv；登录 shell 由配置控制 | 直接采用 + 必要适配 | 使用固定非登录 zsh 生成实际 argv，不允许模型选择 shell |
| cwd | `unified_exec/exec_command.rs` | 相对 `workdir` 基于 environment cwd 解析，并验证本机路径约定 | 必要适配 | environment cwd 固定为论文逻辑 workspace，不接受模型提供的 cwd |
| 环境变量 | `core/src/exec_env.rs`、`unified_exec/process_manager.rs` | 通过 `ShellEnvironmentPolicy` 构造环境，再叠加非交互执行变量 | 直接采用 + 必要适配 | 引入窄化环境策略；不继承用户凭据，并采用 Codex 的 `NO_COLOR`、`TERM`、locale 和 pager 语义 |
| sandbox 选择 | `sandboxing/src/manager.rs` | `SandboxManager` 根据文件系统、网络策略和平台选择 sandbox，再把声明式权限转换为平台命令 | 直接采用 | handler 不直接拥有安全规则；先构造声明式策略，再由 macOS renderer 生成 Seatbelt 命令 |
| macOS sandbox | `sandboxing/src/seatbelt.rs` | 基础策略 + readable roots + writable roots + network policy，最终包装 `/usr/bin/sandbox-exec` | 直接采用 + 必要适配 | readable roots 为 library/cache；writable root 仅 scratch；网络 restricted |
| 权限审批 | `tools/runtimes/shell.rs` | canonical command、cwd、sandbox permissions 和 additional permissions 共同组成 approval key；策略允许时可审批或升级 | 必要适配 | `library_exec` 不开放额外权限，也不在 sandbox 失败后升级；用户可见写操作继续由 `library_edit` 承担 |
| 特殊命令拦截 | `unified_exec/exec_command.rs` 中的 `intercept_apply_patch` | 命令解析后、通用进程启动前，把一个窄化命令交给专用 handler | 直接采用 + Codex 缺失 | `paper-cache` 采用相同拦截位置和失败语义，仅接受占据整个 `cmd` 的直接命令；复合使用明确拒绝，具体缓存操作是论文领域专用能力 |
| 进程生命周期 | `unified_exec/process_manager.rs` | 分配 process id、启动、yield、取消、退出 watcher、并发上限和持续进程存储 | 必要适配 | Slice 2 仅实现一次性有界进程、取消和进程组终止；不实现 PTY、yield session 或 `write_stdin` |
| 执行时限 | `tools/runtimes/shell.rs`、`unified_exec/process_manager.rs` | request 携带 expiration/cancellation；长进程可 yield 后继续 | 必要适配 | 因不提供持续进程，`timeout_ms` 作为硬 deadline，超时终止整个进程组 |
| 原始输出上限 | `unified_exec/head_tail_buffer.rs` | 固定容量保存 head 和 tail，丢弃中间内容并记录 omitted bytes | 直接采用 | 替换当前只保留开头的 stdout/stderr capture，采用对称 head-tail 和明确 omission marker |
| 模型输出预算 | `tools/context.rs::ExecCommandToolOutput` | 使用 token budget 和模型 truncation policy，而不是字符预算 | 直接采用 | 删除 `max_output_chars`，改为 `max_output_tokens` |
| 返回结构 | `tools/context.rs::ExecCommandToolOutput::code_mode_result` | `output`、`exit_code`、`wall_time_seconds`，持续进程时另有 `session_id` 和 `chunk_id` | 直接采用 + 必要适配 | 返回 `output`、`exit_code`、`wall_time_seconds` 和截断元数据；不返回 session 字段 |
| trace/hook | `unified_exec.rs`、`unified_exec/exec_command.rs` | pre/post tool payload 保存实际 command 和 response；审批 identity 使用 canonical command、cwd 和权限 | 直接采用 + 必要适配 | 完整输入/输出进入现有权威 trace；稳定 identity 放在 trace，不作为模型输出协议 |
| PDF 缓存 | Codex source ref 中无论文 TXT 内容寻址缓存 | 无对应领域机制 | Codex 缺失 | 复用 Slice 1 `PdfTextCache`，只增加 `status/ensure/page` 窄化 broker |
| 受控外部命令供应 | `core/src/exec_env.rs`、`sandboxing/src/seatbelt.rs`、`scripts/codex_package/{README.md,rg,dotslash.py,ripgrep.py}` | Codex 构造受控 PATH；package builder 从固定 DotSlash manifest 下载官方 ripgrep 发布包，命中缓存前校验 archive size 和 SHA-256，并只提取目标平台 `rg` | 直接采用 + 必要适配 | `.app` 使用同一 Codex source ref 的 ripgrep 15.2.0 macOS ARM64 artifact、size/SHA-256 和缓存语义；PATH 仅增加 Runtime 控制的调用级 `bin/`。cache、`library_exec` 和 `inspect_page` 共用 Poppler resolver，按 runtime PATH、应用 bundle `bin/`、固定 Homebrew 前缀解析；Seatbelt 只放行已解析命令的精确 Mach-O 闭包 |
| CPU/file-size `ulimit` | Codex unified exec 未发现对应通用限制；`process-hardening` 只关闭 core dump | Codex 缺失 | Codex 缺失 | 用户已明确确认作为 Paper Copilot 一次性论文命令的额外资源边界保留 |

## 3. 当前实现复核

### 3.1 可以保留

- `LibraryExecInput.cmd`；
- 固定非登录 shell；
- 固定论文授权根；
- macOS Seatbelt、无网络和仅 scratch 可写；
- deadline 后终止进程组；
- `paper-cache` 作为窄化内部 broker；
- Runtime 控制的 `rg`/`pdfinfo`/`pdftotext` 调用级命令目录；
- tool input/result 写入现有 session 和 trace。

### 3.2 已按 Codex 回改

1. `max_output_chars` 改为 `max_output_tokens`；
2. stdout/stderr 首部截断改为聚合 head-tail buffer，并带 omitted-bytes marker；
3. 返回结构对齐 Codex 的 `output`、`exit_code`、`wall_time_seconds`，不再自定义
   `completed/failed` 状态作为主要协议；
4. `command_ref` 和 sandbox identity 移入权威 trace，不作为模型工具返回字段；
5. 把 handler 内手写安全规则拆成声明式 filesystem/network policy 和 macOS renderer；
6. `paper-cache` 在命令完成 shell resolution 后拦截，参照 `intercept_apply_patch`，
   只接受占据整个命令的直接调用；复合使用明确拒绝，不在入口处用独立解析路径抢先执行；
7. 环境策略补齐 Codex 的非交互输出约束。
8. 补齐 Codex restricted platform defaults 中用于获取 cwd 的根目录项读取规则；
9. 不开放 Homebrew PATH，只把三个批准命令和精确 Mach-O 依赖加入声明式 Seatbelt
   policy；可用命令名称进入权威 trace，外部真实路径不进入模型输出协议。
10. cache、命令 sandbox 和页渲染统一使用同一 Poppler resolver，避免“命令可用但
    cache 报缺失”的分裂判断。

### 3.3 用户已确认的必要适配

- 不开放 Codex 的 `workdir`、模型可选 shell、login shell、PTY 和远程 environment；
- 不实现 `yield_time_ms`、持续 session 和 `write_stdin`；
- 不开放 sandbox/additional permissions，也不在 sandbox 失败后升级；
- 保留 Paper Copilot 专用 `paper-cache` broker；
- 保留一次性命令的硬 `timeout_ms`；
- 当前额外 CPU/file-size `limit` wrapper 是 Codex unified exec 中没有的设计，作为
  明确的 Paper Copilot 专用资源边界保留。
- `rg` 作为受控 Runtime 依赖随 `.app` 分发，供应方式直接采用 Codex package builder
  的固定官方 artifact、archive size/SHA-256 校验和临时缓存。该 artifact 自包含
  PCRE2，并携带 ripgrep 与 PCRE2 许可证。Poppler 不随 `.app` 分发，只解析用户安装后
  的固定 Homebrew `pdfinfo`/`pdftotext`。

上述差异已于 2026-07-27 获得用户确认。Runtime 手工验收与 `.app` 打包验收均已通过；
Slice 2 完成，不自动开始其他 v2 slice。
