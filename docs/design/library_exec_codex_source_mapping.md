# `library_exec` Codex 源码映射

状态：Codex 执行反馈、按需 manifest 发现与上下文职责去重已写入工作区，尚未验证或重跑
日期：2026-08-01
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
- Slice 2 不实现 `yield_time_ms`、持续 session 和 `write_stdin`；该历史限制已由 E3
  conversation 级环境取代；
- 不开放 sandbox/additional permissions，也不在 sandbox 失败后升级；
- 保留 Paper Copilot 专用 `paper-cache` broker；
- Slice 2 保留一次性命令的硬 `timeout_ms`；E3 改为 bounded `yield_time_ms`，整体
  deadline 继续由 Agent/job Runtime 强制；
- 当前额外 CPU/file-size `limit` wrapper 是 Codex unified exec 中没有的设计，作为
  明确的 Paper Copilot 专用资源边界保留。
- `rg` 作为受控 Runtime 依赖随 `.app` 分发，供应方式直接采用 Codex package builder
  的固定官方 artifact、archive size/SHA-256 校验和临时缓存。该 artifact 自包含
  PCRE2，并携带 ripgrep 与 PCRE2 许可证。Poppler 不随 `.app` 分发，只解析用户安装后
  的固定 Homebrew `pdfinfo`/`pdftotext`。

上述差异已于 2026-07-27 获得用户确认。Runtime 手工验收与 `.app` 打包验收均已通过；
Slice 2 完成，不自动开始其他 v2 slice。

## 4. E3：conversation 级 Unified Library Environment

固定 Codex 源码 `fe01054a28fa4bd04716d9ceadb410f2443a50ce` 的后续映射：

- `core/src/tools/handlers/unified_exec/exec_command.rs`：exec 分配 process ID，解析
  yield/output budget，并把仍存活进程交给 session 级 manager；
- `core/src/unified_exec/process_manager.rs::exec_command`：进程在初始 yield 前进入
  store，返回增量输出、chunk ID、可选 process/session ID 和 exit code；
- `process_manager.rs::write_stdin`：同一 process 的交互串行化，非空输入写入、空输入
  轮询，退出后从 store 移除；
- `core/src/tools/handlers/unified_exec/write_stdin.rs`：模型使用 `session_id` 继续原命令，
  不重新执行权限或 pre-tool 流程。

Paper Copilot 的必要适配：

- `LibraryEnvironment` 位于 conversation session 目录，固定 `workspace/`、只读
  `library/`/`cache/`、持久 `scratch/` 和受控 `bin/`；
- process manager 使用不透明 UUID session ID，stdout/stderr 合并为按 interaction
  drain 的 bounded chunk；每次返回独立 chunk ID；
- `library_exec` 公开 `cmd/yield_time_ms/max_output_tokens`；
  `library_write_stdin` 公开 `session_id/chars/yield_time_ms/max_output_tokens`；
- 用户中断或删除 conversation 时终止全部进程组；
- 不开放 PTY、login shell、shell/workdir/environment 选择、网络或权限升级；
- 受控 Python 留给 E4，不在本 slice 扩大 PATH。

## 5. Codex 式跨论文批量研究视图

固定 Codex 源码与原生运行证据表明，低工具调用数不只来自 shell 语法：

- `core/src/tools/handlers/shell_spec.rs::create_shell_command_tool` 提供通用命令入口；
- `core/src/tools/handlers/shell/shell_command.rs::to_exec_params` 把模型命令映射到同一
  执行环境；
- 原生论文运行在平坦 cwd 中直接枚举 PDF，并用一次 Python 批处理覆盖多篇论文。

Codex 没有 Paper Copilot 的论文授权、内容寻址 cache 和应用内引用契约，因此不能原样
开放任意本地 Python 或把原始 PDF 复制到平坦目录。最小产品适配为：

- Runtime 为本次已准备论文生成内容寻址、不可变的 JSONL manifest；
- conversation workspace 用短 `papers/paper-NNNN-<artifact>.layout.txt` 只读 symlink
  指向既有内容寻址缓存，不复制文本、不改变授权；
- 模型通过 `research-manifests/current.jsonl` 按需发现当前 manifest，并在同一环境中
  使用短文本路径；
- `python3` 仅作为既有受控 `python` 的命令别名，不增加解释器、第三方包、网络或写权限；
- Skill 对多论文任务优先建议有明确标签的批量发现，但不强制固定搜索顺序。

这保留了 Paper Copilot 的确定性缓存、页码证据和引用边界，同时消除模型拼接长缓存路径
和逐论文启动命令的主要协调成本。是否实际降低工具调用和 token，仍需在同一冻结问题集
上做受控评测；本实现本身不把预期收益记为已验证结论。

## 6. 2026-07-31 工具调用粒度诊断

### 6.1 运行证据

同一 `deepseek-v4-pro`、reasoning effort `max` 的既有 trace 显示：

- Codex CLI 共 19 次原生 function call，其中 2 次环境发现、17 次论文研究；
- Paper Copilot 禁用 Skill 的当前实现共 59 次 `library_exec`；
- Codex 每次工具输出平均 11142 字符，PC 平均 5035 字符；
- PC 总工具输出更多，但按“定位—局部读取—修正范围—再次读取”分散在更多轮次；
- PC 没有权限或协议失败，现有通用 shell、循环、管道、`pdftotext` 和受控 Python
  已足以表达跨论文批处理；
- Codex 的较少调用同时伴随 UDA 误判和 T03 漏项，不能把最低调用数直接等同于更强
  Agent。

改动前 PC 存在两个具体容量差异：

1. `LibraryExecInput.max_output_tokens` 默认和硬上限均为 10000；
2. `LibraryEnvironment` 在模型侧 token 截断之前，先以 64000 bytes 的 head-tail
   buffer 收集原始输出。

最新 V4 Pro 运行中已有一次命令在第二层省略 88810 bytes。因此只修改 prompt 或仅提高
schema 上限都不能验证 Codex 式批量读取；底层收集和模型侧截断必须作为同一协议切片
处理。

### 6.2 固定 Codex 源码依据

固定源码 `fe01054a28fa4bd04716d9ceadb410f2443a50ce`：

- `core/src/tools/handlers/shell_spec.rs`：`exec_command` 与 `write_stdin` 暴露
  `max_output_tokens`，描述为较大请求可由 policy 限制，而不是在 schema 中固定
  10000 上限；
- `core/src/tools/context.rs::ExecCommandToolOutput::response_text`：模型可见结果按
  chunk、wall time、exit/session、original token count 和 output 组成稳定文本；
- `ExecCommandToolOutput::truncated_output`：token 截断与底层 collection omission
  分别标记，不静默把两者合并；
- `core/src/unified_exec/process_manager.rs`：completed 与 yielded 共享 output
  collection metadata，并由 `write_stdin` 返回后续增量。

### 6.3 当前工作区实现

目标是让同一模型获得与 Codex 等价的执行反馈和批量证据带宽，不追求固定调用次数。

实施范围：

1. 将 `library_exec` / `library_write_stdin` 的模型可见结果改为固定 Codex 的文本分节
   语义；结构化 sandbox identity、命令解析和授权信息继续只进入权威 trace；
2. 采用 Codex 的 `max_output_tokens` policy 形态，允许较大请求由 Runtime policy
   限制，不在 Pydantic schema 中把最大值固定为默认值；
3. 联动调整原始 output collection，使其容量与模型侧 token budget 一致，并继续
   暴露准确的 `original_token_count`、collection omitted bytes 和截断 marker；
4. 保留 PC 的必要领域边界：固定 logical cwd、只读 `library/cache/papers`、仅
   `scratch` 可写、无网络、无权限升级、无 PTY/login shell/任意 workdir；
5. 用简洁环境事实声明现有 `pdftotext` 和受控 Python 可用于批处理，不增加论文专用
   搜索、待办或 Query 模板。
6. 停止向 World State 预注入逐论文 `research_cache_index`；把准备完整性、PDF
   SHA-256、短文本别名和 `citation_base` 保存在内容寻址 manifest 中，并通过模型只读
   的 `research-manifests/current.jsonl` 稳定入口按需发现。
7. 去重基础 prompt、工具 description、参数 description 和 research Skill；各层分别
   负责结果约束、工具能力、参数语义和可选研究方法。

非目标：

- 不设置工具调用硬预算或强制一次读取多少篇论文；
- 不针对冻结四轮 Query、Gold claim 或论文名称编码工作流；
- 不修改模型、reasoning effort、Skill 加载生命周期、provider wire、底层 cache 格式
  或引用合同；Skill 正文只做职责去重和 manifest 入口迁移；
- 不以取消 sandbox 换取调用数；
- 不为冻结 Query 编码 system prompt 研究策略。

Definition of Done：

- completed、yielded 和 poll 的模型可见字段与固定 Codex 语义逐项映射；
- 大批量命令不会在模型侧 token policy 之前被未说明的 64 KB 上限静默截断；
- collection omission 与模型侧 token truncation 可在 trace 和模型反馈中区分；
- 现有授权、网络和写入边界不扩大；
- 代码状态记录为“已写入、未验证”；经用户要求的验证和隔离评测仍分别记录，不把未运行
  项标为完成。

评测主门槛为二选一：质量超过 Codex CLI，或在质量不下降时 total tokens 低于 Codex
CLI。工具调用数和平均输出/调用只作为机制诊断；单次运行不作显著性结论。

### 6.4 2026-08-01 direct CLI 诊断补充

独立的 `codex-deepseek CLI + deepseek-v4-flash/max` 四轮 run 保存在：

```text
/Users/a123/paper-copilot-eval-private/multi-thesis-v1/runs/codex-deepseek-cli-v4-flash/formal-single-20260731T163926Z/
```

该 run 的 native trace 只暴露 `exec_command`，共记录 144 次调用，其中绝大多数命令
使用 `pdftotext`；它不是对 Paper Copilot `library_exec` 的协议验证。相较历史
`deepseek-v4-pro` adapter run 的 19 个 native function call，当前 V4 Flash 采用了更
细粒度的 PDF 查询策略。两次运行同时改变了模型和 provider 路径，调用数差异只能作为
工具粒度诊断，不能作为某个实现切片的因果结论。

该 run 的原始 `run_metadata.json` 还暴露了一个计量问题：每个
`turn.completed.usage` 已经是会话累计值，汇总器却再次累加四轮。修正后 formal usage
为 10,617,376 total tokens、¥0.54661056；此前的 22,519,931 / ¥1.31295844 只能标为
错误汇总，不用于效率比较。当前文档不把这个修正冒充为 runner 代码修复。

metadata 虽保存了 research-papers Skill v16 的 SHA-256，native trace 没有显示
`load_skill` 或 Paper Copilot 论文工具的加载记录，因此本次 direct run 不能作为 Skill
v16 已实际加载的证据，也不能替代当前实现的成对消融。
