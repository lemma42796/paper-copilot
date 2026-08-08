# TASKS

> 本文件保存所有未完成任务，可以同时存在多个任务；已完成任务删除，未完成任务保留或
> 更新。实验记录不得写入这里；历史实验入口统一见
> [实验索引](docs/design/experiment_index.md)。工程规则见 [AGENTS.md](AGENTS.md)，
> 当前接力状态见 [STATUS.md](STATUS.md)，当前架构见
> [ARCHITECTURE.md](ARCHITECTURE.md)。

更新于 2026-08-08。

## 未完成任务

### 1. 重新讨论并设计公式定位方法

状态：`discussion_pending`，下一任务，不开始实现。

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

### 2. 构建并验证 Plus-M Formula OCR 可选组件

状态：`implementation_complete_packaging_pending`，排在定位方案讨论之后。

生产源码默认模型已从 `PP-FormulaNet_plus-S` 切换为
`PP-FormulaNet_plus-M`。Runtime 已改为首次请求按需启动 Helper、串行复用同一已加载模型，
连续一小时无请求后由 Helper 退出释放内存；旧版单次调用 Helper 保留兼容降级。

尚未完成：

- 用已下载的 Plus-M 权重构建 `1.1.0` Runtime/模型组件；
- 签名并生成/发布新的 manifest 与归档；
- 真机安装更新，验证冷启动、连续复用、超时/崩溃重启、一小时空闲释放和真实公式识别；
- 有验证结果后再决定是否清理旧 Plus-S 安装或保留回滚版本。
