# Paper Copilot

> 本地优先的论文研究助手：阅读 PDF、检索个人论文库，并基于证据生成研究笔记与
> 可验证的模型框架草案。

![Python](https://img.shields.io/badge/python-3.12+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Code style](https://img.shields.io/badge/code_style-ruff-purple)
![Package manager](https://img.shields.io/badge/package-uv-orange)

简体中文 | [English](README.en.md)

Paper Copilot 面向约 50–100 篇论文的个人知识库。它把 PDF 转为结构化报告，建立本地
SQLite / sqlite-vec 索引，并通过 macOS 客户端或 MCP 完成论文问答、跨论文检索、对比
和研究方案组合。

PDF、索引、session、报告和 trace 默认保存在本地。本地检索选出的文本片段可能发送给
用户配置的云端模型；“PDF 未上传”不表示任何论文内容都不会离开设备。

## Status

当前产品入口：

- **SwiftUI macOS 客户端**：论文目录、模型配置、持久任务、对话、报告、停止/恢复和
  diagnostics。
- **Local MCP Server**：六个只读论文工具和四个长任务工具。
- **Python Core**：Agent、PDF 解析、hybrid retrieval、session、job recovery、eval
  和 observability。

M20–M24 已完成，包括自包含 Apple Silicon `.app`、开发预览 DMG 和旧 Next.js Web UI
退役。Developer ID 与 Apple 公证留到正式发布阶段。完整状态见
[TASKS.md](TASKS.md)。

## Capabilities

- 将 PDF 提取为贡献、方法、实验、局限和跨论文关系。
- 使用 FTS5/BM25、`text-embedding-v4`、sqlite-vec 和 RRF 检索本地论文库。
- 通过一个 bounded Paper Copilot loop 选择读取、检索、对比和 Composer 工具。
- 组合 baseline、可接入模块、风险、消融计划和 evidence，生成待验证研究草案。
- 使用 append-only session、持久 job/attempt、rollout replay 和本地 trace 保留
  恢复与诊断证据。
- 使用字段 golden、retrieval suite、成本和延迟趋势约束模型变更。

输出是研究草案，不是论文成稿，也不证明建议的组合一定有效。

## Quick Start

开发环境需要 Python 3.12+、[`uv`](https://docs.astral.sh/uv/) 和可用的模型 API Key。

```bash
git clone https://github.com/lemma42796/paper-copilot.git
cd paper-copilot
uv sync --dev
cp .env.example .env
```

编辑 `.env`：

```bash
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=sk-your-key-here
LLM_MODEL=qwen3.6-flash
DASHSCOPE_API_KEY=sk-your-key-here
PAPER_COPILOT_PDF_DIR=/path/to/your/papers
```

源码开发可在 Xcode 打开：

```bash
open apps/macos/PaperCopilot.xcodeproj
```

客户端在动态端口启动本地 Python Runtime。发布构建内嵌 Runtime，终端用户无需安装
Python、uv 或 Node.js。

## Build the macOS Preview

```bash
./scripts/build_macos_dmg.sh
open dist/macos/PaperCopilot-arm64.dmg
```

默认输出使用 ad-hoc 签名，macOS 会拦截来自未知开发者的下载包。确认来源可信后，先
尝试打开，再到“系统设置 → 隐私与安全性”选择“仍要打开”；不要关闭整个 Gatekeeper。

正式签名与公证：

```bash
PAPER_COPILOT_SIGN_IDENTITY="Developer ID Application: Example (TEAMID)" \
PAPER_COPILOT_NOTARY_PROFILE="paper-copilot-notary" \
./scripts/build_macos_dmg.sh
```

notarytool profile 必须预先保存到 Keychain；仓库不保存证书或 Apple 凭据。

## Configuration

| 变量 | 用途 |
| --- | --- |
| `LLM_BASE_URL` | OpenAI-compatible LLM endpoint |
| `LLM_API_KEY` | LLM API Key |
| `LLM_MODEL` | 模型 ID，默认 `qwen3.6-flash` |
| `DASHSCOPE_API_KEY` | `text-embedding-v4` Key |
| `PAPER_COPILOT_HOME` | 数据根目录，默认 `~/.paper-copilot` |
| `PAPER_COPILOT_PDF_DIR` | 本地 PDF 目录 |

macOS 客户端将 LLM Key 保存到 Keychain。embedding 模型或维度变化后必须重建索引。

使用 DeepSeek 官方 API 时只需替换前三个 LLM 变量；embedding 仍使用独立的
`DASHSCOPE_API_KEY`。

## Local MCP Server

将开发 checkout 加入 Codex：

```bash
codex mcp add paper-copilot -- \
  uv --directory /absolute/path/to/paper-copilot run paper-copilot-mcp
```

只读工具：

```text
library_status  list_papers  search_papers
get_paper       inspect_evidence  compare_papers
```

长任务工具：

```text
start_read_paper  get_job_status  get_job_result  cancel_job
```

有 embedding Key 时搜索使用 hybrid retrieval，否则使用本地 FTS5/BM25。普通只读
工具不进入 Agent loop；`start_read_paper` 会使用 LLM budget，并写入本地 job、
session、report 和索引状态。

MCP 不返回完整 PDF、session 或本机结果路径，但云端 MCP Host 通常会接收返回的摘要、
evidence 和报告。应把这些内容视为可能离开设备的数据。

## Local HTTP API

本地 HTTP API 是 macOS Runtime 的内部边界：

| Method | Path | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查 |
| `POST/GET` | `/jobs` | 创建或列出 job |
| `GET` | `/jobs/<id>` | 状态和结果 |
| `GET` | `/jobs/<id>/events?after=N` | 增量事件 |
| `GET` | `/jobs/<id>/stream?after=N` | SSE |
| `GET` | `/jobs/<id>/diagnostics` | attempt 诊断 |
| `POST` | `/jobs/<id>/interrupt` | 停止 |
| `POST` | `/jobs/<id>/resume` | 创建恢复 attempt |
| `POST` | `/jobs/<id>/approval` | 工具审批 |

客户端断线不影响 job。恢复使用持久 rollout 重建历史，不会从上一次网络流或模型 token
原地续跑。

## Architecture

```text
SwiftUI macOS Client ──► local HTTP/job API ──┐
Local MCP Server ──────► MCP services ─────────┤
                                               ▼
                                       Python Paper Core
```

Core 包含单一 Paper Copilot loop、持久 job、JSONL session、SQLite knowledge stores、
rollout trace 和 eval。模块职责、依赖规则、模型策略及数据流见
[ARCHITECTURE.md](ARCHITECTURE.md)。

## Data

运行时数据默认位于 `~/.paper-copilot/`：

```text
papers/<paper_id>/          # PDF、session、report
jobs/<job_id>/              # job、events、attempt traces
fields.db                   # 结构化字段
embeddings.db               # FTS5 + sqlite-vec chunks
embedding_cache.sqlite      # embedding cache
graph/                      # 跨论文关系
eval/                       # 本地 eval 结果
```

`paper_id = SHA1(PDF bytes)[:12]`，因此重命名或移动 PDF 不改变 ID。

## Development

```bash
uv sync --dev
make lint
make typecheck
make test
```

执行验证应遵守 [AGENTS.md](AGENTS.md) 的工作约定。修改默认模型前必须运行 smoke eval，
并同时比较质量、成本和延迟。

## Limitations

- 当前开发预览仅支持 Apple Silicon，使用 ad-hoc 签名且尚未公证。
- 不支持账号、云同步、多用户 ACL 或托管部署。
- Core 不联网发现论文，只处理本地 PDF 和索引。
- active retrieval path 没有 cross-encoder 或 LLM reranker。
- evidence grounding 仍可能不完整，生成内容需要人工核验。
- 部分 eval 依赖仓库不分发的本地 PDF。

## Contributing

提交改动前请阅读 [AGENTS.md](AGENTS.md)：保持范围小，不未经讨论新增依赖，并优先
改进可追溯、可评测的 harness。

## License

MIT，详见 [LICENSE](LICENSE)。
