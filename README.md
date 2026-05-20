# Paper Copilot

> 本地优先的论文研究助手：阅读 PDF、检索个人论文库，并基于证据生成可验证的研究笔记和模型框架草案。

![Python](https://img.shields.io/badge/python-3.12+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Code style](https://img.shields.io/badge/code_style-ruff-purple)
![Packaged with uv](https://img.shields.io/badge/packaged_with-uv-orange)

简体中文 | [English](README.en.md)

Paper Copilot 会把一个小规模本地 PDF 论文库变成可检索、可追溯的研究工作区。它可以把论文读成结构化 Markdown 报告，建立字段索引和 chunk 索引，围绕本地论文库回答问题，对比论文，并在预算约束下运行有 trace 的研究循环。

当前产品方向是 **chat-first**：普通用户从一个自然语言输入框开始提问，本地 Python HTTP API 负责运行，Next.js macOS 风格前端负责展示。CLI 仍然保留，用于索引、调试、eval 和脚本化流程。

## 项目状态

状态同步自 `TASKS.md`，更新时间为 2026-05-19：

- CLI 已支持读论文、列论文、检索、对比、重建索引、eval 和成本诊断。
- 本地 HTTP API 已可通过 `paper-copilot serve` 启动；主运行时接口是 `POST /chat`。
- `apps/web/` 已包含当前 Next.js chat shell，支持资料库选择、报告历史、route/status、成本展示和 evidence 查看。
- 当前本地默认测试论文库已有 34 篇论文 / 2066 个 chunks，索引模型为 `text-embedding-v4`。
- paper 级 retrieval seed eval 已达到较高召回：mean `recall@5=98.4%`，`recall@10=100.0%`。
- evidence chunk selection 是当前已知短板：带标签 query 的 mean `evidence_recall@5=53.8%`，`evidence_recall@10=53.8%`。系统经常能找对论文，但不总能把精确答案 chunk 放到前排。

这不是托管 SaaS，不是多用户系统，也不是开放式全自动文献综述 agent。它面向的是大约 50-100 篇论文规模的个人本地知识库。

## 核心能力

- **Chat-first 研究运行时**：把自然语言请求路由到 `knowledge_qa` 或 `framework_composer`，运行有上限的 tool loop，并返回 Markdown 报告、session 路径、成本、终止原因和 paper budget。
- **根据研究方向生成模型框架草案**：围绕用户给定方向，先找 strong baseline，再从本地论文库中找可接入模块，组合成 baseline + modules 的新模型框架建议，并给出兼容性风险、消融实验和证据引用。
- **本地论文阅读流水线**：skim / deep / related agents 提取贡献、方法、实验、局限和跨论文关系。
- **本地 hybrid retrieval**：`fields.db` 元数据过滤、FTS5/BM25、`sqlite-vec` dense retrieval、RRF 融合，以及每篇论文的多 chunk evidence。
- **证据查看**：报告中可以包含可解析 evidence refs；API 和 Web UI 可以回查对应 chunk 原文。
- **SQLite-only 知识库**：目标规模下不需要外部向量数据库。
- **Eval 与可观测性**：字段级 golden regression、retrieval eval、run history、静态 HTML 报告、cache 命中率、延迟和人民币成本统计。
- **可追溯输出**：每次运行都会在 `~/.paper-copilot` 下写 Markdown 和 JSONL session trace。

## 架构

```text
apps/web
  -> local HTTP API
  -> chat.runtime.handle_chat_request()
  -> ResearchAgent bounded tool loop
  -> knowledge stores, paper readers, reports, eval traces
```

主要模块：

| 路径 | 职责 |
| --- | --- |
| `src/paper_copilot/api/` | 面向 Web shell 的本地 stdlib HTTP API |
| `src/paper_copilot/chat/` | 单输入框路由与运行时边界 |
| `src/paper_copilot/agents/` | 论文阅读 agents 与 bounded research loop |
| `src/paper_copilot/knowledge/` | 跨论文字段、embedding 与 hybrid search |
| `src/paper_copilot/retrieval/` | 单篇论文 chunk / section 工具 |
| `src/paper_copilot/eval/` | 回归、retrieval 指标与报告 |
| `src/paper_copilot/session/` | JSONL session 存储 |
| `apps/web/` | Next.js 本地 chat UI |

更多模块边界见 [ARCHITECTURE.md](ARCHITECTURE.md)，chat-first 路线见 [docs/design/chat_first_research_copilot_plan.md](docs/design/chat_first_research_copilot_plan.md)。

## 环境要求

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- Node.js 20+，用于 Web UI
- 模型 provider API key：
  - `ANTHROPIC_API_KEY`：Anthropic-compatible LLM endpoint
  - `DASHSCOPE_API_KEY`：DashScope `text-embedding-v4`

`.env.example` 默认使用阿里云百炼 DashScope 的 Anthropic-compatible LLM API。Embedding 使用 DashScope OpenAI-compatible `text-embedding-v4` endpoint。

## 安装

作为 CLI 工具安装：

```bash
git clone https://github.com/lemma42796/paper-copilot.git
cd paper-copilot
uv tool install .
paper-copilot --help
```

本地开发：

```bash
git clone https://github.com/lemma42796/paper-copilot.git
cd paper-copilot
uv sync --dev
uv run paper-copilot --help
```

`pc` 也注册为 `paper-copilot` 的短别名。

## 配置

```bash
cp .env.example .env
```

编辑 `.env`：

```bash
ANTHROPIC_BASE_URL=https://dashscope.aliyuncs.com/apps/anthropic
ANTHROPIC_API_KEY=sk-your-key-here
DASHSCOPE_API_KEY=sk-your-key-here
PAPER_COPILOT_PDF_DIR=/path/to/your/papers
```

`PAPER_COPILOT_HOME` 控制运行时数据根目录。未设置时，默认写入 `~/.paper-copilot`。

`PAPER_COPILOT_PDF_DIR` 是 chat/research 在需要本地 PDF 时使用的默认论文文件夹。新 clone 后请指向自己的 PDF 目录，并用 `read` 或 `reindex` 建立索引。

## 快速开始

读并索引一篇论文：

```bash
paper-copilot read path/to/paper.pdf --lang zh
```

检索本地论文库：

```bash
paper-copilot search "residual connections for very deep image recognition" --k 5
```

从 CLI 发起一个 bounded research 请求：

```bash
paper-copilot research "对比 Transformer 和 ViT 的注意力机制演化，给出证据引用" \
  --pdf-dir /path/to/your/papers \
  --max-papers 5 \
  --budget-cny 2.0
```

请求生成新论文模型框架草案：

```bash
paper-copilot research "针对行人重识别，先选一个 strong baseline，再从近年论文找可插拔模块，组合成可验证的新模型框架，并给出消融实验计划和证据引用" \
  --pdf-dir /path/to/your/papers \
  --max-papers 5 \
  --budget-cny 2.0
```

启动本地 API：

```bash
paper-copilot serve --host 127.0.0.1 --port 8765
```

调用 chat endpoint：

```bash
curl -sS http://127.0.0.1:8765/health
curl -sS -X POST http://127.0.0.1:8765/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"总结本地库里和 ViT attention 相关的证据","pdf_dir":"/path/to/your/papers"}'
```

运行 Web shell：

```bash
cd apps/web
npm ci
npm run dev
```

然后打开 `http://127.0.0.1:3000`。另一个终端里需要保持 `paper-copilot serve` 运行。

## CLI 参考

| 命令 | 用途 |
| --- | --- |
| `read <pdf>` | 读一篇 PDF，写入 `report.md`、`session.jsonl` 并更新索引 |
| `research "<topic>"` | 从 CLI 运行 chat-first bounded research loop |
| `serve` | 启动 Web shell 使用的本地 HTTP API |
| `list` | 从 `fields.db` 列出已索引论文 |
| `search "<query>"` | 对本地论文库做 hybrid semantic search |
| `compare <paper_id_a> <paper_id_b>` | 不调用 LLM，直接对比两篇已索引论文 |
| `reindex` | 从 session traces 和可选 PDF 重建本地索引 |
| `doctor` | 查看最近运行的 cache 命中率、延迟、tokens 和成本 |
| `eval mark/run/report/retrieval` | 维护 golden eval、retrieval eval 和趋势报告 |

完整参数见 `paper-copilot <command> --help`。

## 本地 HTTP API

本地 API 故意保持轻量，当前不引入 FastAPI 等额外框架。

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查 |
| `POST` | `/chat` | 通过 `handle_chat_request()` 运行自然语言请求 |
| `GET` | `/reports` | 列出最近 chat/research 报告 |
| `GET` | `/evidence?ref=...` | 把报告里的 evidence ref 解析成 chunk 原文 |
| `POST` | `/library/select-directory` | 给 Web UI 使用的桌面目录选择器 |

典型 `POST /chat` body：

```json
{
  "message": "找一个 ReID strong baseline，再找 2-3 个可接入模块，给出实验计划",
  "pdf_dir": "/path/to/your/papers",
  "max_turns": 16,
  "budget_cny": 2.0,
  "max_papers": 5
}
```

响应包含 route、Markdown 报告、session 路径、report 路径、可选 quality/eval report 路径、终止原因、成本、事件数和 paper budget。

## 数据目录

运行时数据默认保存在仓库外：

```text
~/.paper-copilot/
├── papers/<paper_id>/
│   ├── source.pdf
│   ├── session.jsonl
│   ├── report.md
│   └── research-report.md
├── fields.db
├── embeddings.db
├── embeddings_meta.json
├── graph/cross-paper-links.jsonl
└── eval/
    ├── runs/<run_id>.jsonl
    └── report.html
```

`paper_id` 是 `SHA1(PDF bytes)[:12]`，所以 PDF 改名或移动位置不会改变身份。

仓库内 eval fixtures：

```text
eval/
├── goldens/<paper_id>_<field>.json
├── retrieval/queries.yaml
└── suites/smoke.yaml
```

## 开发

```bash
uv sync --dev
make lint
make typecheck
make test
```

常用聚焦检查：

```bash
git diff --check -- README.md README.en.md
uv run pytest tests/chat/test_runtime.py tests/api/test_http.py
```

改默认模型 tier 之前，需要跑 smoke eval，并同时比较质量、成本和延迟。当前默认仍保持较便宜的 flash tier，因为已有 plus-tier 试验显示成本和延迟更高，但没有测到质量收益。

## Roadmap

近期工作以 [TASKS.md](TASKS.md) 为准。当前优先级：

1. 在不改 paper-level ranking 的前提下改进 evidence chunk selection。
2. 同时跟踪 evidence pool recall、final evidence recall 和 evidence anchor precision。
3. 在 grounding 风险更可控后，继续推进 M19 最小闭环，让“论文创新方案生成 / 新模型框架草案”更稳定可用。

## 已知限制

- 没有云同步、账号、多用户 ACL 或托管部署。
- 核心运行时不联网发现论文；它基于本地 PDF 和本地索引工作。
- 当前 active retrieval path 没有 cross-encoder 或 LLM reranker。
- Evidence chunk 还不够稳定，不能把每条生成 claim 都视为完全 grounding。
- 部分 eval suite 依赖本地 PDF，仓库不会随附这些论文文件。

## 贡献

这是一个实验性的 local-first 研究工具。提交 PR 前：

- 阅读 [AGENTS.md](AGENTS.md)，理解工程规约和模块边界。
- 保持改动范围小，说明用户可见行为。
- 不要在未讨论 tradeoff 的情况下新增依赖。
- 优先做可追溯、确定性的 harness 改进，而不是只改 prompt。

## License

MIT。详见 [LICENSE](LICENSE)。
