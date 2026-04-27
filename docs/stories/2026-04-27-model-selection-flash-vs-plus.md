# M15 Session B — qwen3.6-flash vs qwen3.6-plus 模型选型决策

**日期**：2026-04-27
**作者**：yyh455 (paper-copilot M15 Session B)
**结论**：**继续用 qwen3.6-flash 当默认模型**。eval 数据通过了 "0 regression" 门槛，但没出示任何**升级收益**，2x 成本与 2.2x 延迟在没有可测质量提升时不成立。

---

## 背景

M9 cost discipline 写入 `CLAUDE.md`:

> Before changing the default model (switching to a different qwen tier
> or to another provider), run `paper-copilot eval run
> eval/suites/smoke.yaml` and confirm 0 regressions.

M15 Session A 把 eval 趋势报告基础设施铺好（5 baseline + 1 摆拍 catastrophic
+ last-vs-prev diff）。Session B 第一次真用这条规则，gate 一个真实候选——
qwen3.6-plus（百炼 2026-04-02 snapshot）。

候选选定 plus 不是 turbo 也不是 max 的理由（discussion 见 TASKS.md M15
Session B 框定）：

- 同 family 单 hop 升级，工程零差错（base_url / tool_use / cache_control
  协议同 family 不变）
- 价格 1.67x flash 跨四档统一比例，cost 增长可预测
- "升级" 而非"降级"——避免摆拍嫌疑（升级若发现退化才是真实信号）

## 实验设置

| 项目 | 值 |
|------|-----|
| baseline 数据 | Session A run 1-5（flash，正常）|
| degraded 数据 | Session A run 6（flash + DeepAgent prompt "skip methods"，已 git checkout 复原）|
| candidate 数据 | Session B run 7（plus）|
| suite | `eval/suites/smoke.yaml`（5 篇，每篇 methods + contributions）|
| budget cap | 临时 0.20 → 0.50 CNY/paper（plus 1.67x 定价 + headroom）|
| pricing | 2.0 / 2.5 / 0.2 / 12.0 CNY per Mtok（input / cache-create / cache-hit / output）|
| 代码改动 | `agents/llm_client.py:26` `DEFAULT_MODEL = "qwen3.6-plus"`（一行临时切换）+ `shared/cost.py` 加 `QwenPlusPricing` + `pricing_for_model()` |

## 数据

### 每篇成本 / 延迟 / 缓存

| paper_id | baseline cost | candidate cost | cost ratio | baseline lat | candidate lat | lat ratio | b cache | c cache |
|----------|---:|---:|---:|---:|---:|---:|---:|---:|
| 2c03df8b48bf (ResNet)     | ¥0.0533 | ¥0.1368 | **2.57x** | 28.3s | 65.8s | 2.33x | 0.299 | 0.000 |
| 2315fc6c2c0c (AlexNet)    | ¥0.0488 | ¥0.0937 | **1.92x** | 25.5s | 59.5s | 2.34x | 0.309 | 0.140 |
| 268d347e8a55 (ViT)        | ¥0.0732 | ¥0.1303 | **1.78x** | 18.4s | 50.0s | 2.71x | 0.145 | 0.080 |
| 071b16f25117 (Bahdanau)   | ¥0.0550 | ¥0.1017 | **1.85x** | 26.4s | 43.4s | 1.64x | 0.195 | 0.105 |
| 445d06b2ac99 (Inception)  | ¥0.0425 | ¥0.0905 | **2.13x** | 25.0s | 54.9s | 2.20x | 0.282 | 0.136 |
| **suite 合计** | **¥0.273** | **¥0.553** | **2.03x** | 124s | 274s | **2.22x** | 0.246 | 0.092 |

### 字段 PASS rate（所有 7 次 run）

| run | 描述 | methods | contributions |
|-----|------|---:|---:|
| 09-23-37 | flash baseline 1 | 100% | 100% |
| 09-25-51 | flash baseline 2 | 100% | 100% |
| 09-27-41 | flash baseline 3 | 100% | 100% |
| 09-29-40 | flash baseline 4 | 100% | 100% |
| 09-31-22 | flash baseline 5（自然噪声 — AlexNet methods 7→3 触 len_short）| 80% | 100% |
| 09-33-29 | flash 摆拍（DeepAgent prompt "skip methods"）| **0%** | 100% |
| 14-15-51 | **plus candidate** | **100%** | **100%** |

### 趋势图（`eval/report.html`）

7 个 run 的趋势线肉眼分三段：

1. **runs 1-4**：methods + contributions 双线 100% 平稳
2. **run 5**：methods 一根**锯齿** 100→80%（自然 LLM 噪声）
3. **run 6**：methods **断崖** 80→0%（人为 prompt 退化）
4. **run 7**：methods 拉回 100%、contributions 仍 100%（plus 候选）

per-paper cost 曲线在 run 7 整体抬头约 2x；cache hit 曲线 run 7 是冷启动级
（首篇 0%）。

## 解读

### Quality

- **5/5 PASS**：plus 通过了 M9 写下的 "0 regressions" 门槛。
- **可惜，eval 看不出 plus 比 flash 更好**。M14 收尾把断言收到 catastrophic-class
  noise floor（"methods 长度 < golden × 50%" 而非 name-keyed alignment），
  这意味着 flash 和 plus 都过线，但谁离线更远 eval 不报。
- **单样本观察**：run 5 那次自然噪声（AlexNet methods 7→3）在 plus 没复现。
  样本太少（n=1），不能据此宣称 plus 抗噪更强；得跑多次才能定调。

### Cost

- 价格牌 1.67x，**实测 2.03x**——36 个百分点的差额来自 plus 输出更长（更多
  output token）。说明同等任务下 plus 倾向于多说话。
- 单篇绝对值不大（plus ¥0.10 vs flash ¥0.05），但**没有可测质量收益时**
  这 2x 是纯额外开销。

### Latency

- 实测 2.22x。比成本比还要更陡，意味着 plus **每 token 也更慢**。
- 单篇 25s → 55s 对个人 CLI 工具来说都还在可接受区间，但若未来要做
  batch read（M15+ 想法）会被放大。

### Cache

- 看起来 plus cache 命中率比 baseline 平均低（0.092 vs 0.246），但**这是
  伪信号**：baseline runs 2-5 是同一 model 连续跑，前一次 system+tools 仍
  在 5 分钟 TTL 内被 reuse。Plus run 7 是该 model 的**首次**调用，等价于
  baseline run 1（也是 0% / 0.122 / 0.076 / 0.119 / 0.128，和 plus 数字
  几乎相同）。
- 结论：cache 行为同代，**无显著差异**。

## 决策

**继续 qwen3.6-flash 当默认模型**，理由按权重排：

1. **没有可测的质量上行**。eval 通过 ≠ 升级。Session B 主任务是 gate，gate
   的结果是"通行"——但通行只是允许，不是必需。
2. **2x cost 在零收益时不成立**。M9 cost discipline 不是只看 cost cap，是
   看"cost 跟价值是否匹配"。
3. **2.22x latency 隐藏放大风险**。今天 5 篇 ~5 分钟无所谓，未来真要做
   batch reindex / 批量读会被放大。
4. **eval 本身的限制是更值得投资的方向**。如果换 plus 的真实收益存在
   (比如 method name 一致性、subtle hallucination 减少），现在的断言看不
   出来。要么提升 eval 颗粒度（M14 已论证这条路有 LLM noise floor 阻
   挡），要么走另一条路（多次跑 + 投票 / 人工标注 / 语义相似度），都是
   未来 milestone 的真问题，不是 Session B 的事。

### 触发重新评估的条件

未来如果出现下列任一情形，需要重跑这个对比：

- 新增的 eval 颗粒度断言（比如 method name 跨次 stability 度量、subtle
  factual error rate）发现 flash 落后 plus；
- 百炼调价导致 plus / flash 比例显著下降（< 1.3x）；
- 出现 flash 答错且用户人工捕获到的 case，且复跑 plus 答对——这是单 case
  反例，触发 issues.md 一条目，攒够数再讨论。

## 后续行动

- [x] 候选数据落 `eval/runs/2026-04-27T14-15-51Z.jsonl`（保留作为历史
      数据点）
- [x] `shared/cost.py` 的 `QwenPlusPricing` + `pricing_for_model()` 留下
      （未来切换零摩擦的真实必需）
- [ ] 还原 `agents/llm_client.py` `DEFAULT_MODEL = "qwen3.6-flash"`
- [ ] 还原 `eval/suites/smoke.yaml` budget cap 0.50 → 0.20
- [ ] 在 TASKS.md M15 Session B 勾完三条 DoD
- [ ] CLAUDE.md / ARCHITECTURE.md 是否需要补一条"flash 是默认，plus
      可用但需 eval gate"：暂不补，决策本身已经在 story 里立此存照,
      重复不必要

## 简历 bullet 候选文案

> 在 paper-copilot 项目里搭了 eval suite + 趋势报告（7 次 run / 70 数据
> 点 / 静态 SVG / 零 JS），并用它 gate 了一次 LLM 模型选型决策（qwen3.6-flash
> vs qwen3.6-plus）。eval 跑出 5/5 PASS、0 regression，但同时量化出 plus
> 是 flash **2.03x cost / 2.22x latency**，且现有断言无法证明 plus 有
> 等价质量收益——决定继续用 flash，把"升级"挂在颗粒度更高的 eval 假设
> 出现后再做。**用数据否决了一次本来会过 0 regression 关的升级**，比抓
> 自己故意搞的破坏更接近真实工程判断。

## 附录：本次 Session B 的代码改动清单

留下：
- `shared/cost.py`：加 `QwenPlusPricing` / `Pricing` type / `pricing_for_model()`
- `agents/main.py`：`CostTracker(pricing=pricing_for_model(DEFAULT_MODEL))`
- `tests/shared/test_cost.py`：plus pricing 已知值 + routing 测试
- `docs/stories/2026-04-27-model-selection-flash-vs-plus.md`：本 story
- `eval/runs/2026-04-27T14-15-51Z.jsonl`：候选 run 数据（gitignored）

回滚：
- `agents/llm_client.py`：`DEFAULT_MODEL = "qwen3.6-flash"`
- `eval/suites/smoke.yaml`：budget cap 0.20

未做（pre-existing，不在本 milestone 范围）：
- `agents/main.py:106` mypy `arg-type` 错（`related_run.response.usage`
  漏 None 检查）—— 已存在，不在 Session B 范围内修。
- `cli/commands/doctor.py` 仍硬编码 `QwenFlashPricing`：以 flash 为默认
  时正确；若未来切 plus 默认需要这里也跟改并加 session-level model
  字段——届时再说。
