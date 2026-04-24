# Phase 2 usage log

> 每读完一篇 `paper-copilot` 就写一条。目的是攒 Phase 2 输入,驱动 M8
> (prompt/schema 迭代)和 M9(cache / cost)。
>
> 条目风格:短、可执行、引一手证据(paper_id / session 路径 / 具体行)。
> 不写"将来应该重构 X"那种想当然。

## 当前进度(2026-04-24 M8 closed)

**Phase 2 收尾 = 13 篇样本**(10 Phase 2 新跑 + 3 M7 reality-check 静态分析)。
**M8 5 条 issue 全关**(1 partial)。Phase 2 质量基线已重置。

**10 篇完成**。测试目录非 symlink PDF 读完。

- ✅ 1. Bag of tricks (ReID) — `b350b567b13a`
- ✅ 2. Deep residual learning (ResNet) — `2c03df8b48bf`
- ✅ 3. FaceNet — `8533b7bdd635`
- ✅ 4. Gradient-based learning (LeNet 98) — `d3f587797f95`
- ✅ 5. ImageNet classification (AlexNet) — `2315fc6c2c0c`
- ✅ 6. In defense of triplet loss — `c2c0252624f0`
- ✅ 7. Neural machine translation (Bahdanau) — `071b16f25117`
- ✅ 8. Hypergraph Neural Networks (HGNN, Feng 2019) — `510d98681e5e`
- ✅ 9. Learning with Hypergraphs (Zhou 2006, NIPS) — `9f53740cc80e`
- ✅ 10. Rethinking the Inception Architecture (Szegedy 15) — `445d06b2ac99`
- ✅ 11. Attention Is All You Need (Vaswani 17) ⁺ — `a639448e61be`
- ✅ 12. ViLBERT (Lu 19) ⁺ — `65a9c7b0800c`
- ✅ 13. ViT (Dosovitskiy 21) ⁺ — `268d347e8a55`

⁺ = M7 reality-check session,2026-04-24 通过静态分析 session.jsonl
补入,未重跑;详见文末"累积观察"表的 M7 三行注释。**Phase 2 数据收集
结束**,切 M8。

运行命令:`./.venv/bin/paper-copilot "<pdf>"`。默认 `--lang en`。

### M8 triage 排序(按严重度)

跨 9 篇浮出。**M8 closure 2026-04-24**:前 5 条已按顺序关闭 —— 见
每条 `[DONE]` 标记和文末"M8 Closure"小节。

1. **[DONE 2026-04-24] [SEVERE] 无 embedded outline 时 Skim 只见首 3 页 →
   outline 残缺 → Deep 丢整块后半论文。** Zhou 2006 NIPS(8 页,无 PDF
   bookmarks)暴露:`src/paper_copilot/agents/skim.py:38` 硬编码
   `_FRONT_MATTER_PAGES = 3`,Skim 只看前 3 页文字 → 推断出的 outline 只有
   4 个 section(Abstract / Intro / Preliminaries / 3 Normalized hypergraph
   cut,最末 page_end=3) → Deep 只 fetch 这 4 节 → Experiments /
   Conclusions / 大半 Methods 从未进模型 → output 的 experiments 字段里
   把**摘要那句"Our experiments on a number of benchmarks showed..."**
   当实验数据,limitations 字段 LLM 自己说"provided text snippet does not
   explicitly list limitations"还强行编一条。影响面:任何无 bookmarks 的
   PDF(老 NIPS / 老 ICML / 无 \usepackage{hyperref} 的 latex 输出)。
   **修复(commit 70aa5aa)**:`load_front_matter` 先 peek toc,
   有 outline 读 3 页、无则读 8 页(或全文,取小)。Zhou06 重跑 outline
   从 4 → 10 section,Experiments 变真 4 条,Limitations 变成论文原文抽取。
2. **[DONE 2026-04-24] [SEVERE] `arxiv_id` 幻觉成真实他论文 id** —
   AlexNet 被写成 Vaswani 17 的 `1706.03762`。
   **修复(commit 8a8f92b,schemas 三合一)**:`arxiv_id` field description
   明确禁 "NEVER invent or infer from title, authors, year";同时删掉
   `meta.id` 字段(LLM 填 id/arxiv_id 两字段随机分配的根源)。AlexNet
   重跑 `arxiv_id=null`(论文 NIPS 2012 本就无 arxiv 版)。
3. **[DONE 2026-04-24] [SEVERE] Section 嵌套导致 Deep 输入重复喂入** —
   Bahdanau 定位到根因:父 section 的 content 已含所有子 section 文字,
   子 section 又作为独立 section 再贴一次 → Bahdanau 15p PDF 12.5k tokens
   被膨胀成 Deep 输入 45k tokens(in 总 59.6k,迄今最高)。HGNN 9p 也达
   4.66x,确认与页数无关、与嵌套 depth × width 有关。证据:`2 Background`
   (7207 字符) ≈ 其唯一子节 `2.1 RNN Encoder-Decoder`(7190),字节对
   字节重合。这重写了之前"长文 feeding 丢失"的故事:不是 feeding 不够,
   是 **feeding 重复** → budget 被自己吃空。
   **修复(commit 520f56d)**:`retrieval/sections.py` 加 "skip parent"
   规则——section i 若 sections[i+1].depth > sections[i].depth 则跳过,
   只保留 leaf。Bahdanau 重跑 ratio 4.77 → 2.90 (-39%),HGNN 4.66 →
   3.40 (-27%)。
4. **[PARTIAL-DONE 2026-04-24] [HIGH] `meta.id` vs `arxiv_id` 混淆 +
   "low-resource languages" 模板** — (合并原 3 和原 4)。
   **修复(commit 8a8f92b)**:删 `meta.id` 字段;`Limitation.description`
   加反例禁"low-resource languages"类跨域模板。Partial 因为 AlexNet
   仍产出变体 "English-language visual object recognition tasks"(图片
   无语言仍被套模板,LLM 绕过字面禁令)。纯 prompt 层到此为止,语义变体
   需要 validator/output filter 类硬机制,归到 M9+ 候选。
5. **[DONE 2026-04-24] [HIGH] Method schema 无 "novel to paper" 闸门** —
   LeNet 把 backprop 当本篇 method 并编 novelty。
   **修复(commit 8a8f92b)**:Method 加 `is_novel_to_this_paper: bool`
   必填字段。AlexNet 重跑 8 methods → 3 True / 5 False(CNN / ReLU /
   Dropout / Data Augmentation / SGD Momentum 都标 False)。报告渲染
   对 False entry 加 `[baseline]` tag。
6. **[DONE 2026-04-24] [MED] Confidence 刻度废 + "Not stated but likely:"
   自注入** — (合并原 6 和原 7)。
   **修复(commit 8a8f92b)**:`Contribution.confidence: float (0-1)` →
   `evidence_type: Literal["explicit_claim", "author_hedge",
   "our_inference"]`。AlexNet/Inception/ViLBERT 回归:hedge 语言的
   contribution 落到 `author_hedge`(Inception "aux classifiers as
   regularizers" 一条)、硬数据落 `explicit_claim`,结构化 3 档取代
   float clumping。`Limitation.description` 同时禁"Not stated but
   likely:" 前缀(全部 3 个回归篇此前缀为 0)。
7. **[DONE 2026-04-24] [MED] 非数值 experiment 塞入数值 schema** —
   ResNet/LeNet/Triplet/Bahdanau 多 metric 挤一条导致 `value: null`。
   **修复(commit 8a8f92b)**:`Experiment.dataset` / `.metric` description
   明确"每 (dataset, metric) 对一条 Experiment,never 'mAP / Rank-1' 斜线"
   + 多条件(All vs No UNK)也要拆。M14 eval 重测 Triplet/Bahdanau
   验证 `value: null` 比例归零。
8. **[DEFERRED] [LOW] 终端 rich 把 display-math `_xxx_` 当 italic 吞掉** —
   只影响 CLI stdout,report.md 存盘正常。CLI 渲染层 bug,不在 M8 范围。
9. **[DEFERRED] [LOW] session.jsonl 缺 per-call usage / latency** — 13/13
   命中。影响 Phase 2 反思纪律"找最贵一步"。属于 `session/` + `agents/loop`
   观察性改动,留给 M9(prompt cache + doctor 命令)一起做。

---

## Conventions

- **paper_id**: 文件系统 id,对应 `~/.paper-copilot/papers/<id>/`
- **Severity tags**:
  - `[BUG]` 输出明确错误(字段错位、转义错、事实错)
  - `[SMELL]` 输出可用但质量可疑(confidence 恒定、字段堆砌)
  - `[COST]` 延迟 / token / 费用超预期
  - `[UX]` CLI 或 report 渲染层面的体验问题

---

## 2026-04-23 — Bag of Tricks for ReID

- `paper_id: b350b567b13a`
- `pdf: Bag of tricks and a strong baseline for deep person re-identification.pdf` (~10 p, 1.4MB)
- `wall: 19.4s  |  cost: ¥0.0428  |  in=22046 out=2270 cache_read=0`
- Per-step latency(由 session 时间戳推算):Skim 2.7s,Deep 16.1s。

### Issues

- **[BUG] 内联 LaTeX 里 `\times` 被吃成 tab 字符。**
  `report.md` 里 warmup 小节原文:
  `$3.5 	imes 10^{-5}$`(TAB 字符,不是 `\t` 字面量)。
  根因:LLM 在 tool-use JSON 里吐 `\times` 单反斜杠,JSON 解码把 `\t`
  当 tab 转义。**同一段的 display math `$$...\times...$$` 正常**——
  说明 LLM 不一致地 double-escape。命中 `\t/\b/\n/\r/\"/\\` 的 LaTeX
  宏(`\times/\beta/\neq/\rho/\"/\\`)都有风险。M8 优先级。
  - 验证方法:`grep -P '\t' report.md` 能直接命中受害行。

- **[BUG] arxiv id 写错字段。** Skim 把 `arXiv:1903.07071v3` 放进
  `meta.id`,`meta.arxiv_id` 反而是 `null`。但 PDF 左边栏白纸黑字印着
  arxiv id。
  对照 TASKS.md M7 备注("PDF 不印时返回 null"):这是**印了但放错槽**,
  不是抽取不到。`schemas/paper.py` 的 `PaperMeta.id` vs `arxiv_id`
  对 LLM 太像。M8 schema 迭代候选:要么合并,要么给 `id` 的 description
  加反例 "不要把 arXiv:xxx 放进来"。

- **[SMELL] Contribution.confidence 只产 1.0 / 0.9。**
  4 条 contributions:`[1.0, 1.0, 1.0, 0.9]`。和 TASKS.md 观察一致,
  刻度未被使用。这一篇里 3 个 novel_result/novel_method/analysis 打 1.0
  其实**没校准**——前 3 条是论文明说的,第 4 条 batch/image size 实验
  "minor impacts" 论文也只是 supplementary,不该是 0.9 vs 1.0 的 0.1 差。
  M8 要么改 description 给出锚点(1.0 = 论文摘要原话, 0.7 = 需要推断),
  要么干脆删掉 confidence 字段。

- **[UX] Experiment 渲染重复。** `report.md` 每条实验长这样:
    ```
    - **Market1501** / rank-1 accuracy: **94.5%** vs Standard Baseline (ResNet50, 87.7%) (p. 5, 6)
      - _94.5%_
    ```
    父级由 `value+unit+dataset+metric+comparison_baseline+pages` 拼,
    子级 italic 是 `raw` 字段内容。两行大多数情况信息等价(子级只有
    "(trained without REA)" 这种边 remark 时才真多出东西)。
    `cli/` 或 `agents/main.py` 的 markdown 模板需要判断 `raw ≠
    f"{value}{unit}"` 时才渲染子级。

- **[COST] output_tokens 贴顶 76%。** 2270/3000,和 TASKS.md
  transformer (1498) / vit (2398) / vilbert (2279) 数据同频。这篇只 10 页、
  table 不密,就已经 76%。一旦碰 result-heavy(ImageNet/ResNet 那种多
  table)就可能 truncate。M9 之前先看能不能把 Deep 的 max_tokens 调到
  4000-6000,或者给 schema 加 `max_items` 约束。

- **[UX] session.jsonl 没有 per-call usage / latency。**
  TASKS.md Phase 2 要求"看 session.jsonl,找最贵的一步/最慢的一步"——
  但当前 `tool_use` entry 只有 `{parent_id, tool_use_id, name, input}`,
  token 数和 wall_ms 都没写进去。我只能从相邻 entry 的 `ts` 差值倒推
  Skim/Deep 各用了多久,总 cost 只有 CLI 结尾那一行(不区分两个 agent)。
  `session/types.py` + `agents/loop.py` 需要把 `LLMResponse.usage` 和
  wall_ms 落到 tool_use entry 的 payload 里。否则 Phase 2 的第二条纪律
  (看最贵一步)根本做不了。

### What went well

- BNNeck / warmup / last-stride (8x4→16x8) / REA / Label Smoothing /
  Center Loss 6 个方法抽取**全对**,novelty 描述也准。
- "decouple ID loss vs triplet loss gradient signals" 这类**机制层面**
  的 novelty 概括,比论文原文的铺陈更凝练。
- 8 条 experiments 覆盖 same-domain 2 metric × 2 dataset + cross-domain
  2 方向 × 2 metric,无遗漏。
- wall 19.4s << 2min DoD,cost ¥0.043 << ¥0.30 DoD。

---

## 2026-04-23 — ResNet (Deep Residual Learning)

- `paper_id: 2c03df8b48bf`
- `pdf: Deep residual learning for image recognition.pdf` (~12 p, 0.8MB)
- `wall: 20.0s  |  cost: ¥0.0574  |  in=35876 out=1992 cache_read=0`
- Per-step latency:Skim 2.9s,Deep 16.9s。
- 抽取数量:6 contributions / 4 methods / 8 experiments / 2 limitations。

### Issues

- **[BUG] `meta.id` 与文件系统 `paper_id` 语义打架。**
  本篇 `meta.id = "1512.03385"`(arxiv 号),但磁盘路径是
  `~/.paper-copilot/papers/2c03df8b48bf/`。上一篇 `meta.id =
  "arXiv:1903.07071v3"`(带前缀),磁盘路径是 `b350b567b13a`。
  → `meta.id` 是"LLM 编的那个 id",`paper_id` 是"SessionStore SHA1"。
  两个 id **永不相等**。最好: (a) 删掉 `meta.id`,只留 `arxiv_id`,
  文件系统 id 放到非 LLM 字段(比如 session_header 已经有 `paper_id`);
  或 (b) `meta.id` 由 SessionStore 事后回填,不暴露给 LLM。

- **[BUG] `arxiv_id` 抽取仍不稳。** 本篇 `arxiv_id` 正确填了
  `"1512.03385"`,但**同时** `meta.id` 也写了 `"1512.03385"`——重复。
  上一篇 (Bag of Tricks) arxiv_id = `null`、`meta.id = "arXiv:1903.07071v3"`
  (带前缀)。
  → LLM 行为:前缀是否带、塞 `id` 还是 `arxiv_id`,每篇随机。
  和上一篇的 `[BUG] arxiv id 写错字段` 是同一个根因 (schema 两个字段
  功能重叠) 的两种表现。M8 必改。

- **[SMELL] Non-numeric experiment 被硬塞进数值 schema。**
  第一条实验(degradation 观察)长这样:
    ```json
    {
      "dataset": "CIFAR-10", "metric": "training error",
      "value": null, "unit": "%",
      "raw": "56-layer plain net has higher training error than 20-layer ...",
      "comparison_baseline": "Plain Network (same depth/parameters)",
      "pages": [1]
    }
    ```
    `value: null` + `unit: "%"` 自相矛盾(没值还有单位)。这种"A 比 B 差"
    的定性观察其实不是 experiment,更像 contribution 里的 analysis,
    或者一个独立的 `qualitative_finding` 字段。现在被挤进数值格子里,
    渲染成 `n/a vs Plain Network (...)` 很奇怪。
  - M8 候选:experiment schema 允许 `value: null` 但同时要求 `raw` 必填,
    或者给 Deep agent 的 prompt 明确 "只抽 numeric result,定性 observation
    归到 contribution"。

- **[SMELL] Confidence 全 1.0,更差了。** 6/6 条 contribution 全是 1.0。
  上一篇还至少有一条 0.9(4/4 里 1 条)。把 confidence 刻度用成二值
  都谈不上——现在是恒等函数。
  - 和上一篇归到同一条 M8 action:锚定 description 或直接删字段。

### What went well

- **所有 ResNet 标志性论点都抽到**:residual F(x)+x / shortcut 零参数 /
  bottleneck 1x1→3x3→1x1 / 152 层 / 3.57% top-5 / COCO +28% / 1202 层
  overfitting。
- `arxiv_id` 没经过 CLI 额外查询,纯靠首页抽取就拿到了(和上一篇形成
  对照——有印就(有时)能拿到,没印就没)。
- 20.0s / ¥0.057,12 页的 ResNet cost 反而比 10 页的 Bag of Tricks
  (¥0.043)只贵 34%,线性得还挺稳。

### 无 LaTeX tab 腐败

本篇 `grep -P '\t' report.md` = 0 行。对照上一篇:ResNet 的 Methods
只用了 `F(x,\{W_i\})+x` / `y = F(x,\{W_i\})+W_s x`——**没有**
`\times`/`\beta`/`\neq`/`\bar`/`\rho` 这种 `\t/\b/\n/\r` 前缀的
LaTeX 宏,所以逃过 JSON 转义。bug 条件:LLM 输出的 LaTeX 含 JSON
转义字符前缀宏,且那一次 LLM 忘了 double escape。

---

## 2026-04-23 — FaceNet

- `paper_id: 8533b7bdd635`
- `pdf: FaceNet- A unified embedding for face recognition and clustering.pdf` (~9 p, 4.7MB)
- `wall: 13.1s  |  cost: ¥0.0388  |  in=23967 out=1400 cache_read=0`
- Per-step latency(推算):Skim ~2s,Deep ~10s。
- 抽取数量:5 contributions / 4 methods / **3** experiments / 3 limitations。

### Issues

- **[BUG] 幻觉:face recognition 论文 limitation 里冒出"low-resource languages"。**
  原文:
    ```json
    {
      "type": "scope",
      "description": "Experiments are limited to face recognition tasks;
                      transfer to other domains or low-resource languages
                      is not evaluated."
    }
    ```
    "low-resource languages" 是 NLP 教科书模板套语,和 face embedding
    完全无关。LLM 在写 scope limitation 时套了泛化模板没检查语义。
  - 诊断:`Limitation.description` 的 field description 大概鼓励 LLM
    "说一个模型未覆盖的泛化场景",导致模板化。M8 候选:给 `scope`
    type 加一条反例 "不要列举与本篇领域无关的场景(如 face 论文
    提语言、NLP 论文提图像)"。这是**可具体复现、可验证修复**的。

- **[SMELL] Experiments 数量陡降:3 条。** 对照 Bag of Tricks 8 条 /
  ResNet 8 条,同样规模的 FaceNet 只抽出 3 条(LFW / YTF / Personal
  Photos)。但 FaceNet 原文有大量 ablation(embedding 维度 64/128/256
  sweep、图像分辨率 sweep、training data 量 sweep、model zoo 比较)
  都没进来。
  → 不确定是 Deep 的"只保留 headline benchmark"判断,还是 output_tokens
  压力下被截掉(本篇 out=1400 离 ceiling 还远,**不是**token 原因)。
  Bag of Tricks / ResNet 的 DukeMTMC 跨域 / CIFAR 深度 sweep 却进来了。
  标准不一致。M8 schema description 要么明确 "每个 table row 一条 exp"
  要么 "只保留顶层 table",不要让 LLM 自判。

- **[SMELL] Confidence 依旧 1.0/0.9。** 5 条:[1.0, 1.0, 1.0, 1.0, 0.9]。
  第 5 条 harmonic embedding 是 0.9——大概 LLM 觉得"次要 novelty"
  才打 0.9。刻度在"主要 vs 次要"两档之间做了"二分类",其他数值从未出现。
  累积证据越来越强,M8 此项优先级 == BUG。

- **[BUG-repeat] `meta.id` + `arxiv_id` 重复。** 两者都 = `"1503.03832"`。
  和 ResNet 同模式。不再单列,汇总到 M8 行动项。

### What went well

- 核心 FaceNet 故事线齐全:triplet loss + margin α、online hard mining、
  直接 128-D embedding(没 bottleneck)、LFW 99.63% / YTF 95.12%、
  harmonic embedding 跨版本兼容。Methods 3+1 条都准。
- Triplet loss 公式 `sum max(|f(x_a)-f(x_p)|^2 - |f(x_a)-f(x_n)|^2 +
  α, 0)` 原样抽出,`\alpha` 没被 JSON 吞(`\a` 不是 JSON 转义字符)。
- 最快一篇:13.1s。证明窗口/网络非线性没在小 paper 上爆出瓶颈。

### 观察:运行时特征对照表(累积 3 篇)

| paper | pages | wall | cost | in_tok | out_tok | out%ceiling |
|---|---|---|---|---|---|---|
| Bag of Tricks | ~10 | 19.4s | ¥0.043 | 22k | 2270 | 76% |
| ResNet | ~12 | 20.0s | ¥0.057 | 36k | 1992 | 66% |
| FaceNet | ~9 | 13.1s | ¥0.039 | 24k | 1400 | **47%** |

out_tok 并非线性跟 pages 或 in_tok 变——FaceNet in_tok 比 Bag of Tricks
多,out_tok 反而更少。合理假设:Deep 的 "把所有 table row 转成 exp"
自判有随机性,是 out_tok 主要噪声源。

---

## 2026-04-23 — LeNet / Gradient-Based Learning (LeCun 98)

- `paper_id: d3f587797f95`
- `pdf: Gradient-based learning applied to document recognition.pdf` (**46 p**, 1.0MB)
- `wall: 15.8s  |  cost: ¥0.0498  |  in=33288 out=1369 cache_read=0`
- 抽取数量:5 contributions / **4 methods** / 3 experiments / 2 limitations。

### Issues

- **[BUG] 输入 PDF 内容只有约一半进入 LLM。** 本篇 PDF 46 页,
  PyMuPDF 提取 265115 chars ≈ **66k tokens** 粗估。但 `in=33288` 总
  (Skim+Deep 两个 agent 加起来)。推断 Deep 看到的 content 不超过 25-28k
  tokens——**不到 PDF 的一半**。
  → 证据旁证:3 experiments 少得离谱(46 页的 LeCun 百科全书,MNIST
  SDNN check-reading 各有大量 result table),out_tok 1369 也没撞 ceiling
  (46%),不是 token budget 切的。应该是 Skim/Deep 之间的"section
  selection"或 Deep 内部 section 切片把内容 filter 掉了。
  - 验证方法:加一条 debug 日志,dump 每次 LLM call 的真实 user content
    char 数。如果 Deep 发给 LLM 的 char 数 << PyMuPDF 提取总数,就是这个
    bug。M8 之前优先核实。**这可能解释 FaceNet experiments 只 3 条的
    问题**——不是 Deep 自判保守,是压根没看见那些 ablation table。

- **[BUG] Method schema 无 "novel to this paper" 门槛,把 background
  当贡献。** 本篇 4 个 methods 里:
  - `Back-propagation` — Rumelhart 86 发明,LeCun 98 只是用。paper-copilot
    给出的 novelty:"Efficiently computes gradients for deep networks,
    making training of complex non-linear models feasible compared to
    earlier limited linear systems"。**这不是 LeCun 98 的贡献,是 1986
    backprop 本身的。**
  - `Gradient-Based Learning` — 论文的 section 2 标题,整段是 review,
    非本篇 novelty。被当作 Method 写入。
  → `novelty_vs_prior` 是**必填字段**(从历次输出判断),LLM 没法"拒绝
    填",于是对背景技术也编造 novelty。M8:要么让 `novelty_vs_prior`
    optional 并在 prompt 强调"not novel 时留空",要么 Method schema 加
    `is_novel_to_this_paper: bool` 作闸门。

- **[BUG] 幻觉 arxiv id。** `meta.id = "cs/9807034"`(`arxiv_id` = null)。
  旧式 arxiv 格式,看起来像真的,但 LeCun 98 的 Proceedings of the IEEE
  版本**从未上 arxiv**(1998 年 CV/ML 类论文上 arxiv 极少)。LLM 凭格式
  猜了一个。`arxiv_id=null` 没被污染,但 `meta.id` 被污染。再次印证前两
  篇的**[BUG] `meta.id` 有害**论点——这字段既不对 SessionStore 路径
  负责、又被 LLM 随意填,纯净化就该删。

- **[BUG-repeat] "low-resource languages" 幻觉第 2 次出现。**
  Limitation #1: "broader applicability to complex document layouts or
  **low-resource languages** is not extensively evaluated"。
  → 第 2/4 篇命中这个模板。face/document 都蹭 NLP 语料概念。
  **不是 FaceNet 特例,是 LLM 有固定"scope limitation"模板**。M8
  优先级升为 HIGH。改 `Limitation.description` 或 type=scope 的专门
  prompt,加反例。

- **[SMELL-repeat] Confidence 恒 1.0 / 0.9**:[1.0, 1.0, 1.0, 0.9, 1.0]。
  第 4 条打 0.9,大概因为"Hand-crafted features can be replaced..."
  说法较谨慎——LLM 在用 confidence 粗略打"论文 claim 的确定性"而非
  "我的抽取置信度"。**语义错位**。M8 要么删字段,要么重新定义含义。

### What went well

- **Venue 第一次被抽出**(`"Proceedings of the IEEE"`)。前三篇
  venue=null。LeCun 98 因为不是 arxiv preprint,首页有明确 venue 标志,
  Skim 识别得到。
- **年份 1998 准确**,尽管是 28 年前的老 paper,Skim 没被 reference 里
  后续年份(论文 cite 了 2001 前后的进展)带偏。
- LeNet-5 + GTN 两个真实 novel methods 都抽到,novelty 描述准确(LeNet
  novelty 写的是"local connections + shared weights 编码 2D 先验",
  GTN novelty 写的是"全局可微模块图",两条都对)。

---

## 累积 issue 频次(跑完 4 篇)

| 类型 | 命中篇数 | 是否 TASKS.md 已记 |
|---|---|---|
| Confidence 刻度废(恒 1.0/0.9) | 4/4 | **是** |
| output_tokens 贴顶 (>70%) | 1/4 | **是** |
| `\times` tab 转义 | 1/4 | 新发现 |
| `meta.id` / `arxiv_id` schema 混淆 | 4/4 | 新发现 |
| `meta.id` 幻觉 arxiv id | 1/4 | 新发现 |
| 非数值 experiment 塞入数值 schema | 2/4 | 新发现 |
| "low-resource languages" 幻觉 | 2/4 | 新发现 |
| Experiments 抽取不稳(3 vs 8) | 2/4 | 新发现 |
| Method 把 background 当 novel | 1/4 | 新发现 |
| session.jsonl 缺 per-call cost/latency | 4/4 | 新发现 |
| **Deep 看到的 PDF content < 原文一半** | **1/4** | **新发现,最严重** |

**LeNet 触发的那条是 Phase 2 至今最严重发现**——如果属实,意味着前
三篇 FaceNet 低覆盖率也可能是同一个 root cause。剩下 6 篇要有意识地
对照 PDF 页数 / token 数 / 被抽 experiment 数,验证假设。

---

## 2026-04-23 — AlexNet (ImageNet Classification)

- `paper_id: 2315fc6c2c0c`
- `pdf: ImageNet classification with deep convolutional neural networks.pdf` (9 p, 1.4MB)
- `wall: 16.1s  |  cost: ¥0.0309  |  in=14515 out=1868 cache_read=0`
- PDF 总量 ≈ 35k chars ≈ **8.8k tokens**。in=14515 **> PDF tokens**——
  本篇 Skim+Deep 肯定看到了全文。佐证 LeNet 的"半篇丢失"不是通病,
  是**长文特定 bug**。
- 抽取数量:6 contributions / 5 methods / 6 experiments / 3 limitations。

### Issues

- **[BUG - SEVERE] arxiv_id 幻觉成另一个著名论文的 id。**
  `meta.arxiv_id = "1706.03762"`——**这是 Vaswani 17 "Attention Is All
  You Need" 的 arxiv id**,不是 AlexNet 的。AlexNet 是 NIPS 2012,
  根本没有 arxiv 版(原版只有 NIPS pdf)。`meta.id` 也被污染成同一个值。
  → 这比 LeNet 的 `cs/9807034`(编一个看似合理的旧式 id)**严重得多**。
  这次 LLM 幻觉出了**另一篇真实论文**的 id——指向正确格式的、真实存在的、
  但完全错的 paper。
  - 用户如果点 arxiv 链接会到 Transformer 页面,极度误导。
  - 证据:PDF 里不含"1706.03762"字符串(可 `pdftotext | grep` 验证)。
  - **M8 最紧急**:Skim 的 `arxiv_id` 字段必须改 prompt——"只从 PDF
    文本抽取,不允许推断",或者直接关掉让外部工具(arxiv API)补。

- **[BUG] LLM 主动标注"not stated but likely"注入自造 limitation。**
  Limitation #3 原文:
    ```
    [method] Not stated but likely: The reliance on specialized GPU
    hardware and high computational cost may limit accessibility for
    researchers without significant resources.
    ```
    LLM **显式声明**这条是它的推断。`Limitation` schema 只要求"抽取
    论文自述的局限",不该允许 LLM 编。description prompt 需要加强。
  - M8 action:在 `Limitation` 的 `description` field 加 "only include
    limitations explicitly stated or strongly implied by the paper's own
    authors; do not add limitations the reader might think of"。

- **[BUG-repeat] "low-resource languages" 第 3 次命中。**
  Limitation #2: "English-language **visual data** (ImageNet); transfer
  to other domains or **languages** is not evaluated"。
  → **3/5 papers**。AlexNet 为了套 "languages" 还生造了 "English-language
    visual data" 这个奇怪短语。ImageNet 是图片,没语言。
    模板 overfitting 程度极深。**M8 最高优**,第 4 次出现前必须改。

- **[BUG] Experiment 渲染 `f"{value}{unit}"` 无空格。**
  ```
  top-1 error rate reduction: 1.7points vs single-GPU net ...
  top-5 error rate reduction: 1.2points vs single-GPU net ...
  ```
  `unit = "points"` (应该是 "pp" or "percentage points"), 但**更明显**
  的是 `1.7points` 没有空格。markdown 模板的 `f"{v}{u}"` 应该是
  `f"{v} {u}"`。小 UX bug 但每次都刺眼。

- **[SMELL-repeat] Confidence 6/6 全 1.0。** 和 ResNet 一样。累积 5 篇
  (4, 5, 5, 5, 6 条 contributions),confidence 从未出现 < 0.9 的值。
  数据量够了,M8 优先级 = DELETE or REDESIGN。

- **[SMELL] Methods 5 条有过度拆分嫌疑。** `Multi-GPU Parallel
  Training` 和 `GPU-Optimized Convolution` 基本是**同一件事**
  (Krizhevsky 的 cuda-convnet 就是为了多 GPU 训练做的优化),paper
  里也没按这两条分节。Deep 把它们拆成 2 个 Method,novelty 描述内容
  也有重叠。
  - 非硬 bug,但加上 LeNet 的"把 backprop 当 method",两条线指向
    **Method schema 的粒度和排他性约束都太弱**。

### What went well

- **Experiments 覆盖好**:6 条,包含 headline LSVRC 2010/2012、ReLU 6x
  speedup、多 GPU split 1.7/1.2 pp 提升。LeNet/FaceNet 的低覆盖率
  **在短文上不出现**,再次指向长文 content-feeding bug。
- ReLU / dropout / GPU split 三个 method 的 novelty 描述都贴合历史事实
  (没像 LeNet 那样说成"本篇发明 backprop")。
- 16.1s / ¥0.031——5 篇里最便宜。

---

## 累积频次(跑完 5 篇)

| 问题 | 5 篇内命中 | 变化 |
|---|---|---|
| Confidence 刻度废 | 5/5 | 从未失效 |
| `meta.id` vs `arxiv_id` 混淆/重复 | 5/5 | 从未失效 |
| `arxiv_id` 真幻觉(编出**真实**错论文 id) | **1/5** | **新-AlexNet,最危险** |
| `meta.id` 幻觉 arxiv id | 2/5 | LeNet + AlexNet |
| "low-resource languages" 幻觉 | 3/5 | FaceNet/LeNet/AlexNet,趋稳 |
| 非数值 experiment 塞入数值 schema | 2/5 | ResNet/LeNet |
| Experiments 覆盖不均(3 vs 6-8) | 2/5 | FaceNet/LeNet,都是"未充分喂文"嫌疑 |
| Method schema 无 "novel to paper" 闸门 | 2/5 | LeNet 把 backprop 当 method, AlexNet 拆 GPU 成 2 条 |
| LLM 主动标"not stated but likely"注入自造 | **1/5** | **新-AlexNet** |
| unit 拼接无空格 | 1/5 | AlexNet 首次明显 |
| session.jsonl 缺 per-call cost/latency | 5/5 | 从未失效 |
| Deep 看到 < 一半 PDF | 1/5 | LeNet 唯一,**未复现**(AlexNet 短文正常) |

**AlexNet 升级了"最严重 bug"**:arxiv_id 从"null or 自造格式"升级到
"真实存在的别的著名论文的 id",是用户**信任代价最高**的一类错误。
M8 要把 `arxiv_id` 的保守度拉到最高(只抽 PDF 可见字符串)。

---

## 2026-04-23 — In Defense of the Triplet Loss (ReID)

- `paper_id: c2c0252624f0`
- `pdf: In defense of the triplet loss for person re-identification.pdf` (17 p, 8.0MB)
- `wall: 11.4s  |  cost: ¥0.0267  |  in=13447 out=1462 cache_read=0`
- PDF 65k chars ≈ **16.2k tokens**;in=13447 → **覆盖 ~83%**。
  LeNet 是 50%,本篇 83%,AlexNet(9p)是 >100%。
  **长度与内容丢失明显相关**,半定量指标成型。
- 抽取数量:5 contributions / 3 methods / 3 experiments / 3 limitations。

### Issues

- **[BUG - 混合渲染] 终端输出把 display-math 里的 `_xxx_` 当 italic 吞掉。**
  同一条公式三个位置三种结果:
  | 层 | 内容 |
  |---|---|
  | JSON (session.jsonl) | `\\mathcal{L}_{BH}(\\theta; X) = \\sum_{i=1}^{P}` ✓ |
  | report.md 原始 | `$$\mathcal{L}_{BH}(\theta; X) = \sum_{i=1}^{P}$$` ✓ |
  | 终端(CLI stdout) | `$$\mathcal{L}{BH}(\theta; X) = \sum{i=1}^{P}$$` ✗ |
  → 终端用 rich 渲染 markdown,把 `_xxx_` 当 italic markup 剥掉。
    display-math `$$...$$` 里不该再二次解析。这不影响**存盘**但影响
    用户直接从终端复制公式。
  - 修:CLI 渲染 display-math 时禁用 rich 的 markdown inline parsing,
    或 wrap 公式为 rich `Text` 原样输出。

- **[BUG] `key_formula = 'None'` 字符串被渲染成 `$$None$$`。**
  Plain CNN with Triplet Loss 这个 method 没公式,LLM 把 `key_formula`
  填成字符串 `"None"`(不是 JSON `null`),markdown 模板无判断,
  包成 `$$None$$` 写进 report.md。
  - 两处 fix 选一:(a) prompt 强调"无公式时返回 JSON null,不要写
    字符串 None/N/A/-" ;(b) 模板跳过 `key_formula in (null, "", "None", "N/A")`。
    两个都做更稳。

- **[BUG-repeat] "Not stated but likely:" 第 2 次出现。** Limitation #3:
  "Not stated but likely: Training stability can still be sensitive to
  hyperparameters ...". AlexNet + 本篇 = 2/6 papers 命中。
  前一篇猜可能是单次,本篇印证**是模式**。M8 优先级同 HIGH。

- **[SMELL] Experiments 全 `value: null`,丢失具体数值。**
  3 条 experiments 分别对应 Market-1501 / CUHK03 / MARS,全写成:
    ```
    { "dataset": "...", "metric": "mAP / Rank-1 accuracy",
      "value": null, "raw": "State-of-the-art results on ... dataset" }
    ```
    原文 Table 里明明有具体 mAP 和 Rank-1 数字(paper 截止 2017 在
    Market-1501 应该是 ~81 mAP / ~86 Rank-1)。可能有两原因:
    1. 一个 Experiment 被填了两个 metric(`"mAP / Rank-1 accuracy"`),
       schema 的 `value: float` 容不下两个值,LLM 选择填 null;
    2. 长文内容 feeding 82% 覆盖,Results 表格这部分可能掉进没 feed 的
       18% 里。
  - 验证:dump Deep 实际输入,看 Section 5 / Table 1 是否到达。
  - M8 action 二选一:allow `metric` 和 `value` 成对数组(一 exp 多 metric),
    或强制每个 metric 拆成独立 exp。

- **[SMELL] Method description 重复 name。** 3 个 method 的 `description`
  都是 "Batch Hard Triplet Loss: Instead of ..." —— 冒号前复读一遍 name。
  JSON 里 name 已经是单独字段,description 再写一次是冗余。可能 LLM
  复制 paper section title 做开头。
  - 软 issue,但用户每次都要跳过那句"Xxxxxx: ...",读感磕绊。
    M8 prompt 加一行 "description 不要重复 name"。

- **[SMELL-improved] Confidence 首次出现 0.95。** [1.0, 0.9, 1.0, 1.0, **0.95**]。
  前 5 篇从未见过 0.9/1.0 以外的值,本篇出 1 个 0.95。不算解决,但
  数据点多了。把 30 条 contributions(跨 6 篇)汇总:
    - 1.0 × 25 条 (83%)
    - 0.9 × 4 条  (13%)
    - 0.95 × 1 条  (3%)
    - 其他 × 0 条
  仍属于"高端二值 + 极少中间值",刻度没用起来。

### What went well

- **arxiv_id `1703.07737` 正确**,是本篇的真 id(和 AlexNet 的幻觉
  `1706.03762` 做对照——真 preprint 就抽对,没 preprint 的
  (AlexNet/LeNet)就胡编)。
- Batch Hard / Batch All 两个 triplet 变体的**公式完整准确**,JSON
  里 LaTeX escape 规范(没出现 `\t` 吞字 bug),关键复杂公式 qwen
  能稳定输出。
- Contributions 里"challenging pre-trained models are necessary"那条
  把 paper 的**反共识立场**抽出来了,没有滑成通用套话。
- 最快一篇(11.4s)、最便宜一篇(¥0.0267)。17 页只 11s,意味
  着 Skim/Deep 的 I/O 开销不大,主要时间在 LLM 调用本身。

---

---

## 2026-04-24 — Bahdanau (NMT by Jointly Learning to Align and Translate)

- `paper_id: 071b16f25117`
- `pdf: Neural machine translation by jointly learning to align and translate.pdf` (15 p, 50k chars, ≈12.5k PDF tokens)
- `wall: ~18s  |  cost: ¥0.0869 (最贵)  |  in=59602 out=2132 cache_read=0`
- Per-step latency(session 时间戳):Skim 8s,Deep 10s。
- 抽取数量:4 contributions / 4 methods / **2** experiments / 3 limitations。

### Issues

- **[BUG - SEVERE - ROOT CAUSE] Deep 输入 section 重复喂入。**
  Deep user message **182025 字符**,但 PDF 原文只 50151 字符 → **3.6x
  膨胀**。逐 section dump 后对照:
    | 父 section chars | 唯一子 section chars | 差 |
    |---|---|---|
    | `2 Background` 7207 | `2.1 RNN Encoder–Decoder` 7190 | 17 |
    | `3 Learning...` 6829 | `3.1 Decoder` 6828 | 1 |
    | `4 Experiment Settings` 7150 | `4.1 Dataset` 7140 | 10 |
    | `5 Results` 8888 | `5.1 Quantitative Results` 8903 | -15 |
    | `6 Related Work` 7949 | `6.1 Learning to Align` 7956 | -7 |
    | `A Model Architecture` 5261 | `A.1 Architectural Choices` 5266 | -5 |
    | `B Training Procedure` 7070 | `B.2 Training` 7062 | 8 |
    父节的 content 已经包含全部子节文字,子节又被当成独立 section 再贴
    一次。三层嵌套(如 `A.1 → A.1.2`)放大更狠。
  - **这重写了之前"长文 feeding 丢失"(Triplet/LeNet)的归因**:不是
    喂不够,是内容被算 2-3 次,budget 先被自己吃空。Triplet 17p ratio
    0.83、LeNet 46p ratio 0.50 的"覆盖不足"可能就是这个 bug + token cap
    的联合结果——父 section 先吃满 budget,后半部 leaf section 掉进
    未喂入区。
  - 验证方法:加日志在 Deep 调用前 dump 每个 section chars + 是否 leaf,
    对 sum(leaf_chars) vs sum(all_chars) 做二选一断言。
  - 修:`retrieval/sections.py`(或 `agents/main.py` 的 concat 逻辑)
    只 emit leaf section,或 parent-only(不下钻)。不要同时给 2 份。

- **[BUG-repeat] Method schema 无 "novel to this paper" 闸门。** 4 个
  method 里第 1 个 `RNN Encoder-Decoder (basic)` 的 novelty 直接写:
  "This is the baseline method from Cho et al. (2014a) and Sutskever et
  al. (2014), which the paper contrasts against. It does not have an
  attention mechanism." ——**LLM 自己都承认不是本篇贡献**,schema 仍
  强制它填一个 Method 条目。3/7 命中(LeNet backprop / AlexNet GPU 拆分 /
  Bahdanau basic enc-dec)。M8 优先级对齐 triage #5。

- **[BUG-repeat] `meta.id` 带 `arXiv:` 前缀 + `arxiv_id=null`。**
  `meta.id = "arXiv:1409.0473v7"`(Bahdanau 真 arxiv id 确是 1409.0473),
  `arxiv_id` 字段 null。6/7 继续命中。triage #4 结构性。

- **[SMELL-repeat] Experiments 只 2 条,`value: null`,raw 塞两套数字。**
  原文 Table 1 有 4 models × 2 conditions (All / No UNK),本该 8 个
  数据点。现在被捏成 2 条 experiment:
    ```
    metric: "BLEU", value: null,
    raw: "RNNsearch-50: 26.75 (All), 34.16 (No UNK);
          RNNencdec-50: 17.82 (All), 26.71 (No UNK)"
    ```
  和 Triplet Loss 同病:一个 Experiment 多 metric/多 baseline,value:float
  容不下 → LLM 填 null、真数据掉进 raw 字符串。渲染层拿到 `n/a vs X`,
  数值丢失。不是 token 压力(out=2132,ceiling 71%),是 schema 表达力
  不够。M8 action:allow `metric` / `value` 成对数组,或强制拆 row 为
  独立 experiment。

- **[SMELL-improved] Confidence 首次 4 值共存**:[1.0, 0.9, 0.95, 0.8]。
  `0.8` 第一次出现,落在最弱 claim("alignments linguistically plausible
  and agree with human intuition")——方向对。但 7 篇 34 条 contribution
  分布仍是 25×1.0 / 4×0.9 / 2×0.95 / **1×0.8** / 0×其他。高端二值 +
  极少中间值,刻度仍未用起来,只是松动了一点。

### What went well

- arxiv_id 字面(`1409.0473`)从 PDF 直接抽到,放在 `meta.id` 里,内容
  真实无幻觉(对照 AlexNet `1706.03762` severity case)——再次印证
  "PDF 上印了就抽对,没印就编"。
- 4 个 method 的 key_formula 全齐 ($h_j$ BiRNN / $\alpha_{ij}$ softmax /
  $e_{ij}$ tanh),`\alpha/\tanh/\top/\overrightarrow` 等 LaTeX macros
  在 JSON 转义都 OK,没出现 Bag of Tricks 那种 `\times → tab` 事故。
- Conclusion 抓到"未来扩展 vocabulary / sub-word"方向,不是套模板;
  limitation 里 `O(T_x * T_y)` complexity 是论文里确实有的段落(不是
  LLM 推断),未出现 "Not stated but likely" 注入。
- wall 18s / ¥0.087,相对 in=59.6k 的 3.6x 膨胀**已经算快**——若修掉
  section 重复,这篇预计 ≈ ¥0.025,省 70%。

---

---

## 2026-04-24 — HGNN (Hypergraph Neural Networks)

- `paper_id: 510d98681e5e`
- `pdf: Hypergraph Neural Networks.pdf` (9 p, 35.8k chars, ≈9k PDF tokens)
- `wall: 13s  |  cost: ¥0.0628  |  in=41851 out=1751 cache_read=0`
- Per-step latency:Skim 3s,Deep 10s。
- 抽取数量:7 contributions(2×novel_method + 1×novel_theory + 4×novel_result)
  / 2 methods / 4 experiments / 3 limitations。

### Issues

- **[SMELL-worst-yet] Confidence 7/7 全 1.0。** 第一次全样本打满,样本量
  还比 ResNet/AlexNet 的 6/6 大。累积 8 篇 41 条 contribution:
  33×1.0 / 4×0.9 / 2×0.95 / 1×0.8 / 0×其他(<0.8 仍为 0)。triage #6
  优先级再拉高。

- **[BUG-repeat] Deep 输入 3.3x section 嵌套膨胀。** Deep text 117703
  chars vs PDF 35803 chars = **3.29x**。in=41.9k token vs PDF 9k token
  = **4.66x**,9 页短论文居然超过 AlexNet(9p,1.65x)快 3 倍。原因是
  HGNN 的 Methods 节有 4 个子节 + Experiments 节有 2 个子节,嵌套
  scales with depth × width,不是 page count。Bahdanau 根因再命中:
    | parent | chars | sibling children chars |
    |---|---|---|
    | `Related Work` 7856 | `Hypergraph learning` 7863 / `Neural networks on graph` 7868 | 各自 ≈ parent |
  triage #2 第 2 次独立命中。

- **[BUG-repeat] `meta.id="arXiv:1809.09401v3"` 带前缀 + `arxiv_id` 缺失。**
  8/8 命中。triage #4 结构性。

- **[SMELL-lite] Method 可能过度拆分。** 2 个 method:
  `hyperedge convolution` 和 `Chebyshev polynomial approximation for
  hypergraphs`。前者是后者的**形式化**结果(论文先推 Chebyshev 近似,
  再把得到的 filter 叫做 hyperedge convolution),不是两个独立方法。
  novelty 描述也高度重合("避免 eigendecomposition" / "高阶相关性建模")。
  和 AlexNet "Multi-GPU + GPU-Optimized Conv" 拆分同构,但比 AlexNet 轻
  (至少两者数学形式不同一行)。

- **[SMELL-lite] Experiment comparison_baseline 挤一栏。** 每条 exp 的
  baseline 写成 `"GCN, Planetoid, Chebyshev, DeepWalk"`,只有本方法值
  (81.6%),没有各 baseline 的对比数。Table 里 baselines 和本方法是
  并列的数值点,应每个 baseline 拆独立 exp,或把 `comparison_baseline`
  改成数组(对象数组)带各自数值。

### What went well

- **首次出现 `novel_theory` tag**("GCN 是 HGNN 的 2-ary 特例")。前 7 篇
  `contribution_type` 只见过 `novel_method` / `novel_result`。证明 schema
  的 enum 在有合适刻度的论文上**能用起来**,刻度本身不是僵死的。HGNN
  算 schema 的一个正面样本。
- **Experiments 有具体数值**(81.6 / 80.1 / 96.7 / 84.2),和 Bahdanau/
  Triplet 的 `value: null` 形成对照——HGNN 每条 exp 只 1 metric + 1 value,
  schema 能放下。验证"一个 exp 多 metric → null"的成因是 schema 表达力
  而非 LLM 抽取能力。
- **Limitations 无模板幻觉,且质量高。** Limitation #1 抓到论文自己承认
  的"citation 网络 gain 小因为生成的超图结构和原图差不多"——这是论文
  discussion 原话,抽取忠实。`[scope]` 里 "social media text / bioinformatics"
  是 HGNN 真实潜在方向,没有套 "languages" 模板。这是 8 篇里第一次 limitation
  完全 clean。
- **venue=null 合理**:PDF 首页无 AAAI 2019 标记(学校 + 邮箱 + abstract
  直接开始),LLM 没编。对照 LeNet venue=`Proceedings of the IEEE` 抽对,
  再次印证"有印就能抽,没印就 null"的稳定行为。

---

## 2026-04-24 — Zhou 2006 (Learning with Hypergraphs, NIPS)

- `paper_id: 9f53740cc80e`
- `pdf: NIPS-2006-learning-with-hypergraphs-clustering-classification-and-embedding-Paper.pdf`
  (8 p, 28.5k chars, ≈7k PDF tokens, **无 embedded outline**)
- `wall: ~10s  |  cost: ¥0.0217  |  in=11200 out=1143 cache_read=0`
- 抽取数量:5 contributions / 4 methods / **2 experiments(全假)** /
  2 limitations(1 假 + 1 "Not stated but likely" 自造)。

### Issues

- **[BUG - SEVERE - ROOT CAUSE OF LONG-TAIL LOSS] Skim 只见首 3 页,
  后半论文不存在。** 直接证据链:
    1. `skim.py:38` 硬编码 `_FRONT_MATTER_PAGES = 3`
    2. Zhou 2006 PDF 无 bookmarks → `front_matter.outline is None` 分支
    3. Skim 被告知"推断 section 结构",输入只有前 3 页文字
    4. Skim 忠实地 emit 4 个 section,最末 page_end=3(Abstract / 1 Intro /
       2 Preliminaries / 3 Normalized hypergraph cut)——论文真正的 section
       4/5/6/7 + Experiments + Conclusions **完全不在 outline 里**
    5. Deep 按 outline 取 section → Deep input 只有前 3 页的 17852 chars,
       后 5 页 10708 chars **从未进入 LLM**
  - 下游症状:Experiments 字段里抓的是**Abstract 里那句"Our experiments
    on a number of benchmarks showed the advantages of hypergraphs over
    usual graphs."**——没有数据,只有概述。Limitations 里 LLM 直接承认
    "The provided text snippet does not explicitly list limitations",
    然后强行编造。
  - 影响面:任何无 embedded outline 的 PDF。老 NIPS (06 及更早多数)、
    老 ICML、扫描版会议集、不含 `\usepackage{hyperref}` 的 arxiv 投稿。
    9 篇里第 1 次命中,但这是**类别型**命中——遇到就 100% 坏,不遇到
    就 0% 坏。
  - 修:M8 候选(a) 放开 `_FRONT_MATTER_PAGES` 覆盖整篇(需要考虑 Skim
    token 成本和 system prompt 对 Skim 任务窄化的影响);(b) 无 outline
    时走不同路径:基于 font-size 统计 / regex `^\d+\s+[A-Z]` 全文扫 heading
    做 outline 推断,然后再走 Skim。这是 M8 优先级最高的一条,比 section
    重复更致命——section 重复是"多喂了",这个是"没喂"。

- **[BUG] `meta.id = "cs/0406013"` 很可能是幻觉。** `cs/0406013` 对应
  2004-06 提交(cs/YYMM### 格式),Zhou 2006 NIPS 论文投稿肯定在 2006,
  时间不吻合。复刻 LeNet `cs/9807034`、AlexNet `1706.03762` 的老模式:
  真实论文没 arxiv 版 → LLM 按格式编。`arxiv_id` 字段仍 null(没被污染)。
  triage #2 再次命中,且每次命中都是**不同老论文**,非偶发。

- **[BUG-repeat] "Not stated but likely:" 第 3 次出现。**
  Limitation #2 字面写"[scope] Not stated but likely: The approach assumes
  connected hypergraphs..."。AlexNet / Triplet Loss / Zhou 三次命中。
  本篇上下文特殊:前半论文缺失导致 LLM 没数据源,被逼编——这种"上游
  无输入"的场景 M8 还要专门处理(例如告诉 Deep 若 section 覆盖不足则
  限定 limitations 为 empty list,不要凑)。

- **[SMELL] Limitation #1 自相矛盾地透露了 bug**:
  `"The provided text snippet does not explicitly list limitations, but
  typically spectral methods scale poorly with the number of vertices..."`
  LLM 自己承认没读到 limitation 原文,然后按"经验"填一条。这应该是
  schema 拒绝的:`Limitation.description` 本意是"论文自述",LLM 把自己
  的教科书常识塞进去。M8 的 Limitation prompt 加"若论文未明说请返回空
  列表,不要补"。

- **[SMELL-repeat] Confidence 5/5 的第 1-4 条全 1.0,第 5 条 0.8。**
  模式和 Bahdanau 一致:前 N 条方法 claim 全满打,最末那条 experiment
  归纳打 0.8。9 篇 46 条累积:38×1.0 / 4×0.9 / 2×0.95 / 2×0.8 / 0 其他。

### What went well

- 前 3 页被喂入的部分(Methods 的 hypergraph normalized cut / Laplacian /
  embedding / transductive classification 四个 method)抽取**质量很高**,
  novelty 描述精准(例如明确说"generalizes the simple graph normalized
  cut [Ng et al.] ... rather than reducing hypergraphs to cliques"),
  公式完整($\text{argmin}_S \text{vol}\partial S / ...$ 一字不差)。
  → 一旦 outline 完整,Deep 在老论文上表现也没问题。bug 的位置明确。
- `meta.venue=null` 合理(NIPS 2006 论文首页确实没印会议名,只有"NIPS"
  文件名给线索,而 Skim 不看文件名)。
- cost ¥0.022 是 9 篇**最便宜**——因为 input 被截了一半……典型的"便宜
  的数据是假的"。

---

## 2026-04-24 — Inception v3 (Rethinking the Inception Architecture, Szegedy 15)

- `paper_id: 445d06b2ac99`
- `pdf: Rethinking the Inception architecture for computer vision.pdf`
  (10 p, 41.5k chars, ~10.4k PDF tokens, **有 embedded outline**)
- `wall: ~13s  |  cost: ¥0.0546  |  in=32951 out=2098 cache_read=0`
- 抽取数量:6 contributions / 5 methods / 5 experiments / 3 limitations。

### Issues

- **[BUG-repeat] `meta.id = "1512.00567"` + `arxiv_id` 缺失。** 10/10
  仍是 schema 结构性 bug。Inception 这次不带 `arXiv:` 前缀,和 ResNet
  (`"1512.03385"`) 一致;FaceNet(`"1503.03832"`)也不带。带前缀 vs
  不带前缀在 10 篇里**约各半**,完全随机。triage #4 结构性。

- **[SMELL-light] Experiment #5 过度抽取。** `value=76.6, metric="top-1
  accuracy", comparison_baseline="none"`——这是 Section 9 "Performance
  on Lower Resolution Input" 里对 299×299 baseline 的单点描述,**不是
  独立实验**,而是后续 79×79 / 151×151 对比的基准 context。被抽成了
  第 5 条 exp,但没 baseline 对比、属于悬空的绝对值报告。
  M8 候选:在 Experiment 的 description 加"只抽真正有 baseline 对比的
  数据点;单独报告的绝对 accuracy 归到 contribution(novel_result)"。

- **[SMELL-repeat-lite] Section 3 嵌套重复。** 只一处嵌套(section 3 /
  3.1 / 3.2),ratio 仅 2.11x,是 HGNN (4.66x) / Bahdanau (4.77x) 的一半。
  验证"膨胀率随嵌套 depth × width"假设:Inception 只 1 个嵌套父节 vs
  HGNN 2 个 + Bahdanau 5+ 个。这是个**架构性上限**信号——即使完美的
  扁平论文,2x 以下膨胀可能就是 concat 的自然开销。

### What went well

- **[BIG] Confidence 首次出现 0.7,且 calibration 正确。**
  6 条 `[1.0, 1.0, 0.8, 1.0, 1.0, 0.7]`。关键是 LLM **跟着论文自身的
  hedge 措辞在打分**:
    - `0.7` 给"79×79 resolution 仍能高精度"——Section 9 论文原话
      "we postulate";
    - `0.8` 给"auxiliary classifiers as regularizers"——论文用
      "we argue";
    - `1.0` 给硬 ImageNet 数据(21.2% / 5.6% / 3.5% / 17.2%)。
  对照 HGNN 7/7=1.0 失效(因为 HGNN 通篇陈述式),Inception 说明
  confidence 字段**在论文 epistemic 结构清晰时能用**。M8 可能不需要
  删字段,而是加一段 description 提示 LLM"跟着作者 hedge(we postulate
  / may / likely)调低"。

- **Limitations 3 条全真。** 第 1 条抓到论文开头的"design principles
  are speculative and require future experimental evidence"——这是
  Szegedy 自己写在 General Design Principles 段落末的**免责声明原文**,
  不是 LLM 补的。3 条里 0 "low-resource languages"、0 "Not stated but
  likely:"——干净。

- **5 个 Methods 全是 novel-to-paper**:factorized conv / asymmetric
  conv / label smoothing / BN auxiliary classifiers / efficient grid
  reduction。没 LeNet-style 背景技术当 method 的问题——论文本身 method
  层次清晰,schema 能发挥。

- **venue = null 合理** (Inception v3 是 CVPR 2016, PDF 首页只有
  `arXiv:1512.00567`,未印 CVPR 标签)。

- 10 篇里**最"干净"的一篇**:confidence 刻度用上了、limitations 无幻觉、
  methods 无 backprop 问题、outline 完整、膨胀最低。不是 Inception 最
  容易(不是最简短,不是最现代),而是**论文结构 + 作者措辞清晰**时,
  现有 pipeline 基本 work。Inception 几乎是 M7 baseline 的上限表现。

---

## 累积观察(13 篇)

**长度-膨胀率 + 覆盖完整性**表。后 3 篇(Transformer/ViLBERT/ViT)是
M7 reality-check,在 2026-04-24 通过静态分析 session.jsonl 补入;其
`in (Skim+Deep)` 数是估算(`(skim_msg + deep_msg) chars / 4`,session
未记真实 usage,对应 triage #10):

| paper | PDF pages | PDF tokens | in (Skim+Deep) | ratio | outline? | 覆盖问题? |
|---|---|---|---|---|---|---|
| AlexNet | 9 | 8.8k | 14.5k | 1.65 | yes | 无 |
| FaceNet | 9 | ~12k | 24.0k | ~2.0 | yes | 3 条 exp(疑) |
| Bag of Tricks | 10 | ~16k | 22.0k | 1.38 | yes | 无 |
| ResNet | 12 | ~25k | 35.9k | 1.44 | yes | 无 |
| Triplet Loss | 17 | 16.2k | 13.4k | **0.83** | yes | exp 全 null |
| LeNet | 46 | 66.3k | 33.3k | **0.50** | yes | 仅 3 exp |
| **Bahdanau** | 15 | 12.5k | 59.6k | **4.77** | yes | 2 exp + null |
| **HGNN** | 9 | 9k | 41.9k | **4.66** | yes | 无 |
| **Zhou06** | **8** | **7k** | **11.2k** | **1.60** | **no** | **后 5 页全丢** |
| **Inception v3** | 10 | 10.4k | 33.0k | 3.17 | yes | 无 |
| Transformer ⁺ | 15 | 9.9k | ~25.2k | ~2.55 | yes | 无 |
| ViLBERT ⁺ | 11 | 11.3k | ~29.4k | ~2.60 | yes | 无 |
| ViT ⁺ | 22 | 16.8k | ~55.6k | ~3.31 | yes | 无(30 节含 D.1-D.10 appendix) |

⁺ = M7 reality-check,`in` 是估算。

Zhou06 把故事分成**两个独立失败模式**:
- 有 outline,嵌套深 → Bahdanau/HGNN 的"膨胀型"丢失(重复喂)
- 无 outline → Zhou06 的"截断型"丢失(从未喂)

Zhou06 的 ratio 1.60 看似"正常"(类似 AlexNet 1.65),但正常的假象是
输入只有半本书,后半根本没走 pipeline。**ratio 单指标不足以检测这类
bug**,需要配合"outline section 数 / PDF 页数" 或 "Deep input chars /
PDF chars" 两个辅助指标。

Inception v3 补了"中等嵌套"格:1 个嵌套父节 → ratio 3.17。ratio vs
嵌套父节数的单调关系 13 篇稳定:0 个(AlexNet flat)→ 1.65;1 个
(Inception)→ 3.17;几个(Transformer/ViLBERT 2.5 级)→ 2.5-2.6;
深 appendix(ViT D.1-D.10)→ 3.31;密集嵌套(HGNN/Bahdanau)→ 4.5+。

### Confidence 累积(13 篇,67 条 contributions)

| 值 | 命中 | 占比 |
|---|---|---|
| 1.0 | 53 | 79% |
| 0.9 | 7 | 10% |
| 0.95 | 2 | 3% |
| 0.8 | 4 | 6% |
| **0.7** | **1** | **1%** ← Inception 唯一 |
| <0.7 | 0 | 0% |

高端仍集中(79% 打 1.0)但 Inception 的 0.7 + 正确 calibration 是 13
篇里**唯一证据**说明字段不是完全死的——有前提:论文本身 hedge 措辞
清晰。M8 candidate 不一定是"删 confidence",可以是"prompt 显式指引
跟随作者的 we postulate / may / likely 打折"。

### 累积幻觉/结构性 bug 计数(13 篇)

| bug | 命中 / 13 | 是否类别型(遇到即坏)|
|---|---|---|
| `meta.id` + `arxiv_id` 字段混淆 | 13/13 | 是(schema 结构问题) |
| `arxiv_id` 幻觉成真 id 或老式幻觉 | 3/13 (LeNet / AlexNet / Zhou06) | 是(无 PDF-可见 id 时触发) |
| section 嵌套重复膨胀 | 13/13 有膨胀(程度不同) | 是(随嵌套结构单调) |
| Skim outline 截断(无 bookmarks) | 1/13 (Zhou06) | 是(遇到即 100% 坏) |
| "low-resource languages" 模板幻觉 | 4/13 (FaceNet / LeNet / AlexNet / ViLBERT) | 否(模板复用) |
| "Not stated but likely:" 自注入 | 4/13 (AlexNet / Triplet / Zhou06 / ViLBERT) | 否(LLM 填空习惯) |
| Method schema 无 novel 闸门 | 3/13 (LeNet backprop / AlexNet 拆 GPU / Bahdanau basic enc-dec) | 否(LLM 判断差异) |
| Experiment `value:null` 丢数值 | 3/13 (Triplet 全 null / Bahdanau 2 null / Zhou06 2 假) | 否(schema 表达力) |
| session.jsonl 缺 per-call usage | 13/13 | 是(全局代码 bug) |

**M8 执行顺序建议**:
1. 先修 outline 缺失 fallback(这条影响最大,而且代码定位明确)
2. 再修 section 嵌套重复(Bahdanau 根因)
3. 修完两条后重测 Triplet / LeNet / Zhou06 / Bahdanau / HGNN,看覆盖
   完整性和 ratio 是否都归位
4. 最后再动 schema 层面的 confidence / `meta.id` / Method 闸门等
   (confidence 在 Inception 的正面样本提示"prompt 调优"可能比"删字段"
   更合理)
