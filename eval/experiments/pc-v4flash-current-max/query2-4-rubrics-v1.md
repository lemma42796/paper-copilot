# Query 2–4 当前评分规范

状态：当前评分口径
机器可读真源：私有目录 `rubrics/query2.yaml`、`query3.yaml`、`query4.yaml`
校正日期：2026-08-04
适用范围：`multi-thesis-v1` 的 Query 2–4

## 共同规则

- `query1-aligned-v1` 保持不变；Query 2–4 分别评分，不把四轮合成一个总分。
- Query 2–4 必须来自同一连续会话。固定分母评价 canonical 任务完成度；对上一轮实际输出
  的跟随情况另记 continuity，不改变固定分母。
- 内容项统一使用 `correct=1`、`partial=0.5`、`incorrect=0`、`missing=0`。错误与缺失
  同分但分开报告。
- 最终回答和原文是质量真源；工具调用、token、费用、耗时、失败与恢复单独报告。
- `未确认` 仅在没有可靠证据时是合规表达；若原文存在明确证据但回答没有给出，该项仍为
  `missing`。
- 评分前只显示匿名 Query 1–4 回答链和本 rubric，不显示系统、Runtime、工具、运行指标、
  旧分或身份映射。全部 scorecard 锁定后才揭盲。
- 实际网络使用、是否真正读取正文、失败恢复和上下文连续性在揭盲后从权威 trace 审计，
  不凭文风推测。

## Query 2：筛选、排除与问题识别

### 固定分母

Query 2 共 54 个主评分项：

1. `primary_unsupervised_selection`：对 14 篇逐篇判断是否“整体以无监督为主要设定”，
   14 项；canonical 仅 P12、P13 为是。
2. `unsupervised_taxonomy`：P12 的无监督域适应、P13 的完全无监督，以及“仅局部使用
   伪标签/混合监督不等于整体无监督”的边界说明，共 3 项。
3. `post_exclusion_issue_selection`：排除 P12、P13 后，对剩余 12 篇逐篇判断是否属于本轮
   的模态缺失、不完整多模态或遮挡集合，共 12 项。P02、P04、P06、P08、P11 纳入；
   P04 和 P06 必须分别注明组件边界与查询图像缺失边界。
4. `required_issue_details`：对 P02、P04、P06、P08、P11 分别评分作者、问题类型、实际
   解决的问题、方法名称和证据页码，`5 × 5 = 25` 项。

主要指标：strict、weighted、completion，以及两个集合的 precision/recall/F1。调用和
运行指标不进入 54 项分数。

### 判定边界

- P12 必须识别为有标签源域训练、无标签目标域训练的无监督域适应；写成一般“无监督”
  为 `partial`，写成完全无监督为 `incorrect`。
- P13 是完全无监督的单模态与跨模态研究；不得与 P12 混淆。
- P03 可用于说明混合监督边界，但不能作为整体主要无监督论文排除；只出现“无监督”一词
  不能触发纳入。
- P02、P08 是推理阶段模态缺失/不完整多模态；两者的问题与补偿方法不得互换。
- P11 整体主要问题是遮挡 ReID。P04 整体仍是轨迹追踪，但其 LIF-ClipReid 子研究明确
  处理局部信息遮挡，因此本轮必须以组件边界方式纳入。
- P06 明确研究查询图像缺失，按 Query 2 的广义“模态缺失”措辞必须纳入；但必须说明它
  是以文本替代缺失视觉查询的 TI-ReID，不得写成 RGB/NIR/TIR 传感器随机缺失。
- 一般数据增强、背景干扰或摘要泛称遮挡不得作为遮挡研究纳入。若回答声称已经列出“全部”
  目标论文，未列出的论文视为明确未选择；否则无法推断的负项记 `missing`。
- 方法名允许全称、缩写或无歧义的描述性名称；只描述目标而没有可识别方法为 `partial`。
- 页码需为可核验 PDF 页码并直接支持该论文的问题或方法；只给印刷页码、宽泛范围或仅
  支持次要主题为 `partial`。

### 独立约束指标

- subsequent exclusion state：P12、P13 从后续讨论排除，P03 及其他论文保留；
- 禁止网络与仅凭文件名判断；
- P06 边界处理；
- false-positive 原因分类：关键词误纳入、一般增强误判遮挡、论文/组件范围混淆。

## Query 3：逐项原文复核

### 分开报告的两个评分族

Query 3 不设置跨部分总分：

1. 上一轮结论复核：按每个系统在 Query 2 后续讨论中实际纳入的项目动态评分。每项评分
   `paper_identity`、`author`、`claim_accuracy`、`pdf_page`、`section`、
   `direct_quote`、`support_calibration`，分母为 `7 × actual_query2_inclusions`。
   因 Query 2 已要求后续排除主要无监督论文，P12、P13 不作为这一部分的固定必答项。
2. 项莘泽论文三个组件：重识别、轨迹补全、可视化系统。每个组件评分 `decision`、
   `rationale`、`pdf_page`、`section`、`direct_quote`，共 `3 × 5 = 15` 项。

两部分分别报告 strict、weighted、completion；另报直接引文支持率和校准准确率。

### 判定边界

- 必须回到原文；只重复 Query 2 的概括而没有页码、章节和短原文，相关证据字段为
  `missing`。
- 引文允许 OCR 空格、标点和换行的非语义差异；改写、拼接成原文没有表达的句子或引用
  错论文为 `incorrect`。
- 页码、章节和引文必须彼此一致。页码正确但章节错误，分别评分，不整体连坐。
- `support_calibration`：原文完整支持且回答准确判断为支持时 `correct`；原文只能部分支持
  而回答明确降级时 `correct`；证据不足却宣称完全支持为 `incorrect`。
- P12、P13 已按 Query 2 的明确指令从后续讨论排除，不因某系统额外复核而加入固定分母。
- 项莘泽组件 canonical 决策：LIF-ClipReid 重识别为 `include`；轨迹补全为 `exclude`，仅
  在更宽泛轨迹/应用综述中条件纳入；可视化系统为 `exclude`，仅在系统实现综述中条件纳入。
- continuity 单独报告 `reviewed_actual_query2_inclusions / actual_query2_inclusions`。

## Query 4：最终比较表

### 三组主指标

Query 4 不把内容准确度与逐单元格证据压成一个总分，分别报告：

1. `final_relevance_decision`：14 项。P01–P10、P14 纳入；P11、P12、P13 排除。
2. `content_accuracy`：11 篇纳入论文 × 10 字段 = 110 项。字段为 `title`、`author`、
   `research_problem`、`supervision`、`input_modalities`、`core_method`、
   `attention_or_fusion_location`、`datasets`、`metrics`、`limitations`。
3. `cell_traceability`：对每篇除题目、作者外的 8 个关键内容字段分别评分证据支持，
   `11 × 8 = 88` 项，使用 `full=1`、`partial=0.5`、`none=0`。

三个指标分别报告 strict/full、weighted 和 completion，不生成跨指标 composite。

### 内容边界

- P11 因整体主要问题为遮挡 ReID 排除；P12、P13 因整体主要设定为无监督排除。若表中仍
  出现，相关 relevance decision 为 `incorrect`，额外行不增加分母。
- P04 只评价 LIF-ClipReid 重识别内容；把 TTCN-pre/TTC 轨迹补全或可视化系统作为该行
  核心方法、数据集或指标为 `incorrect`。
- 红外—可见光必须与 RGB+NIR+TIR、图文 ReID 等输入范围区分；只写宽泛“多模态”而
  隐去决定性模态差异，相关问题或模态字段最高为 `partial`。
- `core_method` 评价 Query 4 明确要求的方法与论文主要贡献；缺少具体方法不再是可选项。
- `attention_or_fusion_location` 必须说明模块作用位置、特征层级或融合阶段；只写模块名称
  而没有位置为 `partial`。论文确无该机制时，应给出有证据的“不适用/未确认”。
- `datasets`、`metrics` 和 `limitations` 只接受论文直接支持的内容。通用常识生成的局限性
  为 `incorrect`；没有可靠证据时写“未确认”符合格式约束，但内容项仍按实际可查状态判定。
- 不因不同数据集、协议或指标直接强行排序；出现无依据排名作为独立严重错误记录。

### 可追溯性边界

- `full`：该单元格有明确 PDF 页码，页面直接支持完整内容；同一页可支持多个字段，但映射
  必须清楚。
- `partial`：页码真实但只支持部分内容，或只给一组宽泛行级页码而无法确定具体字段映射。
- `none`：没有页码、页码不存在、页面不支持、引用网页或错论文。
- 内容正确但没有证据时，内容准确度可为 `correct`，可追溯性仍为 `none`；不得相互替代。

### 独立约束指标

- 11 篇表格每篇一行；
- P04 scope 只保留重识别；
- 红外—可见光区分；
- 不强行跨协议排序；
- `未确认` 使用是否诚实；
- correction log 是否完整列出 Query 2–3 实际发生的修正。若前序没有修正，明确写“无”
  可通过；该 continuity 指标不设固定答案，也不进入 110/88 分母。

## 冲突裁决与冻结范围

- 最终表格或明确最终修正优先；未解决冲突最高为 `partial`。
- 同一错误只在最直接字段扣分一次；由该错误机械导致的集合指标变化照常计算，但不再添加
  人工严重度罚分。
- 私有当前标签确定 canonical 纳入集合、监督边界、组件范围及 Gold claim/evidence
  路由。数据集、指标、局限性和 alternate evidence 允许使用语料中的其他真实页，但
  评分者必须记录页码与短理由，不能依据某系统措辞扩展接受范围。
- Gold revision 2、历史 score、原始答案和 trace 保持只读；本 rubric 不回写旧评分。
