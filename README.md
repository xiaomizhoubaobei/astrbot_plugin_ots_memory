# astrbot_plugin_ots_memory

基于阿里云表格存储（Tablestore）Memory Store 的 AstrBot 跨会话长期记忆插件，支持语义检索与自动沉淀记忆。

## 特性

- **按需召回**：`recall_memory` Tool，模型在需要时主动调用，零常规延迟
- **主动记录**：`save_memory` Tool，模型可将重要信息一键写入长期记忆库
- **自动沉淀**：每轮对话结束后异步投递到 Tablestore 供后续沉淀（可关闭）
- **纯异步实现**：原生 aiohttp + OTS V4 签名，无需 CLI 或 Node.js 依赖

## 安装

将本仓库克隆到 AstrBot 插件目录：

```bash
git clone https://cnb.cool/XMZZUZHI/Astrbot/astrbot_plugin_ots_memory.git
```

然后在 AstrBot 管理面板重载插件。

## 配置

| 字段 | 说明 | 示例 |
|---|---|---|
| `endpoint` | Tablestore 实例地址 | `https://Bot.cn-shanghai.tablestore.aliyuncs.com` |
| `instance_name` | 实例名称 | `Bot` |
| `region` | 地域 | `cn-shanghai` |
| `access_key_id` | 阿里云 AK | `LTAI5t...` |
| `access_key_secret` | 阿里云 SK | `...` |
| `memory_store_name` | Memory Store 名称 | `huawu_memory` |
| `app_id` | Scope App ID | `astrbot` |
| `top_k` | 最大检索条数（1-20） | `5` |
| `min_score` | 最低相关度阈值（0-1） | `0.4` |
| `auto_record` | 是否自动沉淀每轮对话 | `true` |

## 前置条件

在 [阿里云表格存储控制台](https://otsconsole.aliyun.com/) 创建实例和 Memory Store，
或使用 `tablestore-agent-cli` 创建：

```bash
tablestore-agent-cli memory create --name huawu_memory
```

## 工作原理

```
用户消息
    │
    ▼
LLM 推理（携带 recall_memory / save_memory 工具定义）
    │
    ├─ 需要回忆时 → recall_memory(query) → Tablestore SearchMemories → 结果注入上下文
    │
    └─ 遇到重要信息 → save_memory(fact) → Tablestore AddMemories（异步沉淀）

对话结束后 → auto_record=true → 本轮消息异步投递 AddMemories（后台沉淀）
```

## Issues

请在 [CNB 仓库](https://cnb.cool/XMZZUZHI/Astrbot/astrbot_plugin_ots_memory) 提交 Issue。

## License

AGPL-3.0
