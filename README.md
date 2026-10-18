# astrbot_plugin_ots_memory

基于阿里云表格存储（Tablestore）Memory Store 的 AstrBot 跨会话长期记忆插件，支持语义检索与自动沉淀记忆。

## 特性

- **按需召回**：`recall_memory` Tool，模型在需要时主动调用，零常规延迟
- **主动记录**：`save_memory` Tool，模型可将重要信息一键写入长期记忆库
- **自动沉淀**：每轮对话结束后异步投递到 Tablestore 供后续沉淀（可关闭）
- **纯异步实现**：原生 aiohttp + OTS V4 签名，无需 CLI 或 Node.js 依赖

## 安装

本插件以 **AstrBot** 为宿主运行，需先有可用的 AstrBot 实例。

### 1. 安装 AstrBot（源码）

从上游官方仓库拉取源码后安装（要求 `astrbot_version >= 4.0.0`）：

```bash
git clone https://github.com/AstrBotDevs/AstrBot.git
pip install -e AstrBot       # 开发期推荐 editable，跟随源码
astrbot run                  # 默认监听 http://localhost:6185
```

上游仓库：<https://github.com/AstrBotDevs/AstrBot>

### 2. 安装插件

将本仓库克隆到 AstrBot 的 `data/plugins/` 目录：

```bash
git clone https://cnb.cool/XMZZUZHI/Astrbot/astrbot_plugin_ots_memory.git \
  data/plugins/astrbot_plugin_ots_memory
```

然后重启 AstrBot，或在其管理面板中重载插件。

## 开发

`main.py` 依赖 `astrbot.api` / `astrbot.core.*`，宿主须先装好——
**从上游源码安装，不用 PyPI 的 `astrbot` 包**：

```bash
git clone https://github.com/AstrBotDevs/AstrBot.git
pip install -e AstrBot                    # 宿主源码
pip install -r requirements-dev.txt       # 运行依赖 + 测试工具
python -m tests.run_coverage              # 跑单测并生成 coverage.xml
```

> `requirements-dev.txt` 不再声明 `astrbot` 依赖：宿主统一走源码安装，
> CI（`.github/workflows/coverage.yml`）与 CNB（`.cnb.yml`）都按同一口径拉源码。

> 注：AstrBot 宿主是以 pydantic dataclass 形式声明 Tool 的，`plugin` 这类运行时
> 引用字段须标注为 `Optional[Any]`（不能直接标注插件类），且工具返回值须用
> `CallToolResult` 构造——`ToolExecResult` 只是 `str | CallToolResult` 的联合别名，
> 不可当函数调用。

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
