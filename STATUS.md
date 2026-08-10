# STATUS

> 当前任务的跨会话接力快照。每次更新覆盖旧内容，不追加历史流水；详细设计与实验结果
> 保存在各自产物中。

更新于 2026-08-10。

私有历史实验已迁移为单层当前值结构：每个实验根目录直接保存 `experiment.md`、Query、
私有标签、rubric、metrics、包含逐项裁决的 `scores.yaml` 与 `evidence.yaml`。相同协议的
正式重跑只保留最新值；2026-08-08 的 PC V4 Flash 单系统重跑已拆成独立实验
`pc-v4flash-current-max`。旧 `_audit/` 与 `raw/` 包装层已移出活动 `experiments/`，可恢复地
保存在私有根目录 `legacy_experiment_artifacts/`；原始 runs、session、job 和 trace 未删除。

## 新会话从这里继续

PDF 工具链自动恢复已按 Codex 的命令审批与 sandbox override 结构移植到 Python Runtime。
`library_exec` 默认仍无网络且只允许论文逻辑 workspace 的既有读写边界；模型只能为一条精确
命令申请附加网络/文件权限或 sandbox 外执行，审批绑定命令、固定 cwd、权限和输入哈希。
管理员路径使用受限 `SUDO_ASKPASS` 和 macOS 隐藏输入框，密码不进入模型、session 或 trace；
每条命令有独立硬超时，超时、取消和 conversation teardown 都终止原进程组。

Research Skill 已升到 v29：首次读取论文前检查 `pdfinfo`、`pdftotext`、`pdftoppm`；缺少
Poppler 时先检查 Homebrew，按审批分别安装 Homebrew 和 Poppler，最后回到默认 sandbox
复验工具并重试原论文操作。已有工具链路径由
`trace-5287b51caa264d7eae63cfe065cd7521` 验证，没有重复安装或申请权限。

缺少 Poppler 的真实开发 App 验收由 `trace-ce7fccb047d24934b9ffa339bbeda742`
完成：独立 Reviewer 三次均把精确 `brew install poppler` 判定为 high risk、high
authorization、allow；最终在 sandbox 外安装 Poppler 26.07.0，未使用管理员权限，随后在
默认 sandbox 确认三个命令版本，并用真实《FaceNet》PDF 完成元数据读取、首页文本提取和
页面 PNG 渲染。测试 PNG 已清理。

首次验收暴露审批模型 300 Token 输出预算不足，现已提高到 1000；上述三次真实审批分别使用
601、686、838 Token。安装命令使用 `| tail` 时还会掩盖 Homebrew 的失败退出码，默认与升级
shell wrapper 现已启用 `pipefail`；定向验证中失败管道返回 1，成功管道返回 0。

这仍不是发布包验收：完全没有 Homebrew 时的官方安装脚本、管理员密码输入/取消、新 DMG
打包和 Release 下载后运行尚未验证。公开 App 仍是 `v0.1.0-preview.1`，不包含本次工作区
改动。

## 主动公式 OCR 真实验证

成功任务：`job-20260809T092725-b68b814a53`。

- 状态：`completed`，单次 attempt，终止原因 `end_turn`；
- 费用：`0.07822684 CNY`；事件数：49；
- 报告：
  `/Users/a123/.paper-copilot/papers/conversation-20260809T092725-a73177d1a1/research-report.md`；
- Trace：
  `/Users/a123/.paper-copilot/jobs/job-20260809T092725-b68b814a53/attempts/1/trace.jsonl`；
- 没有失败的工具调用，未调用 accept，当前 v3 缓存没有 accepted formula OCR record。

### 公式 (2-9)

论文：《基于多模态信息融合的行人轨迹追踪方法研究》（项莘泽，2025），物理页 28。

- 当时旧协议记录了 `repair_span_id=page-0028-repair-0001`；新协议不再使用该字段；
- region：`{"x1":0.38,"y1":0.09,"x2":0.73,"y2":0.148}`；
- 第 1/3 次成功，用时 8.7 秒；
- candidate：`formula-candidate-77c211087abb4fd3bb2e5e21b166ed3d`；
- render SHA-256：
  `dd2b793aa171b651e36ca67e1f6e70af5bfcd61c979528ed9d9a2fe5e6de0a0b`；
- OCR 恢复向量箭头、根号、求和上下限和平方上标；原始输出的 `\boxed` / `array` 是包装
  产物，裁图顶部横线可能是诱因；
- 候选属于旧 Runtime 进程，后续需重新 recognize，再验证 overlay accept 与缓存回读。

### Rank-3 内联式

论文：《基于多粒度特征融合的多模态行人重识别研究》（彭思懿，2025），物理页 39。

- 通过上下文、`60%` 文本锚点和逐字符坐标确认
  `Rank-3 = 3 / 5 × 100% = 60%`；
- 属于正文内联表达式，缓存信息足够，没有调用 OCR，也没有 candidate 或裁图。

### 公式 (4.10)

论文：《基于低秩融合与动态增强的多模态行人重识别研究》（何子玲，2023），物理页 46。

- region：`{"x1":0.36,"y1":0.545,"x2":0.88,"y2":0.63}`；
- 第 1/3 次成功，用时 3.126 秒；
- candidate：`formula-candidate-4cec34d2168f41419e805509f1d9eeaa`；
- render SHA-256：
  `1ae5b33808fdab6a3e67a431f2454603312904d8cc1de630834da980af2c212a`；
- OCR 恢复两组分段左花括号和二维结构，裁图包含编号，所以原始结果尾部带 `(4.10)`；
- 旧协议因没有写入目标快照而不能 accept；新协议已取消该前提，但旧进程 candidate 不复用。

## Plus-M 本机组件状态

- Runtime/模型组件版本：`1.1.0`；manifest schema：2；
- Helper：ARM64，ad-hoc 签名，已通过 `codesign --verify --deep --strict`；
- 当前激活配置：
  `/Users/a123/Library/Application Support/Paper Copilot/optional-components/formula-ocr/active.json`；
- 当前 Helper：
  `/Users/a123/Library/Application Support/Paper Copilot/optional-components/formula-ocr/versions/1.1.0/FormulaOCRHelper/FormulaOCRHelper`；
- 回滚版本：同目录 `versions/1.0.0/`，另有 `active.plus-s-1.0.0.json` 备份；
- 两次连续真实调用均使用 `PP-FormulaNet_plus-M`，分别 8.7 秒、3.126 秒。

这只验证了本机正常启动、连续调用和真实识别。公开 manifest、Runtime 与模型归档的元数据和
摘要已核对，但尚未从全新 App 安装中执行设置页下载、校验、安装、激活与首次识别。Helper
超时、崩溃重启和一小时空闲退出也未专项验证。

## PDF 字体乱码恢复

Cambria Math、Symbol MT 和缺失 `CIDToGIDMap` 的 ReaderEx 三条源码缓存路径已通过代表性
真实论文验证。7 篇代表样本的显式乱码信号从 12,035 / 2,918,226 降为
202 / 2,908,673，即减少 98.32%；这不是公式准确率，不能发现根号或分段括号等静默结构
丢失。

提取器 fingerprint 为 `embedded-cmap-math-symbol-readerex-v3`。定向 pytest 8 项通过，
覆盖完整 CMap、间接后代数组、显式 CID→GID 解析与应用、观测 GID 门槛、空轮廓删除和
正文顺序保持。

仍未完成：

- 找到真实使用显式 `CIDToGIDMap` 流的代表 PDF 做集成验证；现有真实样本覆盖
  `/Identity` 与映射缺失 ReaderEx，显式流目前只有定向测试；
- 构建包含 Python Helper 的完整 macOS App，确认 PyInstaller 收集 fontTools 并在产品
  缓存目录复现源码结果。

长期记录见 [PDF 字体 Unicode 恢复验证](docs/design/pdf_font_unicode_repair_validation.md)。

## 报告数学排版与客户端性能

SwiftMath `1.7.3` 已锁定，Debug/Release arm64 构建通过；完成报告支持常用展示/行内数学
定界符，解析失败保留原始 LaTeX。仍需 App 内视觉核对深浅色、长公式横向滚动、链接与
失败降级。生成中的活动文本按设计继续使用轻量纯文本。

客户端长流性能修复已按用户接受的 3,278 条、10,000 条和 500 公式边界通过；不再把
50,000 条耐久、停止/强退恢复和重复长跑列为本轮待办。现有结果不证明真实模型长期运行
无内存泄漏。

## 下一步

1. 构建新的 Apple Silicon DMG，发布下一版 Preview，再从 Release 下载运行并复验 Poppler
   恢复、产品缓存字体修复、SwiftMath 与 Formula OCR 下载；
2. 在完全没有 Homebrew 的 macOS 上验证官方安装脚本、管理员密码输入和取消路径；
3. 决定 `m a x` / `e x p` 等局部 OCR 拼写间距的安全处理方式，并用无编号公式覆盖 v4
   accept 与跨会话复用；
4. 验证三次 recognize 上限、失败计数、Helper 超时/崩溃重启和一小时空闲退出；
5. 继续寻找真实显式 `CIDToGIDMap` 流 PDF，补上字体修复集成覆盖。

## 本次文件边界与验证

本轮实现修改 `library_exec` schema、sandbox policy、命令审批、自动 Reviewer、进程超时与
`SUDO_ASKPASS`，同步 Research Skill v29、macOS 审批展示、架构和两份设计文档。真实开发
App trace 覆盖已有工具链与“已有 Homebrew、缺少 Poppler”两条路径；后者完成安装和真实 PDF
三工具复验。审批预算修复在真实 trace 中验证，`pipefail` 只做了两种 wrapper 的定向命令
验证。未运行 Python 测试、Ruff、mypy、完整分发构建或新 Release 安装；Homebrew 缺失与
管理员路径未验证。`output/` 仍是用户未跟踪产物，不提交。
