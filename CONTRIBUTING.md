# 贡献指南（Contributing Guide）

感谢你愿意为本项目出力。这份文档只讲**本仓库真实生效的流程**——没有代码的仓库里
抄不到的规矩，这里也不写；凡是写在这里的，都能在仓库里找到对应文件对得上。

> 先说三件比代码更要紧的事：
> 1. 本插件保管的是用户的**长期记忆**，数据安全是不可让渡的底线；
> 2. 涉密信息（AccessKey、Token、私钥）**绝不**入代码、入日志、入 Issue / PR、入语音；
> 3. 参与即视为同意遵守 [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)，它写了本项目的专项约定。

## 目录

- [从哪里开始](#从哪里开始)
- [报告问题](#报告问题)
- [开发环境](#开发环境)
- [代码规范](#代码规范)
- [测试与覆盖率](#测试与覆盖率)
- [提交规范](#提交规范)
- [Pull Request 流程](#pull-request-流程)
- [文档与发布包边界](#文档与发布包边界)
- [安全问题](#安全问题)

## 从哪里开始

| 我想… | 去哪里 |
| --- | --- |
| 用起来 / 了解功能 | [`README.md`](README.md) |
| 报告 Bug、提功能建议 | [CNB Issue](https://cnb.cool/XMZZUZHI/Astrbot/astrbot_plugin_ots_memory/-/issues)（**唯一入口**，见下） |
| 报告安全漏洞 | **不要开公开 Issue**，见 [`SECURITY.md`](SECURITY.md) |
| 了解协作底线 | [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) |
| 让 Agent / NPC 帮忙改代码 | [`AGENTS.md`](AGENTS.md)（它同时是 Agent 的入口文档） |

> **Issue 以 CNB 为准**：GitHub 仓库是 CNB 主仓的**单向镜像**（`.cnb.yml` 里 `git-sync`
> 在 `main` 推送时强制覆盖），在镜像侧开的 Issue / PR 不会被同步回来。请到 CNB 侧提。

## 报告问题

提 Issue 前先搜一遍现有的 [Issues](https://cnb.cool/XMZZUZHI/Astrbot/astrbot_plugin_ots_memory/-/issues)，重复问题会被合并。

**Bug 报告**请带上：

- 问题描述与**最小复现步骤**
- 预期行为 / 实际行为
- 环境信息：AstrBot 版本、插件版本（`metadata.yaml` 的 `version`）、Python 版本、操作系统
- 相关日志。**注意脱敏**：本插件的日志与工具返回值刻意**不回显上游响应体**，
  工具侧只给固定中文提示（如「检索记忆失败，请稍后重试。」），
  排查靠日志里的 `status` 与截断后的 `request_id`——贴日志前请把 AK / SK 抹掉。

**功能建议**请讲清：想解决什么问题、为什么现有方案不够、你设想的实现方向。

## 开发环境

本插件以 **AstrBot** 为宿主（`astrbot_version >= 4.0.0`），`main.py` 依赖 `astrbot.api` /
`astrbot.core.*` 才能被导入，所以**宿主必须先装好，且一律取自上游源码**，不用 PyPI 的
`astrbot` 包（避免与上游代码形态漂移；`requirements-dev.txt` 因此也不声明该依赖）：

```bash
git clone https://cnb.cool/XMZZUZHI/Astrbot/astrbot_plugin_ots_memory.git
cd astrbot_plugin_ots_memory

git clone https://github.com/AstrBotDevs/AstrBot.git
pip install -e AstrBot                  # 宿主源码（editable）

pip install -r requirements-dev.txt      # 运行依赖 + 测试工具
pip install pre-commit                    # 提交前自检（见「代码规范」）
```

### 项目结构

```
.
├── main.py               # 插件入口：OTSMemoryPlugin、两个 LLM 工具、auto_record 钩子
├── client.py             # OTSMemoryClient：自研 OTS V4 签名 + SearchMemories / AddMemories
├── _conf_schema.json     # AstrBot 配置 schema
├── metadata.yaml         # 插件元数据（version / category / tags 等）
├── tests/                # 单测与覆盖率启动器（python -m tests.run_coverage）
├── ai-audit/             # AI 告警分流示例资产（不计入覆盖率分母）
├── .github/workflows/    # 覆盖率、CodeQL、安全扫描、Release 等
├── .cnb.yml              # CNB 流水线（只做同步到 GitHub 镜像，不打包）
└── AGENTS.md             # Agent 入口与协作规范
```

### 两个容易踩的坑

1. **工具返回值**：`ToolExecResult` 只是 `str | CallToolResult` 的联合别名，**不可当函数调用**；
   表达「出错」必须显式构造 `CallToolResult(isError=True)`，否则运行时抛
   `TypeError: 'types.UnionType' object is not callable`。
2. **工具上的插件引用**：宿主以 pydantic dataclass 声明 Tool，`plugin` 字段须标注为
   `Optional[Any]` 并用 `Field(exclude=True)` 排除序列化，直接标注插件类会抛
   `PydanticSchemaGenerationError`。

## 代码规范

核心代码为 **Python 3.10+**（CI 用 3.12 校验），提交前请务必跑一遍 pre-commit：

```bash
pre-commit install            # 可选：装 git hook 自动执行
pre-commit run --all-files    # 首次会联网安装各 hook 环境，稍慢
```

`.pre-commit-config.yaml` 覆盖：`black`（`--target-version py312`）、`flake8`
（`--max-line-length=100 --extend-ignore=E203,W503`）、`isort`（`--profile black`）、
`mypy`（`--ignore-missing-imports`）、`pydocstyle`（`--convention=google`），以及
文件卫生类钩子（EOF / 行尾空白 / 大文件 / 私钥检测 / 合并冲突标记等）。

关于 `black` 的 Python 版本：**不要**给它固定 `language_version`。`language_version` 未设置时，
pre-commit 用**当前运行 `pre-commit` 的那个系统 Python** 创建隔离的 hook 环境，`black` 跑在
这个解释器里，而不是某个自带独立解释器的镜像。所以只要求本机装好并处于 `PATH` 的 Python 受支持
（3.10+，因为 `black` 26.10.1 的 `requires-python` 就是 `>=3.10`）即可；写死小版本反而会让
「只装了 3.13」的环境找不到 `python3.12` 而失败。
代码目标版本由 `--target-version py312` 决定——它说的是「按 3.12 的语法/风格改写」，与钩子
用哪个解释器执行是两件事。

除此之外，几条本仓库的具体要求：

- **类型注解**：函数与关键变量必须标注，能写具体类型就别用 `Any`（`mypy` 会看）。
- **中文注释**：核心逻辑（控制流、并发调度）、关键阈值（`top_k` / `min_score` 取值边界）、
  正则与签名逻辑必须写明「为什么」，不是复述「做了什么」。
- **错误与日志**：所有 `async` 调用都要有 `try/except`，异常不得逃逸到对话链；
  统一用项目 `logger`，**禁止** `print()` 打业务日志；日志只留非敏感字段。
- **上游错误契约**：非 2xx 一律转中文 `RuntimeError`，文本只承载 `status` 与截断后的
  `x-ots-requestid`（≤64 字符），**不夹带响应体**；工具层返回固定中文提示，不回显堆栈。
- **签名不重写**：`client.py` 的 OTS V4 签名（HMAC-SHA256 + Canonical Request）不要为了
  「省事」引入庞大 SDK，也不要改成非标准实现。

## 测试与覆盖率

```bash
python -m tests.run_coverage              # 跑 tests + 打印报告 + 写 coverage.xml
python -m tests.run_coverage -- -k signing   # ``--`` 之后透传给 pytest
pytest tests -q                          # 只跑测试
```

为什么要用 `tests.run_coverage` 而不是 `coverage run --source=... -m pytest`：
后者在**启动阶段**解析 `--source`，此时 `conftest.py` 还没加载、插件包视图尚未建立，
于是只会警告 `Module ... was never imported` 并写出空报告。启动器先把顺序倒过来，
在**同一进程**里建好包视图再启动 coverage 与 pytest。

- 新增业务代码请**尽量带测试**：覆盖率门槛目前是**提示性**的（`codecov.yml` 里
  `informational: true`），不卡 PR，但别让 `main.py` / `client.py` 的覆盖线一路下滑。
- `tests/` 与 `ai-audit/` 不计入覆盖率分母（见 `pyproject.toml` 的 `omit`）。
- 单测与示例**一律使用假数据**，禁止触碰真实用户的记忆内容或真实 AK / SK。

## 提交规范

### 提交信息：一律中文，Angular 格式

```
<type>(<scope>): <subject>
```

`type` 取值：`feat` / `fix` / `docs` / `style` / `refactor` / `perf` / `test` / `chore`。
`subject` 不超过 50 字，**禁止**全英文描述。

```
✅ feat(main): 为 recall_memory 增加按 app_id 的命名空间过滤
✅ fix(client): 错误信息不再携带上游响应体
❌ fix: increase debounce timeout to 10 mins
❌ update main.py
```

### 提交必须签名

本仓库开启了 commit 签名。提交前**先**执行仓库根目录的脚本：

```bash
bash install_gpg_keys.sh
```

它负责拉取本人 GPG 密钥、设置终极信任、把 `user.signingkey` / `commit.gpgsign` 落盘，
并在末尾用真实 `git commit -S` + `git log --show-signature` 做**签名闭环自检**，失败即
`exit 1`。几条硬规矩：

- **严禁**跳过脚本直接 `git commit`（`docs` / `chore` 等非代码提交同样不豁免）。
- **严禁**自行生成 GPG 密钥：新密钥未登记到平台会被判 `unknown_key`，等同未签名。
- 推送前自检：`git config --get user.signingkey` 非空、`git config --get commit.gpgsign`
  为 true、`gpg --list-secret-keys` 能看到私钥——三者缺一即视为「未接管」，先重跑脚本。
- 脚本报错就**如实上报**报错行与已执行步骤，交给人判断；**不要**在业务代码里打补丁掩盖。

> 脚本需要密钥仓库注入的 `GPG_KEY` / `PLUGIN_GPG_KEY`（私钥解锁短语），缺失会直接报错退出，
> 不会猜测或拼接。CNB 平台默认签名器是 `cnb-gpgsign`，该脚本用于「触发者本人密钥亲自签名」的场景。

## Pull Request 流程

### 分支与 PR

1. 从 `main` 拉分支，命名如 `feat/xxx`、`fix/xxx`、`docs/xxx`。
2. **不直推 `main`**：所有变更一律走 PR，保证可审查、可追溯（除非维护者明确要求直推）。
3. PR 标题沿用提交信息格式，例如 `feat(client): 支持自定义重试次数`。
4. PR 描述写清四件事：**变更说明 / 动机 / 如何验证 / 关联 Issue**（`Closes #123`）。

### 双端同步（强制）

`.cnb.yml` 在 `main` 推送时用 `git-sync` 把代码**强制覆盖**同步到 GitHub 镜像仓库
（`github.com/xiaomizhoubaobei/astrbot_plugin_ots_memory`）。因此：

- 在 CNB 侧开 PR 的同时，请在 **GitHub 镜像仓库**创建**同名、同分支、同变更**的 PR；
- 不要在镜像侧直接改代码——改动会在下一次同步时被覆盖；
- 发布包（zip）与 Release **只在 GitHub 侧产出**，CNB 不打包。

### PR 检查清单

- [ ] `pre-commit run --all-files` 通过
- [ ] `python -m tests.run_coverage` 通过，新增逻辑尽量带测试
- [ ] 提交信息为中文、Angular 格式，且**已签名**
- [ ] 无涉密信息：AK / SK / Token / 用户真实记忆数据均未出现在代码、日志、测试与截图里
- [ ] 改了行为就同步改了文档（README / 本文件 / `AGENTS.md` 相应章节）
- [ ] 新增**随插件发布**的文件时，已加入 `release.yml` 的复制白名单（见下）
- [ ] 若 `.cnb.yml` 的 GitHub 同步仍生效，已同步创建镜像侧 PR

代码审查：所有 PR 都需审查，请积极响应意见；讨论对事不对人，有依据的反对意见同样受欢迎。

## 文档与发布包边界

### 文档规范

- 公共函数与类写 docstring，风格为 **Google convention**（`pydocstyle` 会检查）。
- 改行为就改文档：README（面向使用者）、`AGENTS.md`（面向 Agent 与协作者）、
  本文件（面向贡献者）三处口径要一致，别让文档和代码漂移。
- 参数表、示例、报错文案须与代码**同源**；有疑问时以 `--help` / 实际代码为准。

### 发布包里放什么

发布包只含 AstrBot 加载插件真正会读的文件：

```
main.py  __init__.py  client.py
metadata.yaml  requirements.txt  _conf_schema.json
logo.png（可选）
```

打包是**两步**：

1. `release.yml` 先按**复制白名单**把上面这几个文件 `cp` 进空的构建目录——构建目录里**只有**
   白名单里的东西，这就是包内容的**唯一边界**；
2. 再整目录 `zip`，并断言包内只允许出现白名单条目（含可选的 `logo.png`），混入其它文件即中断。

`AGENTS.md`、本文件、`CODE_OF_CONDUCT.md`、`SECURITY.md`、`install_gpg_keys.sh`、`ai-audit/`、
`.github/`、`tests/` 这些开发 / CI 资产压根不会被复制进构建目录，因此它们**天然不在包里**；
最后那道断言是兜底，防止日后有人往白名单里加东西时顺手把风险资产带出去——它们不会被宿主加载，
却会随包落进使用者的插件目录，其中拉私钥、改全局 git 配置的脚本一旦被下游误执行，
风险不该这样传递。

> 口径只有一条：**新增需要随插件发布的文件**（宿主会读取）→ 改 `release.yml` 的**复制白名单**，
> 否则它不会进包；新增仅供开发 / CI 的顶层文件什么也不用做，它本来就不会被复制。

## 安全问题

发现漏洞**不要**开公开 Issue。请走 GitHub
[私密漏洞报告](https://github.com/xiaomizhoubaobei/astrbot_plugin_ots_memory/security/advisories/new)
或邮件 `qixiaoxin@stu.sqxy.edu.cn`（标题注明 `[SECURITY] astrbot_plugin_ots_memory`）。
支持范围、报告清单、响应时限与不在范围内的情形，以 [`SECURITY.md`](SECURITY.md) 为唯一权威。

## 许可证

通过提交贡献，你同意你的贡献按本项目的 [AGPL-3.0](LICENSE) 授权。

## 致谢

感谢每一位愿意花时间把它做得更好的人——包括那些只写了一句能复现的 Issue 的人。
