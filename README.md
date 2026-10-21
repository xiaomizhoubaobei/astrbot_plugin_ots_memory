<div align="center">

<img src="logo.png" alt="Tablestore 长期记忆" width="180" />

# astrbot_plugin_ots_memory

**给 AstrBot 装上「不会忘事」的长期记忆——数据落在阿里云表格存储 Memory Store**

[![Coverage](https://codecov.io/gh/xiaomizhoubaobei/astrbot_plugin_ots_memory/graph/badge.svg)](https://codecov.io/gh/xiaomizhoubaobei/astrbot_plugin_ots_memory)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
![AstrBot](https://img.shields.io/badge/AstrBot-%3E%3D4.0.0-6a5acd.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-3776ab.svg)

</div>

---

## 这是什么

AstrBot 的记忆默认属于「上下文窗口」——窗口一滑，人也就被忘了。

本插件把记忆搬进 **阿里云表格存储（Tablestore）Memory Store**：模型可以主动检索旧的念想、
主动写下新的事实，每轮对话结束后还能在后台悄悄沉淀。写入与检索都走原生异步请求，
不额外引入 CLI 或 Node.js 依赖。

## 特性

- **按需召回**：`recall_memory` 工具交给模型自己判断何时调用，不做无脑注入，省 Token 也省延迟
- **主动记录**：`save_memory` 工具，模型遇到用户偏好、约定、重要事实时一键落库
- **自动沉淀**：`auto_record` 开启后，每轮对话异步投递 `AddMemories`，失败只告警不打扰对话
- **空间隔离**：基于 `app_id` 命名空间划分，支持跨会话记忆与多应用隔离
- **纯异步实现**：`aiohttp` + 自研 OTS V4 签名（HMAC-SHA256），不依赖庞大的 SDK
- **失败即降级**：配置不全时插件只警告不崩溃，工具返回可读的中文错误，不外抛堆栈

## 安装

本插件以 **AstrBot** 为宿主，需先有可用的 AstrBot 实例（要求 `astrbot_version >= 4.0.0`）。

### 快捷安装（推荐）

- **插件市场**：在 AstrBot Web 管理面板进入「插件市场」，搜索 `Tablestore 长期记忆`，点击一键安装。
- **指令安装**：在任意已配置的管理会话中发送：
  ```text
  /plugin get https://github.com/xiaomizhoubaobei/astrbot_plugin_ots_memory
  ```

### 手动安装（开发者）

1. **准备宿主 AstrBot**：从上游官方仓库拉取源码安装（<https://github.com/AstrBotDevs/AstrBot>）：
   ```bash
   git clone https://github.com/AstrBotDevs/AstrBot.git
   pip install -e AstrBot       # 开发期推荐 editable，跟随源码
   astrbot run                  # 默认监听 http://localhost:6185
   ```

2. **安装插件**：把本仓库克隆进 AstrBot 的 `data/plugins/` 目录后重启或重载：
   ```bash
   git clone https://cnb.cool/XMZZUZHI/Astrbot/astrbot_plugin_ots_memory.git \
     data/plugins/astrbot_plugin_ots_memory
   ```

## 前置条件

在 [阿里云表格存储控制台](https://otsconsole.aliyun.com/) 创建实例（按量付费/CU模式）并开通 Memory Store，
或使用 `tablestore-agent-cli` 命令行快速创建：

```bash
tablestore-agent-cli memory create --name huawu_memory
```

> **提示（免手动建表）**：控制台创建好实例与 Memory Store 后，无需手动创建底层数据表或二级索引。插件运行时会通过 Tablestore Memory Store API 自动管理记忆落库与检索。

> **安全建议**：建议使用仅授予当前 Tablestore 实例/Memory Store 操作权限的 RAM 子账号 AccessKey，避免直接使用阿里云主账号 AK。

## 配置

配置项定义见 [`_conf_schema.json`](_conf_schema.json)，在 AstrBot 插件配置界面填写：

| 字段 | 说明 | 默认值 |
| --- | --- | --- |
| `endpoint` | Tablestore 实例地址 | 空（必填） |
| `instance_name` | 实例名称 | 空（必填） |
| `region` | 地域 | `cn-shanghai` |
| `access_key_id` | 阿里云 AccessKey ID | 空（必填） |
| `access_key_secret` | 阿里云 AccessKey Secret | 空（必填） |
| `memory_store_name` | Memory Store 名称 | `huawu_memory` |
| `app_id` | Scope App ID（记忆隔离命名空间） | `astrbot` |
| `top_k` | 每次检索返回的记忆条数上限（1–20） | `5` |
| `min_score` | 最低相关度阈值（0.0–1.0），0 表示不过滤 | `0.4` |
| `auto_record` | 是否在每轮对话后自动沉淀 | `true` |

> `endpoint` / `instance_name` / `access_key_id` / `access_key_secret` 四项缺任一项，
> 插件会记录一条警告并停用自身（不注册工具），补齐后重启即可恢复。

示例：

```json
{
  "endpoint": "https://Bot.cn-shanghai.tablestore.aliyuncs.com",
  "instance_name": "Bot",
  "region": "cn-shanghai",
  "access_key_id": "LTAI5t...",
  "access_key_secret": "******",
  "memory_store_name": "huawu_memory",
  "app_id": "astrbot",
  "top_k": 5,
  "min_score": 0.4,
  "auto_record": true
}
```

## 推荐人格提示词（Prompt 引导）

插件提供了 `recall_memory` 与 `save_memory` 工具。为避免模型“空有工具却不知道用”，**强烈建议在你的 Bot 人格设定（System Prompt）中加入明确的工具使用引导**：

```markdown
## 长期记忆调用准则
1. **主动回忆**：遇到用户提及前情、偏好、过去约定或模糊信息时，优先调用 `recall_memory(query)` 查询云端记忆，不要直接脑补编造。
2. **主动沉淀**：当用户明确表述个人偏好（如喜好、习惯）、重要待办、关键人际关系或重大事实时，调用 `save_memory(fact)` 记入云端。
3. **保持自然**：无需在对话中刻意声明「我已经查了记忆」，自然将回忆内容融合进回复即可。
```

这样配合 `auto_record`（对话后自动沉淀），Bot 会在日常交互中自主沉淀认知，真正实现“越聊越灵动”。

## 方案对比

| 维度 | 传统全量/前置检索记忆 (如常见向量库方案) | Tablestore Memory Store (本插件) |
| --- | --- | --- |
| **召回机制** | 每轮对话前无脑检索，强行注入 Context | **Tool 按需调用**，模型按需自主检索，零上下文污染 |
| **Token 消耗** | 极高（每次无论用不用都塞满提示词） | **极低**（仅在触发 Tool 时消费少量上下文） |
| **存储扩展性** | 本地 SQLite / JSON / Chroma，数据量大后易膨胀变慢 | **云原生盘古底座**，百万并发无感扩容，容量无上限 |
| **环境依赖** | 需要本地额外起向量库/安装复杂 Python C 扩展 | **零额外笨重依赖**，原生 aiohttp + HMAC-SHA256 签名 |
| **模型智商影响** | 易被大量无关前情稀释注意力，产生幻觉或越聊越呆 | **极高专注度**，上下文保持干净，逻辑更聚焦 |

## 工作原理

```
用户消息
    │
    ▼
LLM 推理（携带 recall_memory / save_memory 工具定义）
    │
    ├─ 需要回忆时  → recall_memory(query) → SearchMemories → 结果以「[相关度 0.xx] 文本」注入上下文
    │
    └─ 遇到重要信息 → save_memory(fact)    → AddMemories（userMemories）

对话结束后 → auto_record=true → 本轮 user/assistant 消息异步投递 AddMemories
```

细节：

- 检索走 `SearchMemories`，固定开启 `enableRerank`；`min_score > 0` 时才下发 `thresholds.minScore`
- 自动沉淀只取回复链第一段文本作为 assistant 内容，且必须在有用户文本时才投递
- 后台沉淀任务用 `asyncio.create_task` 脱离请求链，异常仅 `warning` 记录

## 开发

`main.py` 依赖 `astrbot.api` / `astrbot.core.*`，宿主必须先装好——
**从上游源码安装，不用 PyPI 的 `astrbot` 包**：

```bash
git clone https://github.com/AstrBotDevs/AstrBot.git
pip install -e AstrBot                    # 宿主源码
pip install -r requirements-dev.txt       # 运行依赖 + 测试工具
python -m tests.run_coverage              # 跑单测并生成 coverage.xml
```

> `requirements-dev.txt` 不声明 `astrbot` 依赖：宿主统一走源码安装，
> CI（`.github/workflows/coverage.yml`）与 CNB（`.cnb.yml`）按同一口径拉源码。

### 目录结构

```
.
├── main.py               # 插件入口：OTSMemoryPlugin、两个 LLM 工具、自动沉淀钩子
├── client.py             # OTSMemoryClient：OTS V4 签名 + SearchMemories / AddMemories
├── _conf_schema.json     # 配置 schema
├── metadata.yaml         # 插件元数据（版本、分类、标签）
├── tests/                # 单测与覆盖率启动器（python -m tests.run_coverage）
└── ai-audit/             # AI 审计相关资产（不计入覆盖率分母）
```

### 两个容易踩的坑

1. **工具返回值**：`ToolExecResult` 只是 `str | CallToolResult` 的联合别名，**不可当函数调用**；
   要表达「出错」必须显式构造 `CallToolResult(isError=True)`，否则运行时抛
   `TypeError: 'types.UnionType' object is not callable`。
2. **工具上的插件引用**：宿主以 pydantic dataclass 声明 Tool，`plugin` 字段须标注为
   `Optional[Any]`（直接标注插件类会抛 `PydanticSchemaGenerationError`），并用
   `Field(exclude=True)` 排除出序列化。

### 代码质量

```bash
pip install pre-commit && pre-commit run --all-files
```

覆盖 black / flake8 / isort / mypy（`ignore_missing_imports`，要求类型注解）/
pydocstyle 等钩子，详见 [`.pre-commit-config.yaml`](.pre-commit-config.yaml)。

## 持续集成

- **覆盖率**：GitHub Actions [`.github/workflows/coverage.yml`](.github/workflows/coverage.yml) 出报告并上报 Codecov（徽章见顶部）
- **发布**：`.github/workflows/release.yml` 依据 `metadata.yaml` 的 `version` 打 tag 并构建 Release
- **安全扫描**：CodeQL、依赖审计、secret-scanning、Scorecard、tfsec 等工作流
- **镜像同步**：CNB（`.cnb.yml`）在 `main` 推送时同步到 GitHub 镜像仓库，并以 CNB 侧为准

## 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| 日志出现「配置不完整，插件功能已禁用」 | 四个必填项有缺失，补齐后重启 |
| 工具返回「OTS 记忆插件客户端未初始化」 | 同上，客户端未构造成功 |
| 工具返回「检索记忆失败: OTS API Error [xxx]」 | 上游返回非 2xx，按状态码查 OTS 侧（鉴权 / 实例名 / 网络） |
| 徽章长期灰色 | 仓库为 GitHub 镜像，需在 Codecov 侧完成仓库授权 |

## 参与贡献

- **行为准则**：请先阅读 [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)。它不只讲「别骂人」，
  还写明了本项目的专项约定——涉密信息不入库、AI 辅助的边界、记忆数据伦理、漏洞私下披露。
- **提交规范**：中文提交信息、Angular 格式、签名提交、先跑 `pre-commit`；一律走 PR，不直推 `main`。
- **安全问题**：请勿开公开 Issue，走 Security Advisory 或邮件私下报告。

## Issues

请在 [CNB 仓库](https://cnb.cool/XMZZUZHI/Astrbot/astrbot_plugin_ots_memory) 提交 Issue；
GitHub 镜像仓库为单向同步，Issue 请以 CNB 侧为准。

## License

[AGPL-3.0](LICENSE)
