# `inspect_page` Codex 源码映射

状态：Slice 4 实现与手工验收完成
日期：2026-07-27  
Codex source ref：`61a44880a85d2fd0d8770908dea5733495e571c8`  
Codex worktree：`/Users/a123/Documents/agent学习/codex`，审计时无本地修改

## 1. 目的

本文按仓库的 Codex-first 原则，逐项核对 Paper Copilot `inspect_page` 与固定 Codex
源码。分类只有三种：

- **直接采用**：Codex 已有对应机制，Paper Copilot 保持其结构和语义；
- **必要适配**：Codex 有基础机制，但论文库授权边界或 Chat Completions transport
  要求收窄；
- **Codex 缺失**：固定 source ref 中没有论文领域对应能力，只增加最小专用设计。

未列入本文的自定义机制不得进入 Slice 4。

## 2. 源码映射

| 需求 | Codex source | Codex 机制 | Paper Copilot 分类 | 结论 |
|---|---|---|---|---|
| 模型能力 | `protocol/src/openai_models.rs` | `InputModality` 明确声明 `text`、`image`、`audio`；旧配置缺失时默认 `text + image` | 直接采用 | 模型配置增加 `input_modalities`，缺失时保持 Codex 的 `text + image` 兼容默认 |
| 调用前能力检查 | `core/src/tools/handlers/view_image.rs` | handler 在读取文件前检查 `model_info.input_modalities`；不支持图像时返回明确错误 | 直接采用 | `inspect_page` 在解析授权 PDF 和渲染前检查 `image` capability；纯文本模型不执行文本回退 |
| 图像工具结果 | `core/src/tools/handlers/view_image.rs::ViewImageOutput` | 返回 `FunctionCallOutputContentItem::InputImage`，使用 data URL；日志预览不包含图像正文 | 直接采用 + 必要适配 | Agent 内部工具结果增加有界 image content；Chat Completions transport 在对应 tool result 后追加 image user content；session、日志和 trace 不保存 base64 |
| 图像 detail | `core/src/tools/handlers/view_image.rs`、`core/src/original_image_detail.rs` | 默认 `high`，只有模型能力允许时接受 `original` | 必要适配 | Slice 4 只提供固定有界渲染，不开放 `detail` 参数或原图无界传输 |
| 文件授权 | `core/src/tools/handlers/view_image.rs` | 相对 environment cwd 解析路径，并通过 filesystem sandbox 读取 | 必要适配 | 模型不提供路径；首选完整 PDF SHA-256，兼容旧 session 的 12 位 `paper_id`，两者都只能解析到 macOS 已授权论文库内的 PDF |
| UI/trace 事件 | `core/src/tools/handlers/view_image.rs` | 图像查看作为独立 turn item，trace/log 只记录路径或有界预览，不记录 data URL | 必要适配 | 复用现有 tool call/session/trace；记录 paper、page、region、PDF/render hash、尺寸和字节数，不记录图片正文或完整本地路径 |
| 单页 PDF 渲染 | 固定 Codex source ref 无论文 PDF 页面渲染工具 | 无对应领域机制 | Codex 缺失 | 使用既有 Poppler substrate 的 `pdftoppm`，只渲染一个已验证页码和可选归一化区域 |
| 论文证据 | 固定 Codex source ref 无 `paper_id`、PDF revision 或页级 evidence | 无对应领域机制 | Codex 缺失 | 返回绑定 PDF SHA-256、页码、可选区域和 render SHA-256 的最小 evidence metadata |

## 3. Slice 4 固定边界

- 单次只处理一个完整 PDF SHA-256（首选）或旧 12 位 `paper_id` 的一页；不得截断
  SHA-256 冒充旧 ID；
- `region` 使用归一化页面坐标；
- 渲染像素、字节数、执行时间和模型输入大小均有硬上限；
- 不接受任意路径，不读取授权论文库之外的 PDF；
- 不加入 OCR、批量页面、第二模型、全文入库或新依赖；
- Poppler 缺失、页码无效、渲染失败或输出超限时返回明确失败；
- 模型不支持图像输入时，沿用 Codex `view_image` 语义直接拒绝；
- Slice 4 不切换公开模型工具表面，公开四工具切换保留到 Slice 6。
