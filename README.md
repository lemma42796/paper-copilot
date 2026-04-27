# paper-copilot

> 本地论文阅读 agent —— 读 PDF、出报告、留 trace,可检索可对比可回放。

![Python](https://img.shields.io/badge/python-3.12+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Code style](https://img.shields.io/badge/code_style-ruff-purple)
![Packaged with uv](https://img.shields.io/badge/packaged_with-uv-orange)

`paper-copilot` 读取论文 PDF,用 LLM 提取结构化字段(贡献、方法、实验、
局限),输出 Markdown 报告和可追溯的 JSONL trace,并将结果落入本地 SQLite
索引。已索引的论文支持列表筛选、自然语言检索、双论文对比与跨论文关系挖掘。

## 特性

- 三阶段 agent 流水线(skim / deep / related),各自独立的 schema 与 prompt
- Pydantic 结构化输出,字段描述即 prompt,prompt 随代码进 git
- 本地向量检索基于 `sqlite-vec`,单文件部署,不依赖外部向量库
- `doctor` 子命令观测最近 N 次 session 的 cache 命中率、延迟与 token 成本
- Eval 框架:`mark` 标 golden、`run` 跑 suite 回归、`report` 出跨 run 趋势
- 每篇论文一份 `session.jsonl`,完整调用链可 grep 与 replay
- 中英双语输出(`--lang`),事实字段(数据集、metric、引用片段)保留英文

## 快速开始

```bash
# 1. 安装
git clone https://github.com/lemma42796/paper-copilot.git
cd paper-copilot
uv tool install .

# 2. 配置 API key (默认走百炼的 Anthropic 兼容 endpoint)
cp .env.example .env
# 编辑 .env,填入 ANTHROPIC_API_KEY

# 3. 读一篇论文
paper-copilot read path/to/paper.pdf
# → 报告落在 ~/.paper-copilot/papers/<paper_id>/report.md
```

## 环境要求

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- Dashscope(阿里云百炼)API key,默认模型 `qwen3-flash`

## 安装

```bash
git clone https://github.com/lemma42796/paper-copilot.git
cd paper-copilot
uv tool install .
```

代码改动后重装:`uv tool install . --reinstall`。

## 配置

```bash
cp .env.example .env
# 编辑 .env,填入 ANTHROPIC_API_KEY
```

`.env` 沿当前工作目录向上查找。`ANTHROPIC_API_KEY` shell 环境变量优先级
更高。

## 使用

> 全部命令都支持 `--help`;大多数命令支持 `--root PATH` 覆盖
> `PAPER_COPILOT_HOME` 数据根目录(默认 `~/.paper-copilot`)。

### `read` — 深读一篇 PDF

跑完整三阶段流水线(skim → deep → related),把整个调用链写进 `session.jsonl`,
再把结构化字段渲染成 Markdown 报告,同时落进 `fields.db` 与 `embeddings.db`。

```bash
paper-copilot read path/to/paper.pdf
paper-copilot read paper.pdf --force --lang zh
```

- `--force` —— 这篇 PDF 之前已经分析过(`session.jsonl` 已存在)时,强制覆盖重跑
- `--lang, -l en|zh`(默认 `en`)—— 报告语言。叙述字段切换为目标语言,数据集名 / metric / 数值 / 作者 / 原文引用片段保留英文

输出落在 `~/.paper-copilot/papers/<paper_id>/{report.md, session.jsonl}`,
其中 `paper_id = SHA1(PDF bytes)[:12]`。

### `list` — 列已索引论文

从 `fields.db` 读已索引的论文清单,支持按年份或字段子串过滤。纯本地查询,
0 LLM 成本。

```bash
paper-copilot list                                # 全部
paper-copilot list --year 2017
paper-copilot list -f method -c attention         # method 字段含 "attention"
paper-copilot list --format json
```

- `--year, -y INT` —— 按发表年份过滤
- `--field, -f {method,contribution,experiment,limitation}` —— 限制子串匹配的目标字段(单数形式,对应 `fields.db` 的表)
- `--contains, -c TEXT` —— 子串匹配(大小写不敏感),需配合 `--field` 使用
- `--format text|json`(默认 `text`)—— 输出格式

### `search` — 跨论文语义检索

对自然语言 query 做向量检索(sqlite-vec),返回最相关的 top-k 篇论文。可用
`--field` / `--contains` 先做子串预筛,再在子集上跑向量召回。

```bash
paper-copilot search "attention without softmax"
paper-copilot search "residual connection" --k 5 --year 2016
paper-copilot search "vision transformer" -f method -c attention
```

- `--year, -y INT` —— 仅在该年份的论文中搜索
- `--field, -f` / `--contains, -c` —— 子串预筛,字段集同 `list`
- `--k INT`(默认 `10`)—— 返回 top-k

### `compare` — 双论文并排对比

直接读 `fields.db` 把两篇论文的字段拼成对比表。**纯 SQLite 查询,0 LLM 成本**,
适合写综述时快速对照两篇 baseline。

```bash
paper-copilot compare 2c03df8b48bf 2315fc6c2c0c
paper-copilot compare 2c03df8b48bf 2315fc6c2c0c --format json
```

- `--format text|json`(默认 `text`)—— 输出格式

`paper_id` 从 `paper-copilot list` 的输出获取。

### `doctor` — Cache / 延迟 / 成本观测

扫描最近 N 次 session 的 `session.jsonl`,汇总 prompt cache 命中率、端到端
延迟、token 消耗与人民币成本。换模型 / 调 prompt / 评估 cache 策略时主要靠它对比。

```bash
paper-copilot doctor               # 最近 10 次
paper-copilot doctor --n 50
paper-copilot doctor -f json       # 接 jq 之类
```

- `--n, -n INT`(默认 `10`)—— 最近多少次 session
- `--format, -f text|json`(默认 `text`)—— 输出格式

### `eval` — 回归与趋势

三个子命令构成一条评估闭环:

- `mark` — 把某篇论文当前的字段结果钉成 golden 快照
- `run` — 在一个 suite 上重跑流水线,逐字段比对 golden,输出 PASS/FAIL,并把这次 run 追加到 `eval/runs/`
- `report` — 把多次 run 渲染成 HTML 趋势图(PASS rate / cost / cache 命中率)

```bash
# 钉 golden(选哪些字段做基准)
paper-copilot eval mark 2c03df8b48bf -f methods -f contributions

# 跑回归 suite
paper-copilot eval run eval/suites/smoke.yaml

# 渲染跨 run 趋势 HTML
paper-copilot eval report --last 10 -o eval/report.html
```

`mark -f` 合法字段:`meta`、`contributions`、`methods`、`experiments`(deep-output
顶层结构,**复数形式**,与 `list -f` 的字段集不同),可重复传 `-f`。

`run --no-record` 跳过把这次 run 写进 `eval/runs/`(临时调试时用,正常应该让
`report` 看到)。

Suite YAML 形如:

```yaml
name: smoke
papers:
  - paper_id: 2c03df8b48bf
    pdf: /path/to/paper.pdf
    fields: [methods, contributions]
budget_per_paper:
  cost_cny: 0.20
  latency_s: 180
```

`report` 还有 `--suite NAME` 只画特定 suite,`--last, -n INT` 只画最近 N 次。

### `reindex` — 从 session 重建索引

从 `~/.paper-copilot/papers/*/session.jsonl` 反向重建 `fields.db`(以及
`embeddings.db`,如果传了 `--pdf-dir`),用于误删索引或换机器迁移数据。

```bash
paper-copilot reindex                              # 只重建 fields.db
paper-copilot reindex --pdf-dir ~/papers           # 同时重建 embeddings.db
```

- `--pdf-dir PATH` —— 含原始 PDF 的目录;**只有传了它才会重建 embeddings.db**(向量索引依赖原文重新切块,光看 session.jsonl 不够)

完整 flag 列表见 `paper-copilot <command> --help`。

## 目录结构

```
~/.paper-copilot/                       # 用户运行时数据
├── papers/<paper_id>/
│   ├── session.jsonl                   # 完整调用链 trace
│   └── report.md
├── fields.db                           # SQLite 字段索引
├── embeddings.db                       # sqlite-vec 向量索引
├── embeddings_meta.json
└── graph/cross-paper-links.jsonl       # 跨论文关系,append-only

eval/                                   # 仓库内
├── goldens/<paper_id>_<field>.json
├── suites/<name>.yaml
├── runs/<run_id>.jsonl                 # .gitignore
└── report.html                         # .gitignore
```

`paper_id = SHA1(PDF bytes)[:12]`。同一 PDF 改名或移动位置不影响 id。

## 文档

- [VISION.md](VISION.md) — 项目目标与非目标
- [ARCHITECTURE.md](ARCHITECTURE.md) — 模块边界与数据流
- [TASKS.md](TASKS.md) — 里程碑与实现进度
- [CLAUDE.md](CLAUDE.md) — 工程规约
- `docs/stories/` — 关键技术决策记录

## 许可

MIT — 详见 [LICENSE](LICENSE)。
