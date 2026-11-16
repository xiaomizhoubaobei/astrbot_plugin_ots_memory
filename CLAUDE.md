# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> `AGENTS.md` 是本仓库**唯一的 Agent 入口文档**，其规则（中文提交信息、GPG 签名、PR 流程、双端同步等）对本文件同样有效；两者冲突时以更严格者为准。`CONTRIBUTING.md` 是面向人的同口径说明，`README.md` 面向使用者。

## 项目概览

`astrbot_plugin_ots_memory` 是 AstrBot（`astrbot_version >= 4.0.0`）插件，把跨会话长期记忆存进阿里云表格存储（Tablestore）Memory Store。

- 仓库根即包根（`__init__.py` 在根），宿主按目录名作为包名加载插件。
- 运行形态是「插件跑在 AstrBot 源码宿主上」：`main.py` 依赖 `astrbot.api` / `astrbot.core.*`，缺宿主时整个 `main.py` 连导入都不成立。
- 仅两个业务文件：`client.py` 负责 OTS 协议与签名，`main.py` 负责宿主集成（Star 生命周期、LLM 工具、自动沉淀钩子）。

## 常用命令

宿主必须**从上游源码**安装，不要用 PyPI 的 `astrbot` 包（`requirements-dev.txt` 也刻意不声明它）：

```bash
git clone https://github.com/AstrBotDevs/AstrBot.git
pip install -e AstrBot                       # 本地克隆到 AstrBot/ 即可，该目录已被 .gitignore 忽略
pip install -r requirements-dev.txt
pip install pre-commit
```

测试与覆盖率：

```bash
python -m tests.run_coverage                 # 跑 tests + 打印报告 + 写 coverage.xml（CI 用这条）
python -m tests.run_coverage -- -k signing   # -- 之后的参数原样透传给 pytest
python -m tests.run_coverage --report-only   # 不复跑测试，只基于已有 .coverage 出报告
python -m pytest -q                          # 只跑测试（CI 的纯单测矩阵用这条）
python -m pytest tests/test_client.py -q     # 单文件
python -m pytest tests/test_client.py::test_endpoint_trailing_slash_stripped -q   # 单条
```

代码规范：

```bash
pre-commit run --all-files
```

`pyproject.toml` 里 `asyncio_mode = "auto"`，异步测试直接写 `async def test_...`，不需要 `@pytest.mark.asyncio`。

## 架构

### 模块职责

| 位置 | 职责 | 关键符号 |
| --- | --- | --- |
| `main.py` | 宿主集成层 | `OTSMemoryPlugin`、`RecallMemoryTool`、`SaveMemoryTool`、`_tool_result()`、`_segment_texts()`、`_safe_error_text()` |
| `client.py` | 传输层：OTS V4 签名与 REST 调用 | `OTSMemoryClient._get_signing_key()` / `_build_headers()` / `_request()` / `search_memories()` / `add_memories()` |
| `_conf_schema.json` | AstrBot 配置界面 schema；字段名必须与 `main.py` 读取的 key 一致 | — |
| `metadata.yaml` | 插件元数据；`version` 是 Release 打 tag 的唯一来源 | — |
| `tests/` | 单测 + 包视图 + 覆盖率启动器（见下文「测试体系」） | `package_view.py`、`meta_path.py`、`run_coverage.py` |
| `ai-audit/` | AI 告警分流的演示资产（Taskflow 模板 + 模型配置），不参与覆盖率与类型检查 | — |

### 运行链路

```text
AstrBot 对话
  ├─ LLM 调 recall_memory(query)
  │    → OTSMemoryClient.search_memories() → POST /SearchMemories
  │    → 结果格式化为 "[相关度 0.xx] <text>" 多行返回；空结果返回「没有找到相关的历史记忆。」
  ├─ LLM 调 save_memory(fact)
  │    → OTSMemoryClient.add_memories(text=fact) → POST /AddMemories（userMemories 数组）
  └─ 回复结束（@filter.on_decorating_result）
       → auto_record=true 且 client 存在时，asyncio.create_task 后台 POST /AddMemories（messages 数组）
```

- **初始化与停用**：`OTSMemoryPlugin.__init__` 检查 `endpoint` / `instance_name` / `access_key_id` / `access_key_secret` 四项。缺任一项 → `client = None`、打 `warning`、**不注册任何工具**；齐全才构造客户端并 `context.add_llm_tools(...)`。
- **记忆隔离**：请求里的 `scope` 由配置项 `app_id` 与代码内固定的 `tenant_id = "default"` 组成；`memory_store_name` 默认 `huawu_memory`。
- **检索参数**：`top_k` / `min_score` 来自配置；`enableRerank` 固定为 `True`；仅当 `min_score > 0` 才下发 `thresholds.minScore`。
- **自动沉淀**：用户消息取 `event.get_messages()` 的所有非空文本段；assistant 内容只取回复链 `result.chain` 的**第一段**文本。缺用户文本或缺回复文本时直接跳过。后台任务异常只 `warning`，不向对话链逃逸。
- **签名**：`_build_headers` 组装 `x-ots-*` 头（含 `x-ots-contentmd5`、`x-ots-date`、`x-ots-signdate`、`x-ots-signregion`），按字典序拼 Canonical Request，再用四级 HMAC-SHA256 派生密钥签出 `x-ots-signaturev4`。这是刻意自研——不要为省事引入 Tablestore SDK，也不要改写成非标准实现。
- **出站约束**：`_request` 显式 `allow_redirects=False`，保证出站目标只有配置的 endpoint；非 2xx（含 3xx）统一抛中文 `RuntimeError`。

### 配置项（`_conf_schema.json` 与 `main.py` 默认值）

| Key | 默认值 | 作用 |
| --- | --- | --- |
| `endpoint` | 空（必填） | Tablestore 实例地址；客户端会去掉末尾 `/` |
| `instance_name` | 空（必填） | 实例名，进 `x-ots-instancename` |
| `region` | `cn-shanghai` | 签名派生与 `x-ots-signregion` |
| `access_key_id` / `access_key_secret` | 空（必填） | OTS 鉴权 |
| `memory_store_name` | `huawu_memory` | 请求体 `memoryStoreName` |
| `app_id` | `astrbot` | 请求体 `scope.appId`，记忆隔离命名空间 |
| `top_k` | `5` | 检索返回条数上限 |
| `min_score` | `0.4` | 相关度阈值；`0` 表示不下发阈值 |
| `auto_record` | `true` | 是否在每轮对话后自动沉淀 |

## 必须保持的契约（改代码前先读）

1. **工具返回值**：`ToolExecResult` 是 `str | CallToolResult` 的**联合别名，不可调用**。构造结果一律走 `main.py` 的 `_tool_result()`；错误必须显式 `CallToolResult(content=[TextContent(type="text", text=...)], isError=True)`，否则运行时抛 `TypeError: 'types.UnionType' object is not callable`。
2. **工具上的 `plugin` 字段**：pydantic dataclass 中必须写 `Optional[Any] = Field(default=None, exclude=True)`。标注真实插件类会抛 `PydanticSchemaGenerationError`（宿主 `FunctionTool` 未开 `arbitrary_types_allowed`）；不加 `exclude=True` 则会让宿主引用进入工具序列化。
3. **错误信息脱敏契约**：上游错误体可能回显用户记忆内容，因此
   - `client._request` 的异常文本**只含** `status` 与截断到 64 字符的 `x-ots-requestid`，不夹带响应体；
   - 工具层只返回固定中文提示（`检索记忆失败，请稍后重试。` / `保存记忆失败，请稍后重试。`），不回显堆栈或异常文本；
   - 日志只留异常类型、`_safe_error_text()` 压缩后的摘要（≤200 字符）与 `status` / `request_id`。
4. **失败降级**：配置不全时插件停用自身而非崩溃；`auto_record` 后台任务异常只告警；`add_memories` 在 `messages` 与 `text` 同时为空时抛 `ValueError`。
5. **签名与依赖边界**：`requirements.txt` 只有 `aiohttp`；不要引入 OTS SDK 或 Node.js 工具链。
6. **发布包边界**：唯一入口是 `.github/workflows/release.yml` 的**复制白名单**（`main.py __init__.py client.py metadata.yaml requirements.txt _conf_schema.json` + 可选 `logo.png`），随后还有断言阻止包内出现白名单外条目。新增需要随插件发布的文件时只改白名单。

## 测试体系

### 包视图（为什么测试能按顶层包名导入）

仓库目录名不是 `astrbot_plugin_ots_memory`，但测试统一按顶层包名导入。`tests/package_view.py` 通过 `tests/meta_path.py` 注册一个 meta path finder，把仓库根映射成该包名——不写符号链接、不改 `sys.path`、与检出目录名无关。

- `tests/conftest.py` 在 pytest 收集前注册包视图。
- `tests/run_coverage.py` 在 coverage 启动前注册（它解析 `--source` 早于 pytest 加载 conftest）。
- 若环境里已装真实同名包，注册会主动让位（`PACKAGE_VIEW_MODE == "existing"`），`test_package_import.py` 里依赖「指向本仓库」的断言在运行时跳过。

### 覆盖率启动器（不要直接 `coverage run --source=...`）

`coverage run --source=astrbot_plugin_ots_memory -m pytest` 会在启动阶段解析 `--source`，此时包视图尚未建立，结果只警告 `Module ... was never imported` 并写出空报告。`tests/run_coverage.py` 把「建包视图 → 启动 coverage → 跑 pytest」放进**同一进程**，顺序可控。CI 还有一道兜底断言：`coverage.xml` 里没有任何文件即失败。

`pyproject.toml` 中裸跑口径（`source = ["."]`，文件名相对检出根）与启动器口径（`--source=<包名>`）刻意分开，勿统一。

### 现有用例覆盖什么

| 文件 | 锁定的内容 |
| --- | --- |
| `tests/test_client.py` | 签名派生确定性、已知答案向量、`x-ots-*` 头、content-md5、payload 组装、`allow_redirects=False`、错误不回显响应体、request_id 截断、logger 来源 |
| `tests/test_main.py` | 工具可实例化、`plugin` 字段不进 schema、空参数/未初始化客户端分支、召回格式化、错误包装、插件注册与停用、配置默认值、`auto_record` 各分支、钩子注册 |
| `tests/test_package_import.py` | 包视图自洽、coverage source 可解析、顶层包名与子模块导入 |

写新用例的现成手法：`_FakeClient` / `_FakePlugin`（`test_main.py`）隔离网络与完整 Star 实例；`fake_aiohttp`（`test_client.py`）替换 session，断言真实发出的请求体、头与重定向参数。单测一律使用假 AK/SK 与假记忆内容。

### 覆盖率口径

- 分母排除 `tests/*` 与 `ai-audit/*`（`pyproject.toml` 的 `omit` 与 `run_coverage.py` 的 `_OMIT` 两处）。
- Codecov 门槛是提示性的（`codecov.yml` 中 `informational: true`），不卡 PR，但新增业务代码应尽量带测试。

## CI / 发布

- **`.github/workflows/coverage.yml`**：两个 job。`coverage` 在 Python 3.13/3.14/3.15 矩阵跑 `python -m tests.run_coverage`，仅 3.13 上报 Codecov；`tests` 在同样矩阵跑 `python -m pytest -q`。两者都先从上游源码 `pip install -e` 宿主。
- **`.github/workflows/release.yml`**：`push` 到 `main` 且改动含 `**/*.py` 时触发（也可手动），job 级限制 `github.ref == 'refs/heads/main'`。版本取自 `metadata.yaml` 的 `version`（去掉可能的 `v` 前缀），tag 为 `v<version>`；tag 已存在则跳过发布，需重新发布先提升版本号。之后按白名单复制、打 zip、断言边界，再创建 Release 并附 zip 与 Sigstore 证据资产。
- **`.cnb.yml`**：`main` push 时只用 `git-sync` **强制覆盖**同步到 GitHub 镜像仓库（`github.com/xiaomizhoubaobei/astrbot_plugin_ots_memory`）；CNB 不跑测试、不打包。其 `vscode` 任务会把上游 AstrBot 克隆到 `/workspace/AstrBot` 并以 editable 安装，这是 CNB 开发环境里插件能导入的原因。
- **其他工作流**：CodeQL、Python 依赖审计、dependency-review、secret-scanning、Scorecard、tfsec、stale，以及 `ai-audit-scheduled.yml`（用 LLM 对 CodeQL 告警做分流并创建 Issue）。改这些工作流时保持既有的权限最小化、action 钉定提交 SHA、`persist-credentials: false` 与 harden-runner 约定。

## 改动落点

| 想做的事 | 需要同步改的地方 |
| --- | --- |
| 新增/修改配置项 | `_conf_schema.json`（UI 与默认值）+ `main.py` 的读取与默认值；必要时 README 配置表 |
| 新增 LLM 工具 | `main.py` 新增 `FunctionTool[AstrAgentContext]` dataclass（带 `plugin` 字段契约）+ 在 `__init__` 里 `add_llm_tools` + `tests/test_main.py` |
| 新增/修改上游 API | `client.py` 新增方法并复用 `_request` + `tests/test_client.py`（断言 payload/头/错误契约） |
| 新增随插件发布的文件 | `.github/workflows/release.yml` 的复制白名单与边界断言 |
| 改行为 | 同步 README、`CONTRIBUTING.md`、`AGENTS.md` 的口径，避免文档与代码漂移 |

## 代码规范要点

- Python 3.10+；`black --target-version py312`、`flake8 --max-line-length=100 --extend-ignore=E203,W503`、`isort --profile black`、`mypy --ignore-missing-imports`、`pydocstyle --convention=google`。
- `mypy` 配了 `explicit_package_bases = true` + `mypy_path = ".."`，否则仓库根既像包根又像 workspace 会让 `tests/` 报「source file found twice」。
- `ai-audit/` 被 mypy / pydocstyle 排除：目录名含连字符，本身不是合法 Python 包名。
- 类型注解尽量具体，避免 `Any`（pydantic 工具的 `plugin` 字段是必要的例外）；核心逻辑、阈值、签名与正则需写中文注释说明「为什么」。
- 业务日志统一用 `astrbot.api.logger`，禁止 `print()`。

## Git 与协作

- 提交信息一律**中文**、Angular 格式 `<type>(<scope>): <subject>`，subject ≤ 50 字；`type` 取 `feat/fix/docs/style/refactor/perf/test/chore`。
- 每次 `git commit` 前先执行 `bash install_gpg_keys.sh`。提交后验 `git log -1 --format='%G?'` 必须是 `G` 或 `U`；推送前对 `origin/<branch>..HEAD` 逐条验签。不得用 `--no-verify`、`|| true` 或自行生成 GPG 密钥绕过。详见 `AGENTS.md` 1.5。
- 不直推 `main`，一律 PR。由于存在 GitHub 镜像同步，需在 CNB 侧开 PR 的同时，在 GitHub 镜像仓库创建同名、同分支、同变更的 PR；不要直接改镜像侧代码（会被下一次同步覆盖）。
- Issue 以 CNB 侧为唯一入口；GitHub 镜像是单向同步。
