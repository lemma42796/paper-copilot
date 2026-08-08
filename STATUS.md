# STATUS

> 当前任务的跨会话接力快照。每次更新覆盖旧内容，不追加历史流水；详细设计与实验结果
> 保存在各自产物中。

更新于 2026-08-08。

## 新会话从这里继续

下一任务是重新讨论公式定位方法，先不要写代码。用户对现有三级链
`cache_slot` bbox → `locate_page_text` 双锚点 → `equation_label` 很不满意；此前“公式核实
管线已收官”的判断作废。下一轮应先把公式发现、区域定位、OCR、核实和 accept 拆开，
比较建库期 bbox、运行期文本锚点、编号定位、整页版面/公式检测等方案，再由用户确认
最小可维护路径。

Formula OCR 的另一条工程线已完成源码修改：生产默认从
`PP-FormulaNet_plus-S` 切换为准确率优先的 `PP-FormulaNet_plus-M`，并把每次冷启动改为
常驻 Helper。首次公式请求才加载模型；后续请求串行复用同一进程；连续一小时无请求时
Helper 自动退出；路径变化、协议失步、超时、取消或 Runtime 退出会丢弃进程；旧组件不支持
`--serve` 时回退到原单次 `--image` 调用。

这只是源码状态。当前已安装的 macOS Formula OCR 组件仍是 Plus-S；没有构建、签名、发布
或安装 Plus-M 组件，因此现在运行的 App 还没有真正切到 M。

## 本轮源码变更（尚未做运行验证）

- `src/paper_copilot/formula_ocr_helper.py`
  - 模型身份改为 `PP-FormulaNet_plus-M`；
  - 新增 `--serve` JSON-lines 协议、惰性模型加载与一小时空闲退出；
  - 保留 `--image` 单次诊断入口。
- `src/paper_copilot/agents/formula_ocr_tool.py`
  - 新增长寿命 Helper 管理器、全局串行请求、request ID 校验、stdout/stderr 边界；
  - 超时、崩溃或协议失步后丢弃子进程，对可恢复的断流只重试一次；
  - 支持取消、Runtime 退出清理和旧 Helper 兼容降级。
- `apps/macos/PaperCopilot/Runtime/FormulaOCRManager.swift`
  - 安装 manifest 的预期模型目录改为 Plus-M。
- `apps/macos/PaperCopilot/Views/SettingsView.swift`
  - 设置文案改为 Plus-M；已安装状态提供用户主动触发的“检查并更新”按钮。
- `scripts/build_formula_ocr_component.sh`
  - 构建目标改为 Plus-M；Runtime 默认版本为 `1.1.0`，模型版本独立为 `1.0.0`。
- `ARCHITECTURE.md` 与 `docs/design/formula_ocr_optional_component.md`
  - 同步 Plus-M、常驻进程、空闲释放与兼容边界。

静态检查 `git diff --check` 通过。按仓库规则没有主动运行 Ruff、mypy、pytest、App 构建、
组件构建或真实 OCR。本轮行为仍未验证。

## Plus-M 本地权重

此前已下载并解压：

- 目录：`/Users/a123/Downloads/formula-ocr-m/PP-FormulaNet_plus-M_infer/`
- 归档：`/Users/a123/Downloads/formula-ocr-m/PP-FormulaNet_plus-M_infer.tar`
- 归档大小：592 MiB
- SHA-256：`f208430a7ec1079fce53a447b340e0183bf6c5c14e32915886635c37ec4c5fd9`

构建时显式设置
`FORMULA_OCR_MODEL_DIR=/Users/a123/Downloads/formula-ocr-m/PP-FormulaNet_plus-M_infer`；不要覆盖
当前已安装组件，也不要在未验证前发布 manifest。

## 定位方案现状与问题

当前实现仍是三级定位：

1. 建库期通过 `pdftotext -bbox` 为 `cache_slot` 预计算归一化 bbox；
2. 槽位无 bbox 时由 `locate_page_text` 使用正文双锚点推导区域；
3. 有稳定编号的独立公式可使用 `equation_label`。

已知问题：

- C0 残骸型槽位可能没有 bbox，只能绕到锚点路径；
- 完全丢弃型损坏没有文本层信号，当前检测层看不见；
- 定位、OCR 与 Agent 降级策略耦合，路径和错误引导偏复杂；
- 公式编号并不总是存在，文本锚点也会受栏布局、跨页和提取损坏影响。

下一轮只讨论方案与决策指标，不默认延续三级结构，也不先给现有路径打补丁。

## 工作树与提交边界

- 分支：`main`；本轮开始时 `HEAD` 与 `origin/main` 都是 `aa55bc3`。
- 本次工程提交应包含：`TASKS.md`、`STATUS.md`、Formula OCR Helper/Runtime/Swift/构建脚本、
  `ARCHITECTURE.md` 和 Formula OCR 设计文档。
- 以下实验改动先前已存在，不属于本次 M/常驻 Helper 工程提交，必须保持原样且不要混入：
  - `docs/design/experiment_index.md`；
  - `eval/experiments/codex-vs-pc-deepseek-formula-ocr/`。
- 不提交或推送本地 Plus-M 权重、构建产物、用户缓存、凭据或私有评分产物。

## 下一步

1. 与用户讨论并选定公式定位方法；方案确认前不实现。
2. 定位方案确定后，再单独构建和真机验证 Plus-M `1.1.0` 可选组件。
3. 只有真实安装与推理验证通过后，才发布组件或宣称 App 已切到 M。
