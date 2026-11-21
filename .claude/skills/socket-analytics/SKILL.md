---
name: socket-analytics
description: 用 Socket CLI 做依赖安全分析：analytics 告警趋势、scan create / ci 扫描与 PR 门禁、package score / shallow 包评分、scan report/diff 审计、结果解读与处置，以及 cdxgen SBOM 与 threat-feed。用户提到 Socket.dev、socket CLI / socket analytics、依赖安全扫描、供应链告警、包评分、依赖门禁或漏洞分诊时使用。
---

# Socket CLI 依赖安全分析

覆盖「看趋势 → 卡 PR → 评单包 → 读报告 → 处置」的完整链路。按任务读对应文件，不要一次加载全部。

## 文件导航

| 文件 | 内容 |
| --- | --- |
| [`references/analytics.md`](references/analytics.md) | 告警趋势：参数、原始 JSON、Markdown、jq |
| [`references/scan-create.md`](references/scan-create.md) | `scan create` / `ci`：扫描、排除路径、PR 门禁 |
| [`references/scan-audit.md`](references/scan-audit.md) | `scan list/metadata/view/report/diff`：审计与报告 |
| [`references/package.md`](references/package.md) | `package score/shallow`：包评分与解读 |
| [`references/repository.md`](references/repository.md) | `repository list/view`：确认仓库 slug |
| [`references/interpretation.md`](references/interpretation.md) | 告警类型、severity/policy、分诊与处置、汇报模板 |
| [`references/advanced.md`](references/advanced.md) | `scan setup/reach/del/github`、`organization`、`config`、环境变量 |
| [`references/optional.md`](references/optional.md) | `cdxgen` SBOM、`threat-feed` |
| [`references/setup.md`](references/setup.md) | 安装、鉴权、权限配额、CI 注入、排障 |
| [`scripts/socket_helper.py`](scripts/socket_helper.py) | 预检、取数、摘要封装；用法见 [`scripts/README.md`](scripts/README.md) |

## 何时用 / 何时不用

**适合用**：

- 新增、升级或替换依赖前的信任评估；
- PR 里出现 lockfile / `requirements*.txt` 变更，需要供应链门禁；
- 周期性依赖体检、License 复核、组织内依赖排查；
- 看到 CVE 或恶意包告警，需要分诊和处置建议。

**不适合用**：

- 第一方代码漏洞（用 CodeQL 等 SAST）；
- 运行期防护或入侵检测；
- 没有 Token/配额时的强制门禁；
- 纯文档、注释类改动。

**与其他工具的分工**：

| 工具 | 负责 |
| --- | --- |
| Dependabot | 版本更新与已知 CVE 提醒 |
| CodeQL | 第一方代码安全分析 |
| Socket | 第三方依赖的供应链行为、恶意/仿冒、License、维护性、策略门禁 |

Socket 与 Dependabot 在 CVE 上有重叠，但 Socket 还覆盖安装脚本、混淆、遥测、拼写仿冒等信号；两者互补，不能互相替代。

## 先选命令

| 目标 | 命令 | 详见 |
| --- | --- | --- |
| 看组织/仓库告警趋势 | `socket analytics [org\|repo <slug>] [7\|30\|90]` | analytics |
| 扫描并卡 PR | `socket scan create --report ... .` | scan-create |
| 无排除需求的门禁简写 | `socket ci` | scan-create |
| 审计历史扫描 | `socket scan list/metadata/view/report/diff` | scan-audit |
| 评估单个包 | `socket package score pypi <pkg>` | package |
| 只评估包自身 | `socket package shallow pypi <pkg>...` | package |
| 确认 Socket 侧仓库名 | `socket repository list --json` | repository |
| 解读告警/决定怎么处理 | severity + policy 分诊 | interpretation |
| 固定 CI 默认值/远程扫描 | `scan setup` / `scan github` / `scan reach` | advanced |
| 生成 SBOM | `socket cdxgen -o bom.json` | optional |
| 查恶意/仿冒包 | `socket threat-feed pypi mal` | optional |

## 前置检查

```bash
node --version      # >= 22
socket --version
# 鉴权：socket login 或 SOCKET_CLI_API_TOKEN
```

CI 与本地不同：

1. **Token**：用 `SOCKET_CLI_API_TOKEN` 注入，不写进仓库或日志。
2. **org**：`scan create --no-interactive` 且无默认 org 时必须 `--org`；`ci` 没有 `--org`，用 `SOCKET_CLI_ORG_SLUG`。
3. **TARGET**：`scan create` 建议显式写 `.`；`--dry-run` 下不会自动补全。

## 快速开始（封装脚本）

```bash
HELPER=.claude/skills/socket-analytics/scripts/socket_helper.py

python "$HELPER" preflight                          # 检查 node/socket/token/org
python "$HELPER" analytics --repo <slug> --days 7   # 趋势摘要
python "$HELPER" scan-report <SCAN_ID> --license    # 健康摘要；不健康退出码 2
python "$HELPER" package-score pypi aiohttp         # 单包评分摘要
python "$HELPER" package-shallow pypi pytest coverage
python "$HELPER" repos --filter ots                 # 找仓库 slug
```

- 所有命令支持 `--json`（摘要 JSON）、`--json-out PATH`（原始 JSON）、`--dry-run`（只校验参数）。
- 脚本不读取/打印 Token；凭据仍由 Socket CLI 管理。
- 需要细粒度 jq 时，先用 `--json-out` 落盘，再按对应命令文件的字段路径处理。

## 常用工作流

### PR 门禁

```bash
socket scan create \
  --org "$SOCKET_ORG" --repo astrbot_plugin_ots_memory \
  --branch "${GITHUB_HEAD_REF:-main}" \
  --report --report-level error \
  --exclude-paths AstrBot --no-interactive .
```

需要排除路径时必须用 `scan create`；`ci` 硬编码 `excludePaths: []`、`reportLevel: error`、`targets: ['.']`，不能传这些参数。详见 [`references/scan-create.md`](references/scan-create.md)。

### 趋势报表

```bash
socket analytics --markdown --file socket-weekly.md repo astrbot_plugin_ots_memory 7
```

`--json` 是原始日粒度数组，`--markdown` 是聚合表，二者互斥；`analytics` 没有 `--org`。详见 [`references/analytics.md`](references/analytics.md)。

### 单包评估

```bash
socket package score pypi aiohttp --markdown
socket package shallow pypi pytest pytest-asyncio coverage --json
```

每次 100 units；分数与子项解读见 [`references/package.md`](references/package.md)。

### 审计与分诊

```bash
socket scan list --json
socket scan report <SCAN_ID> --fold=version --license --json
socket scan diff <OLD> <NEW> --json --file diff.json
```

`scan report` 不健康时非零退出；先看 `healthy`，再按 `policy` 和 `type` 分诊。告警类型与处置见 [`references/interpretation.md`](references/interpretation.md)。

## 输出与解读

- 成功：`{"ok":true,"data":...}`；失败：`{"ok":false,"message":...,"cause":...}`（输入校验错误可能用 `data`）。
- `severity` 是风险强度，`policy` 才决定 `healthy`；`policy=ignore` 不等于安全。
- `ci` / `scan create --report` 默认 `error` 级；`scan report` 默认 `warn` 级，所以同一扫描可能一个 PASS 一个 FAIL。
- 汇报时带上 report level、窗口、org/repo，否则结论不可复现。

## 关键约束

1. **`ci` ≠ `scan create`**：`ci` 只接受全局参数和 `--auto-manifest`。
2. **`--exclude-paths`**：相对扫描根；拒绝 `!` 取反、绝对路径、`..`、`.`/`**`/`/`、`{a,b}`。
3. **非交互**：Agent/CI 一律 `--no-interactive`；`analytics` 禁止裸调用。
4. **先校验**：无 Token 时用 `--dry-run` 验证参数；`scan create --dry-run` 需显式 TARGET。
5. **Token 卫生**：不打印、不落盘、不提交；禁止 `config list --full`。
6. **失败不重试**：鉴权/权限/配额错误原样转述。

## 故障排查

| 现象 | 处理 |
| --- | --- |
| `401` / Auth Error | `socket login` 或设置 `SOCKET_CLI_API_TOKEN` |
| 提示需要 org | `scan create --org`；`ci` 设 `SOCKET_CLI_ORG_SLUG` |
| 权限不足 / 配额耗尽 | 对照 [`references/setup.md`](references/setup.md) |
| 扫描混入上游依赖 | 检查 `--exclude-paths AstrBot` |
| 仓库级查询找不到仓库 | 用 `repository list` 确认真实 slug |
| 报告 PASS 但有高危告警 | 检查 report level；`ignore`/`monitor` 默认不阻断 |

## 执行纪律

1. 必须带 `--json` 或 `--markdown`（`ci` 固定 JSON）；交互式命令加 `--no-interactive`。
2. 用 `jq` 处理 JSON，字段路径写在对应命令文件里。
3. 仓库级查询先确认 slug，不要按 git remote 猜。
4. 扫描前排除 `AstrBot/`、`node_modules/`、构建产物等非本仓库依赖源。
5. 鉴权或配额失败时原样转述并给出下一步，不重试。
6. 分诊先看恶意/严重漏洞，再看供应链行为，最后处理维护性与噪音。
