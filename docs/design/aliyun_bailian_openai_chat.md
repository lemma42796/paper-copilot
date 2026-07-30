# 阿里云百炼 OpenAI 兼容 Chat 接口

本文记录 Paper Copilot 配置阿里云百炼模型时所依据的 OpenAI 兼容 Chat
接口地址。内容整理自阿里云百炼官方文档：

- [OpenAI 兼容-Chat](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)
- [获取业务空间 ID](https://help.aliyun.com/zh/model-studio/obtain-the-app-id-and-workspace-id#d3eb3cd37b7fu)
- [获取 API Key](https://help.aliyun.com/zh/model-studio/get-api-key)

记录日期：2026-07-30。

## Base URL

| 地域 | SDK `base_url` |
|---|---|
| 华北 2（北京） | `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` |
| 新加坡 | `https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1` |
| 美国（弗吉尼亚） | `https://dashscope-us.aliyuncs.com/compatible-mode/v1` |
| 德国（法兰克福） | `https://{WorkspaceId}.eu-central-1.maas.aliyuncs.com/compatible-mode/v1` |
| 日本（东京） | `https://{WorkspaceId}.ap-northeast-1.maas.aliyuncs.com/compatible-mode/v1` |

`{WorkspaceId}` 必须替换为真实的业务空间 ID。Chat Completions 的 HTTP
请求地址是在对应 Base URL 后追加 `/chat/completions`。

## 业务空间专属域名

阿里云百炼建议华北 2（北京）和新加坡地域迁移到业务空间专属域名，以获得更好的
推理请求性能和稳定性：

- 华北 2（北京）：从 `https://dashscope.aliyuncs.com` 迁移到
  `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com`；
- 新加坡：从 `https://dashscope-intl.aliyuncs.com` 迁移到
  `https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com`。

官方文档同时说明现有域名仍可正常使用。由于专属域名包含用户自己的业务空间 ID，
Paper Copilot 不应把示例中的 `{WorkspaceId}` 作为可直接请求的固定预设值。

## Paper Copilot 配置含义

- 模型配置中的 API Base URL 对应上述 SDK `base_url`，不包含
  `/chat/completions`；
- Runtime 在发起 Chat Completions 请求时追加 `/chat/completions`；
- `*.maas.aliyuncs.com` 和 DashScope 各地域公共域名都属于阿里云百炼端点，provider
  识别、凭据传递和协议适配不应只匹配 `dashscope.aliyuncs.com`。
