# VISION

## 项目是什么

paper-copilot 是一个本地运行的命令行论文分析工具。给它一个 PDF，
它用 subagent 架构把论文拆成"问题 / 方法 / 实验 / 局限"的结构化摘要，
落盘成可追溯、可分叉、可回溯的 JSONL session；多篇论文之间自动建立概念与
引用关联，形成一棵慢慢生长的结构化知识树。

项目内置一个轻量 eval 模块，用真实使用中积累的 session 作为回归测试的
ground truth，保证 prompt 或模型升级时输出质量不静默退化。

技术上的核心赌注：把 prompt engineering 主要做在 Pydantic Field
description 上，而不是 system prompt 或 few-shot examples 上——让 schema
成为人机共读的单一真源。

## 解决什么问题

我自己每周要读 5-10 篇论文：准备面试、跟进新工作、写毕业论文。现有工具的问题：

- **ChatPDF / NotebookLM 类**：一次读一篇、输出自由文本、多篇之间无法关联；
  读完十几篇后回忆不起"上次那篇讲了什么"
- **Elicit / arxiv-sanity 类**：偏推荐和搜索，不做深度结构化拆解
- **自己做笔记**：成本太高，坚持不下来，最后只剩一堆没读完的 PDF

核心痛点是：**论文的价值在于可对比、可检索、可追溯**，而现有工具的输出是
一次性的自由文本，无法沉淀成可复用的知识资产。

paper-copilot 的假设：用结构化 schema + 本地 JSONL + subagent 隔离，把"读论文"
从一次性对话变成可以在本地慢慢长出、可查询、可回溯的结构化语料库。

## 核心用例

1. **单篇深读**：用户 `paper-copilot read <pdf_path>`，得到一份结构化报告
   （Contribution / Method / Experiment / Limitation），以及每个字段对应的原文页码
   引用；报告和完整推理过程以 JSONL 形式落盘，可 `cat` 可 `grep` 可 `git diff`。

2. **跨论文对比**：用户 `paper-copilot compare <paper_id_A> <paper_id_B>`，
   基于已落盘的结构化字段生成对比表（方法差异、实验设置差异、结论冲突），
   无需重新读 PDF。

3. **基于真实使用的回归测试**：用户 `paper-copilot eval run`，用历史中被标记为
   golden 的 session 作为 ground truth，跑完整 suite，输出 field-level accuracy、
   cache hit rate、cost-per-paper 三项指标的趋势报告；prompt 调整或模型升级
   前后必跑，发现静默退化。

## 明确不做什么

- ❌ **不做 Web UI**：CLI + 生成的 markdown/HTML 报告即可，避免前端负担
- ❌ **不做多用户 / 云端同步**：单机单用户，数据主权在本地
- ❌ **不做论文推荐**：推荐系统是另一个领域，不混入
- ❌ **不做多模态图表理解**：图表用 OCR 抽取文字引用即可，不做 CV 模型
- ❌ **不做通用 eval 平台**：eval 模块服务于本项目自身，不对外做成独立产品
- ❌ **不自建向量数据库**：用 sqlite-vec 或 chromadb，不造轮子
- ❌ **不自训 embedding 模型**：用开源的 bge-m3 或 API 服务
- ❌ **不做实时协作 / 多 agent 编排**：主 loop 单线程 + subagent 单向派发，
  不碰 CrewAI / AutoGen 那类复杂编排

## 成功标准

项目完成时，下列都要为真：

- 我自己真实分析过 ≥ 20 篇论文，session 数据留存在本地
- eval suite 至少一次**真的发现并定位**过 prompt 或模型的退化问题
- 任何一个设计决策（为什么用 subagent、为什么用 JSONL、为什么 hybrid retrieval），
  我都能在 5 分钟内讲清"解决什么问题、放弃了什么"
- 代码库对陌生人友好：clone 后按 README 能在 10 分钟内跑通第一个 demo