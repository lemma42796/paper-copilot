# 论文研究 Skill Codex 源码映射

状态：v2 Slice 3 已实施
日期：2026-07-27  
Codex source ref：`61a44880a85d2fd0d8770908dea5733495e571c8`  
Codex worktree：`/Users/a123/Documents/agent学习/codex`，审计时无本地修改

## 1. 目的

本文按 Codex-first 原则核对 Paper Copilot 的 `research-papers` Skill。Skill 只提供可审查
工作流，不是命令、路径、网络、安装或写入权限边界。

## 2. 源码与实验映射

| 需求 | Codex 或基线依据 | 现有机制 | Paper Copilot 结论 |
|---|---|---|---|
| Skill 格式 | `codex-rs/core-skills/src/loader.rs`、`codex-rs/skills/src/model.rs` | 从 `SKILL.md` YAML frontmatter 读取 `name`/`description`，正文按需加载 | 直接采用标准 `SKILL.md`，并提供 `agents/openai.yaml` 界面元数据 |
| Skill 内容注入 | `codex-rs/core-skills/src/injection.rs`、`codex-rs/core-skills/src/skill_instructions.rs` | 读取完整 `SKILL.md`，以带 `name`、`path` 和正文的 `<skill>` contextual user fragment 注入 | 直接采用相同数据流；在首次运行、恢复和压缩后上下文中注入完整 Skill |
| 资源身份 | `EnvironmentSkillMetadata`、`PathUri` | 环境拥有的 Skill 使用 URI 标识，不要求暴露宿主绝对路径 | 使用固定 `resource://paper-copilot/.../SKILL.md`，不向模型暴露用户本机路径 |
| 发现范围 | Codex skills root discovery 与显式 `$skill` mention | Codex 支持多个作用域和按名称/路径选择 | 必要适配：产品当前只有一个内建论文研究 Skill，运行时确定性加载，不增加通用 Skill 市场、目录扫描或用户 Skill 执行 |
| 上下文生命周期 | Codex 每轮构造 Skill injection；Paper Copilot 既有 resume/compaction 状态机 | Skill 指令在需要的 turn 中重新物化 | 必要适配：首次运行、恢复 turn 和 compaction anchor 都重新加入同一只读 Skill fragment |
| 调用记录 | Codex `SkillInvocation` analytics 与注入状态 metric | 记录 Skill 名称、scope、path 和调用类型 | 复用现有权威 rollout trace，在 turn attributes 和 final payload 记录名称、版本、资源 URI 与正文 SHA-256 |
| Skill version | Codex metadata 没有满足本计划评测要求的独立版本字段 | Skill 可由 path/name 识别，但不能单独冻结内容版本 | Codex 缺失：从同一内建 `SKILL.md` 正文解析唯一显式版本，并同时记录完整正文 SHA-256；不维护会漂移的第二份版本常量 |
| 命令研究顺序 | 冻结四轮 Codex 权威 trace；摘要见 `tool_system_v2_plan.md` 2.3 | `pdfinfo` → `pdftotext -layout` → `rg`/`awk` → 有界页读取 | 复现为 cache status/ensure、`rg`/`awk` 页面定位和 `paper-cache page` 证据绑定，不复制 benchmark 答案 |
| 空结果与截断 | Codex command trace；`ExecCommandToolOutput`/head-tail 输出语义 | 非零退出、timeout、截断和空搜索保持可见 | Skill 要求检查结果元数据；单次空结果不解释为论文不存在该概念 |
| 权限与不可信输入 | Codex Skill injection 不改变 sandbox；Paper Copilot `library_exec` policy | Skill 是上下文，不授予额外命令或文件能力 | 直接保持：PDF、缓存和输出不可信，Runtime policy 仍是唯一执行边界 |

## 3. Paper Copilot 专用边界

- `paper-cache page` 是 Codex 中没有的论文领域原语，沿用 Slice 1/2 已确认的内容寻址缓存
  与窄化 broker。broker 只拦截占据整个 `library_exec.cmd` 的直接命令；循环、管道、
  命令链、替换和 `find -exec` 中的 `paper-cache` 明确拒绝，不伪装为 PATH executable。
- Citation ref 使用完整 PDF SHA-256 与 PDF 页码；权威 trace 另绑定 extractor
  fingerprint、revision 和 page artifact hash。
- `inspect_page` 直接接受 cache 和 `paper_set` 返回的完整 PDF SHA-256；12 位
  `paper_id` 仅用于兼容旧 session，不允许由完整 SHA-256 截断得到。
- `paper_set` 负责显式集合和全量 coverage；Skill 在需要视觉关系时调用
  `inspect_page`，无法形成页级证据或完成覆盖时标记 `incomplete`。
- Codex turn loop 只依据模型响应、待处理输入、工具调用、预算和中断判断是否继续；固定
  source ref 中未发现论文集合 coverage 的领域完成 validator。若加入确定性
  end-turn coverage guard，应作为 Paper Copilot orchestration 的最小领域校验，不修改
  通用 Agent loop，也不引入固定 turn count。
- 当前模型工具没有宿主软件安装能力。Skill 检测到 Poppler 缺失时先请求明确同意，但不
  通过无网络、无升级路径的 `library_exec` 绕过边界；宿主安装能力不存在时明确停止。

## 4. 未引入的机制

- 通用 Skill discovery、用户 Skill 安装或任意 Skill 执行；
- 新 LLM worker、全文结构化字段、OCR、embedding 或向量 RAG；
- benchmark 特例或预写论文答案；
- 由 Skill 放宽 sandbox、网络、路径、审批或写入权限。
