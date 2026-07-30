# 已实施 Agent 基础设施 Codex 源码映射

状态：Skill、`inspect_page`、统一 Tool Registry 和公开工具基础设施已实施；快速测试
45/45 通过，尚未运行完整测试集或模型评测
日期：2026-07-30
Codex source ref：`fe01054a28fa4bd04716d9ceadb410f2443a50ce`
Codex worktree：`/Users/a123/Documents/agent学习/codex`

## 1. 职责

本文只记录三项已经实施的 Agent 基础设施依据：

1. 内建 `research-papers` Skill 的加载和生命周期；
2. `inspect_page` 的图像能力检查和结果传递；
3. 模型可见工具注册、拒绝未公开工具和 Agent loop 终止语义。

命令执行和 sandbox 见 `library_exec_codex_source_mapping.md`；历史 `paper_set` 见
`paper_set_codex_source_mapping.md`；下一证据合同见
`runtime_research_evidence_codex_source_mapping.md`。

## 2. 源码映射

| 需求 | Codex source | 采用方式 | Paper Copilot 边界 |
|---|---|---|---|
| Skill 格式与加载 | `core-skills/src/loader.rs`、`skills/src/model.rs` | 直接采用标准 `SKILL.md` 和完整正文加载 | 当前只有一个只读内建研究 Skill，不扫描或执行用户 Skill |
| Skill 注入 | `core-skills/src/injection.rs`、`skill_instructions.rs` | catalog + 按需 contextual fragment | world state 只放 metadata；`load_skill` 首次返回正文，compaction 保留已加载版本 |
| Skill 身份与审计 | `EnvironmentSkillMetadata`、`PathUri`、Skill analytics | 必要适配 | 使用固定 resource URI；trace 保存名称、正文版本和 SHA-256，不暴露宿主路径 |
| Skill 权限 | Codex Skill injection 不修改 registry 或 sandbox | 直接采用 | Skill 只指导工作流，不能授权命令、路径、网络、安装或写入 |
| 图像能力 | `protocol/src/openai_models.rs::InputModality` | 直接采用 | 调用前检查 `image`；纯文本模型不做文本回退 |
| 图像工具结果 | `core/src/tools/handlers/view_image.rs` | 直接采用结构、适配 Chat Completions transport | data URL 只进当前模型上下文，不写 session、日志或 trace |
| 文件授权 | `view_image.rs` 的 cwd 与 sandbox 读取 | 必要收窄 | 模型不传任意路径；只接受授权 PDF 身份和单页 |
| PDF 页面渲染 | 固定 Codex ref 无对应能力 | 最小领域适配 | 使用 Poppler 渲染一页或归一化 region，绑定 PDF/render SHA-256 |
| 模型可见工具 | `core/src/tools/spec_plan.rs::build_model_visible_specs_and_registry` | 直接采用 spec 与内部 registry 分离 | 公开名称由 allowlist 决定，旧实现可保留但不可调用 |
| Dispatch | `core/src/tools/router.rs`、`registry.rs` | 直接采用未注册名称显式失败语义 | Runtime 在 schema 解析和执行前拒绝未公开名称 |
| Schema/执行绑定 | `registry.rs::CoreToolRuntime`、`ToolExecutor` | 沿用结构 | `ToolDefinition` 绑定名称、Pydantic input、effect、输出上限和 dispatcher |
| 审批绑定 | `tools/runtimes/shell.rs`、`tools/sandboxing.rs` | 直接采用规范化请求与执行策略绑定 | 绑定 call ID、input hash、目标快照和预览；`library_edit` 是用户可见写入口 |
| 工具输出信任 | shell sandbox、bounded output、tool-result boundary | 直接采用 | PDF、文件名、图片和命令输出均为有界不可信数据 |
| Loop 终止 | `core/src/session/turn.rs` 及 task loop | 直接采用无固定 turn count | 由 `end_turn`、预算、deadline、中断、确定性 guard 或失败收敛 |

## 3. 已实施边界

### `research-papers` Skill

- 正文位于 `src/paper_copilot/agents/skills/research-papers/SKILL.md`。
- 版本从同一正文解析，正文 SHA-256 进入 trace 和 final payload。
- 缓存、搜索、页定位和 incomplete/unresolved 只是工作流指令，不是确定性保证。
- Query 1 已证明 Prompt 不能强制页级读取、完整 SHA-256 引用或集合 coverage。

### `inspect_page`

- 输入为授权 PDF 的完整 SHA-256（首选）或旧 session 兼容 ID、正整数页码和可选 region。
- 单次只渲染一页，限制像素、字节、时间和模型输入大小。
- 不加入 OCR、批量页面、第二模型、全文入库或新依赖。
- 成功结果可作为下一证据合同的受信任页面观察来源。

### 工具表面

- 当前按能力暴露的公开表面是 `load_skill`、`library_exec`、
  `library_write_stdin`、`inspect_page`、`library_edit`。
- 历史工具仍可作为不可调用回滚代码存在；不提供 alias、静默迁移或自动回退。
- 固定 `max_turns` 已删除；历史 job 中同名字段仅读取后丢弃。
- 模型可见的页面文本专用读取工具已删除，文本由 `library_exec` 直接读取并保留其命令
  输出历史；模型可见 `paper_set` 已移除，其他旧实现只服务历史 session 兼容。

## 4. 未引入

- 通用 Skill 市场、目录扫描或用户 Skill 执行；
- 任意图像/PDF 路径、OCR、批量视觉或无界 image content；
- 动态工具、extension/deferred namespace、网络或权限升级；
- 新 LLM call site、embedding、向量检索或旧实现删除。
