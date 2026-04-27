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

```bash
# 单篇深读
paper-copilot read path/to/paper.pdf [--force] [--lang en|zh]

# 列表 / 自然语言检索
paper-copilot list [--year YEAR] [--field FIELD --contains TERM]
paper-copilot search "query" [--year YEAR] [--k N]

# 双论文对比(纯 SQLite 查询,不调用 LLM)
paper-copilot compare <paper_id_a> <paper_id_b> [--format text|json]

# Cache 命中率 / 延迟 / 成本
paper-copilot doctor [--n 20]

# Eval
paper-copilot eval mark <paper_id> -f methods -f contributions
paper-copilot eval run eval/suites/smoke.yaml
paper-copilot eval report [--last N] [--suite NAME] [-o eval/report.html]

# 从 session.jsonl 重建索引
paper-copilot reindex [--pdf-dir DIR]
```

完整命令参考 `paper-copilot --help`。

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
