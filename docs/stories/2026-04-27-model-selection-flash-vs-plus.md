# qwen3.6-flash vs qwen3.6-plus 模型选型

**日期**：2026-04-27
**结论**：继续用 `qwen3.6-flash`。Plus 通过了回归门，但没有测出质量收益，
实测成本 2.03x、延迟 2.22x，不满足升级 ROI。

## 背景

M15 第一次用项目自身的 eval suite 裁决真实模型升级，而不是只验证 eval 能否
识别人为破坏。规则是：更换默认模型前必须达到 0 regression；通过这一门槛
只是必要条件，还必须有足以覆盖成本和延迟增量的正向质量信号。

候选使用同一 qwen family 的 plus tier，协议和工具调用路径不变，能把实验主要
变量收敛到模型 tier。

## 实验设置

| 项目 | 值 |
|---|---|
| baseline | qwen3.6-flash，5 次正常 run |
| degraded control | flash + 故意跳过 methods 的 prompt，1 次 run |
| candidate | qwen3.6-plus，1 次冷启动 run |
| suite | `eval/suites/smoke.yaml`，5 篇 × methods/contributions |
| candidate pricing | 2.0 / 2.5 / 0.2 / 12.0 CNY/Mtok |
| 临时改动 | 默认模型切 plus；单篇预算 cap 0.20 → 0.50 |

临时模型和预算改动在实验后还原。多 tier 计费支持
`QwenPlusPricing` / `pricing_for_model()` 保留，便于以后重新评估。

## 结果

| paper | flash cost | plus cost | cost ratio | flash latency | plus latency | latency ratio |
|---|---:|---:|---:|---:|---:|---:|
| ResNet | ¥0.0533 | ¥0.1368 | 2.57x | 28.3s | 65.8s | 2.33x |
| AlexNet | ¥0.0488 | ¥0.0937 | 1.92x | 25.5s | 59.5s | 2.34x |
| ViT | ¥0.0732 | ¥0.1303 | 1.78x | 18.4s | 50.0s | 2.71x |
| Bahdanau | ¥0.0550 | ¥0.1017 | 1.85x | 26.4s | 43.4s | 1.64x |
| Inception | ¥0.0425 | ¥0.0905 | 2.13x | 25.0s | 54.9s | 2.20x |
| **合计** | **¥0.273** | **¥0.553** | **2.03x** | **124s** | **274s** | **2.22x** |

字段 PASS rate：

| run | methods | contributions | 含义 |
|---|---:|---:|---|
| flash normal 1-4 | 100% | 100% | 稳定 baseline |
| flash normal 5 | 80% | 100% | 自然 LLM 噪声 |
| flash degraded | 0% | 100% | 人为 catastrophic regression |
| plus candidate | 100% | 100% | 通过回归门 |

## 解读

- Plus 5/5 PASS，达到 0 regression 的必要门槛。
- 当前 assertions 校准在 catastrophic-class noise floor，只能说明两个模型都
  过线，不能证明 plus 在 method 命名稳定性或细微幻觉上更好。
- Plus 标价约为 flash 的 1.67x，但实测成本为 2.03x，说明它在同一任务上还
  生成了更多 output tokens。
- 延迟比成本增长更高，说明 plus 每 token 也更慢。
- Plus 的 cache hit ratio 不能与连续 warm flash runs 的均值直接比较。它是该
  模型首次调用，正确参照是 flash 的首次冷启动 run；两者 cache 形态接近。

## 决策

继续使用 `qwen3.6-flash`：

1. 没有可测的质量上行。
2. 2.03x 成本在零可测收益时不成立。
3. 2.22x 延迟会在批量和长工作流中进一步放大。
4. 更有价值的后续工作是提高 eval 对细微质量差异的分辨能力，而不是在现有
   coarse gate 下升级模型。

## 重新评估条件

满足任一条件时重跑同类冷启动对比：

- 新 eval 指标能稳定测出 method alignment、subtle factual error 或其他质量差异；
- plus/flash 实际成本比例显著降到约 1.3x 以下；
- 真实用户 case 持续出现 flash 答错、plus 答对的可复现证据；
- provider、模型版本或 cache 行为发生实质变化。

## 可复用经验

- 0 regression 是升级的必要条件，不是充分条件。
- 模型 tier 的真实成本要用端到端 run 测量，价格表比例只是下界。
- 跨模型 cache 比较必须使用相同冷启动状态。
- 对随机信号看多次运行趋势；单次锯齿不等于整体退化。
