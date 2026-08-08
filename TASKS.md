# TASKS

> 本文件保存所有未完成任务，可以同时存在多个任务；已完成任务删除，未完成任务保留或
> 更新。实验记录不得写入这里；历史实验入口统一见
> [实验索引](docs/design/experiment_index.md)。工程规则见 [AGENTS.md](AGENTS.md)，
> 当前接力状态见 [STATUS.md](STATUS.md)，当前架构见
> [ARCHITECTURE.md](ARCHITECTURE.md)。

更新于 2026-08-09。

## 未完成任务

### 1. 完成 PDF 字体乱码恢复产品级验证

状态：`source_cache_validation_partial`，Cambria Math 源码缓存路径已通过一篇真实学位论文
验证，打包 App 与其余字体路径仍未验证。

已完成：

- 对 65 页学位论文《基于低秩融合与动态增强的多模态行人重识别研究》执行隔离缓存重建；
- 命中 1 个 Cambria Math 字体并重建 7,613 条 Unicode 映射，原始文本中的 851 个
  `U+FFFD` 在修复后降为 0；
- 变化只出现在物理页 21、22、24，已与原 PDF 逐页核对数学字母、希腊字母和公式结构；
- 首次 `PdfTextCache.ensure` 生成 65 页缓存，第二次命中同一 revision，临时修复 PDF 已清理。

尚未完成：

- 用真实 Symbol MT 论文验证标准数学符号，并确认不完整拼装件仍保持未解析；
- 用含 `B3+SimSun` ReaderEx 空控制字形的论文验证控制字符删除且正文汉字不变；
- 用不符合修复条件的普通 PDF 验证完全不修改；
- 构建并运行 macOS App，确认 PyInstaller 打包 fontTools 且产品缓存路径结果一致。

### 2. 重新讨论并设计公式定位方法

状态：`deferred_by_user`，用户后续将大改，本轮不修改实现。

用户对当前三级定位链不满意：`cache_slot` bbox → `locate_page_text` 双锚点推导 →
`equation_label`。下一轮先重新定义定位问题和产品边界，再决定是否保留、替换或简化
现有路径。

讨论至少覆盖：

- 把“发现公式、定位公式区域、OCR 识别、模型核实与 accept”拆成独立阶段，明确每阶段
  的输入、输出和失败语义；
- 比较建库期 bbox、运行期文本锚点、公式编号、整页版面/公式检测等候选方法；
- 处理 C0 残骸型无 bbox 与完全丢弃型无文本层信号，而不是继续叠加隐式降级规则；
- 以可靠性、可解释性、工具调用复杂度、延迟和缓存复用为决策指标，选出最小可维护方案；
- 方案确认前不修改定位实现、Skill 或缓存格式。

### 3. 构建并验证 Plus-M Formula OCR 可选组件

状态：`implementation_complete_packaging_pending`，排在定位方案讨论之后。

生产源码默认模型已从 `PP-FormulaNet_plus-S` 切换为
`PP-FormulaNet_plus-M`。Runtime 已改为首次请求按需启动 Helper、串行复用同一已加载模型，
连续一小时无请求后由 Helper 退出释放内存；旧版单次调用 Helper 保留兼容降级。

尚未完成：

- 用已下载的 Plus-M 权重构建 `1.1.0` Runtime/模型组件；
- 签名并生成/发布新的 manifest 与归档；
- 真机安装更新，验证冷启动、连续复用、超时/崩溃重启、一小时空闲释放和真实公式识别；
- 有验证结果后再决定是否清理旧 Plus-S 安装或保留回滚版本。
