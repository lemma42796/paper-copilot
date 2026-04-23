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
paper-copilot <path/to/paper.pdf>
```

**选项**:

| flag | 作用 |
|---|---|
| `--force` | 覆盖已存在的 session(同一 PDF 第二次读时需加) |
| `--lang en\|zh` / `-l` | 输出语言,默认 `en` |

`--lang zh` 时,叙述字段(`Contribution.claim` / `Method.description` /
`Method.novelty_vs_prior` / `Limitation.description`)+ Markdown 章节标题
切换为中文;数据集名、metric、数值、作者、enum 值、`Experiment.raw`(原文
引用)等识别/事实字段保留英文原样。

## 输出

```
~/.paper-copilot/papers/<paper_id>/
├── session.jsonl    # 完整流程 trace(可 grep / replay)
└── report.md        # Markdown 报告
```

`paper_id = SHA1(PDF bytes)[:12]`,同一 PDF 改名或换位置映射到同一 id。

终端同时输出 rich 渲染的 markdown + session/report 路径 + cost 统计。

## 当前状态(M7)

只实现了 `read` 一个子命令。后续 milestone(M10+)会加 `compare` / `search`
/ `list` / `doctor`。细节见 [TASKS.md](TASKS.md)。
