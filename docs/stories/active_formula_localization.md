# 主动公式定位：从损坏文本到可核验 LaTeX

Paper Copilot 不依赖单独训练的公式定位模型，也不需要为论文预先标注公式裁剪框。研究模型先用缓存文本找到页码和公式编号，再读取原 PDF 的逐字符坐标，自主选择归一化 `region`；本地渲染器只按该区域裁图，公式 OCR 组件负责把裁图转写成 LaTeX。

这份记录保存一次真实运行中的两个代表性案例。两处公式都在第一次裁剪中覆盖了完整主体，未调整 `region`，也未写回缓存。

> [!IMPORTANT]
> 这里证明的是：在这两个案例中，通用研究模型借助文本锚点与字符几何，一次选中了足以识别完整公式的区域。它不等于“完全不使用定位信息”，也不证明任意版式、任意公式都能一次成功。

## 工作链路

1. 在 `layout.txt` 中搜索公式编号或上下文，确定候选页。
2. 在原 PDF 文本层中搜索编号，取得编号及邻近字符的坐标。
3. 研究模型根据字符的相对位置推断公式范围，并提交归一化 `region`。
4. Paper Copilot 从原 PDF 渲染该区域；公式 OCR 模型只接收这张裁图。
5. OCR 返回原始 LaTeX，供用户核对；只有显式接受后才能写回缓存。

定位阶段没有调用单独的公式检测或文本定位模型。速度来自“编号文本缩小到一页 + PDF 已有字符坐标”，公式框本身则由研究模型在运行时判断，不是根据编号坐标机械套用固定偏移。

## 案例一：公式 (2-9)——文本已损坏

论文：《基于多模态信息融合的行人轨迹追踪方法研究》（项莘泽，2025），物理页 28。

### 1. 缓存文本

缓存保留了公式编号和部分线性文本，但向量符号、根号、求和结构与上下标已经损坏或丢失。它仍可用于搜索和导航，不能作为公式原文。

![公式 (2-9) 的缓存文本，其中包含乱码并丢失公式结构](../assets/formula-ocr-active-localization/equation-2-9-text-cache.png)

### 2. 研究模型选择的原 PDF 裁图

模型先用 `(2-9)` 定位编号，再检查同一行的字符坐标，选择 `{"x1":0.38,"y1":0.09,"x2":0.73,"y2":0.148}`。第一次裁剪已经包含向量箭头、根号、求和上下限和平方上标。

![研究模型为公式 (2-9) 选择的实际 OCR 裁图](../assets/formula-ocr-active-localization/equation-2-9-model-crop.png)

### 3. OCR 结果

公式 OCR 模型 `PP-FormulaNet_plus-M` 的原始输出：

```latex
\boxed{\begin{array}{l}{\mathrm{d}(\overrightarrow{\mathrm{A}},\overrightarrow{\mathrm{B}})\;=\;\sqrt{\sum_{\mathrm{i}=1}^{\mathrm{N}}{(\mathrm{A}_{\mathrm{i}}-\mathrm{B}_{\mathrm{i}})^{2}}}}\end{array}}
```

去掉 OCR 生成的 `\boxed` / `array` 包装后，可读形式为：

![公式 (2-9) OCR 结果的可读渲染](../assets/formula-ocr-active-localization/equation-2-9-ocr-result.png)

裁图顶部带入了一段横线，可能是 OCR 产生 `\boxed` 包装的原因；数学主体完整。公式编号未包含在裁图内，由 PDF 文本坐标单独确认。

| 运行证据 | 值 |
| --- | --- |
| 尝试次数 | `1 / 3` |
| `candidate_id` | `formula-candidate-77c211087abb4fd3bb2e5e21b166ed3d` |
| `render_sha256` | `dd2b793aa171b651e36ca67e1f6e70af5bfcd61c979528ed9d9a2fe5e6de0a0b` |
| OCR 用时 | `8.7 s` |
| 裁剪是否调整 | 否 |

## 案例二：公式 (4.10)——字符可读但结构静默丢失

论文：《基于低秩融合与动态增强的多模态行人重识别研究》（何子玲，2023），物理页 46。

### 1. 缓存文本

缓存中的字母和条件大多可读，但两组分段公式的左花括号与二维排版已经丢失。与显式乱码相比，这种“看起来正常”的结构损失更容易被误用。

![公式 (4.10) 的缓存文本，字符可读但分段结构丢失](../assets/formula-ocr-active-localization/equation-4-10-text-cache.png)

### 2. 研究模型选择的原 PDF 裁图

模型根据 `(4.10)` 的编号坐标和上下两组字符的位置，选择 `{"x1":0.36,"y1":0.545,"x2":0.88,"y2":0.63}`。第一次裁剪覆盖了两个分段定义和编号。

![研究模型为公式 (4.10) 选择的实际 OCR 裁图](../assets/formula-ocr-active-localization/equation-4-10-model-crop.png)

### 3. OCR 结果

公式 OCR 模型 `PP-FormulaNet_plus-M` 的原始输出：

```latex
\begin{align*}p_{i}&=\left\{\begin{aligned}&1-\beta&,i=y\\ &\beta/N&,i\neq y,\end{aligned}\right.\\L_{CE}^{'}&=\left\{\begin{aligned}&(1-\beta)*L_{CE}&,i=y\\ &\beta*L_{CE}&,i\neq y,\end{aligned}\right.\end{align*}(4.10)
```

整理空格与编号位置后的可读渲染：

![公式 (4.10) OCR 结果的可读渲染](../assets/formula-ocr-active-localization/equation-4-10-ocr-result.png)

原始输出恢复了缓存文本中不可见的两组分段左花括号。裁图也带入了公式编号，因此原始 OCR 结果尾部包含 `(4.10)`。

| 运行证据 | 值 |
| --- | --- |
| 尝试次数 | `1 / 3` |
| `candidate_id` | `formula-candidate-4cec34d2168f41419e805509f1d9eeaa` |
| `render_sha256` | `1ae5b33808fdab6a3e67a431f2454603312904d8cc1de630834da980af2c212a` |
| OCR 用时 | `3.126 s` |
| 裁剪是否调整 | 否 |

## 结论与边界

| 问题 | 本次结果 |
| --- | --- |
| 是否预埋公式框 | 否，`region` 由研究模型在运行时选择 |
| 是否使用单独的公式定位模型 | 否 |
| 是否使用定位信息 | 是，使用文本搜索和原 PDF 逐字符坐标 |
| 两个公式是否一次覆盖完整主体 | 是 |
| OCR 是否完全等于最终可引用文本 | 否，仍需去除包装、核对原 PDF，并由用户确认 |
| 是否写回缓存 | 否，本次候选保持 `recognized_pending_acceptance` |

本案例的重点不是宣称“零算法定位”，而是展示一条更轻量、可审计的路径：复用 PDF 自带的文本与几何信息，让通用研究模型主动选择公式区域，再把局部图像交给专用公式 OCR。每次识别都保存 `region`、候选 ID 和渲染哈希，因此裁图与结果可以复现和核对。

## 审计来源

- 任务：`job-20260809T092725-b68b814a53`，状态 `completed`。
- Trace：`~/.paper-copilot/jobs/job-20260809T092725-b68b814a53/attempts/1/trace.jsonl`。
- 研究报告：`~/.paper-copilot/papers/conversation-20260809T092725-a73177d1a1/research-report.md`。
- 两张“模型裁图”由生产渲染路径按 trace 中的 `region` 重新渲染，文件 SHA-256 与对应 `render_sha256` 完全一致。
- 两张“OCR 结果”图是为了文档可读性生成的整理版渲染；原始模型输出以上方代码块为准。
- 工具层仍标记 `verified=false`，候选未经 `accept`，本页不把未经确认的 OCR 自动写入缓存。
