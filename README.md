# paper-copilot

本地运行的命令行论文分析工具。给它一个 PDF,产出结构化摘要(贡献 / 方法 /
实验 / 局限)+ 可追溯的 JSONL session + Markdown 报告。

> 项目目标与非目标见 [VISION.md](VISION.md),架构与模块边界见
> [ARCHITECTURE.md](ARCHITECTURE.md)。

## 安装

```bash
git clone <repo-url> paper-copilot
cd paper-copilot
uv tool install .
```

代码改动后重装:`uv tool install . --reinstall`。

## 配置

从 `.env.example` 复制一份到项目根的 `.env`,填入你的 Dashscope(阿里云百炼)API key:

```bash
cp .env.example .env
# 编辑 .env,填 ANTHROPIC_API_KEY
```

`.env` 会从当前 CWD 向上查找 —— 在项目目录或其子目录下跑 `paper-copilot`
就能自动读取。也可以改用 shell 环境变量(`export ANTHROPIC_API_KEY=...`),
优先级更高。

## 用法

```bash
# 单篇深读 → 落 session + Markdown 报告
paper-copilot read <path/to/paper.pdf> [--force] [--lang en|zh]

# 跨论文检索(M10/M11)
paper-copilot list                                    # 列已索引论文
paper-copilot list --year 2023 --field method --contains attention
paper-copilot search "<自然语言查询>" [--year ...] [--k N]

# 重建索引(从已有 session.jsonl)
paper-copilot reindex [--pdf-dir <dir>]               # 加 --pdf-dir 一并重建 embeddings.db

# 两篇并排对比(M13,纯 fields.db,0 LLM 成本)
paper-copilot compare <paper_id_a> <paper_id_b> [--format text|json]

# 观测最近 N 次 session 的 cache 命中率 / latency / cost(M9)
paper-copilot doctor [--n 20]

# Eval(M14)— golden curation + suite 回归
paper-copilot eval mark <paper_id> -f methods -f contributions
paper-copilot eval run eval/suites/smoke.yaml

# Eval 趋势报告(M15 Session A)— 跨多次 run 看 PASS rate / cost / cache trend
paper-copilot eval report [--last N] [--suite NAME] [-o eval/report.html]
```

`read --lang zh` 时,叙述字段(`Contribution.claim` / `Method.description` /
`Method.novelty_vs_prior` / `Limitation.description`)+ Markdown 章节标题
切换为中文;数据集名、metric、数值、作者、enum 值、`Experiment.raw`(原文
引用)等识别/事实字段保留英文原样。

## 输出

```
~/.paper-copilot/                       # 用户运行时数据
├── papers/<paper_id>/
│   ├── session.jsonl                    # 完整流程 trace(可 grep / replay)
│   └── report.md                        # Markdown 报告
├── fields.db                            # SQLite 字段索引(M10)
├── embeddings.db                        # sqlite-vec 向量索引(M11)
├── embeddings_meta.json
└── graph/cross-paper-links.jsonl        # 跨论文关系 append-only(M12)

eval/                                    # 仓库内,纳入 git
├── goldens/<paper_id>_<field>.json      # 单字段 golden 快照
├── suites/<name>.yaml                   # suite 定义
├── runs/<run_id>.jsonl                  # M15 Session A: per-run history(.gitignore)
└── report.html                          # M15 Session A: 趋势报告(.gitignore)
```

`paper_id = SHA1(PDF bytes)[:12]`,同一 PDF 改名或换位置映射到同一 id。

`read` 同时落 fields.db / embeddings.db,后续 `list` / `search` / `compare`
/ `eval` 都基于这两个索引。

## 当前状态(M14 + M15 Session A)

`read` / `list` / `search` / `compare` / `doctor` / `reindex` / `eval`
七个子命令可用,`eval` 含 `mark` / `run` / `report` 三个子命令。
M15 Session A 落 `eval/runs/` per-run 历史 + 静态 HTML 趋势图(零 JS 依赖)。
下一步 M15 Session B(真实模型切换演练 + 退化故事记录)。细节见
[TASKS.md](TASKS.md)。
