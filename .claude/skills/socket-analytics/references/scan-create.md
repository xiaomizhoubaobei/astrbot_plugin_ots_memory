# scan create / ci：扫描与依赖门禁

## scan create

```bash
socket scan create [options] [TARGET...]
```

### TARGET

- 交互模式会询问是否使用 `.`。
- `--no-interactive` 的真实运行会回落到 `.`；但 `--dry-run` 不会，所以**示例一律显式写 `.`**。

### 组织与仓库

- org：`--org` > 配置里的 `defaultOrg`；`--no-interactive` 且两者都没有时直接退出。**CI 必须传 `--org`**。
- repo/branch：未给时从 git 推断；CI 建议显式传 `--repo` / `--branch`。
- PR 号可用 `--pull-request` 传入。

### 选项

| 选项 | 作用 |
| --- | --- |
| `--org <slug>` | 强制指定组织；CI 必填 |
| `--repo <name>` / `--branch <name>` | 关联仓库/分支 |
| `--commit-hash` / `--commit-message` / `--committers` | 提交元数据 |
| `--pull-request <n>` | PR 号 |
| `--report` | 等待扫描完成并输出策略报告 |
| `--report-level <level>` | `defer` < `ignore` < `monitor` < `warn` < `error`，默认 `error` |
| `--exclude-paths <glob>` | 排除扫描根下的路径；可逗号分隔或重复传参 |
| `--default-branch` | 把本次扫描设为默认分支基准，只需在 main 上做一次 |
| `--no-set-as-alerts-page` | 不把本次扫描设为告警页的 pending head（默认会设） |
| `--tmp` | 临时扫描，会禁用 pending head |
| `--uv-members` | 按 `uv.lock` 扫描每个 TARGET 的完整依赖图，需要 `uv` |
| `--read-only` | 可读远程但停在创建报告之前 |
| `--cwd <path>` | 扫描根 |
| `--json` / `--markdown` | 非交互输出，二者互斥 |
| `--no-interactive` | 禁止任何交互提示 |
| `--auto-manifest` | 先跑 `socket manifest auto`，面向 Gradle/Maven/.NET 等 |

### `--exclude-paths`

- 相对扫描根的 micromatch：`AstrBot` 只匹配扫描根下的 `AstrBot`；任意深度用 `**/AstrBot`。
- 同时作用于 SCA 清单发现和可达性分析（启用 `--reach` 时）。
- 拒绝：`!` 取反、绝对路径、`..` 逃逸、`.` / `**` / `/` 等匹配一切的模式、括号不平衡的 glob、`{a,b}` 交替（值会被逗号拆分）。

```bash
# 排除上游宿主克隆，显式扫描当前目录
socket scan create --org my-org --repo my-repo --branch main \
  --report --report-level error --exclude-paths AstrBot \
  --no-interactive .
```

### 输出与退出

- `--report` 会等待扫描并按策略给出结论；不健康时进程非零退出。
- 不加 `--report` 只创建扫描，适合先看扫描 ID。
- `--json` / `--markdown` 控制输出格式；脚本中加 `--no-banner --no-spinner` 保持 stdout 干净。

## ci

```bash
socket ci [options]
```

`socket ci` 是 `scan create --report` 的**受限别名**，不是完整透传：

| 行为 | 值 |
| --- | --- |
| TARGET | 固定 `['.']` |
| `reportLevel` | 固定 `error` |
| `interactive` | 固定 `false` |
| `excludePaths` | 固定 `[]` |
| 输出 | 固定 JSON |
| 额外选项 | 仅 `--auto-manifest`，以及全局 `--dry-run` / `--no-banner` / `--no-spinner` 等 |

因此 **`ci` 不支持** `--org` / `--repo` / `--branch` / `--exclude-paths` / `--report-level` / `--json` / `--markdown`。

- org 解析顺序：配置 `defaultOrg` → `SOCKET_CLI_ORG_SLUG` → 调 API 查 Token 所属组织。
- 会根据 `GITHUB_REF=refs/pull/<n>/...` 自动带 PR 号。
- 策略不通过时非零退出。

```bash
# 无排除需求的简写
SOCKET_CLI_API_TOKEN=... SOCKET_CLI_ORG_SLUG=my-org socket ci --no-banner --no-spinner
```

## CI 示例

```bash
# 需要排除目录时：用 scan create
socket scan create \
  --org "$SOCKET_ORG" \
  --repo astrbot_plugin_ots_memory \
  --branch "${GITHUB_HEAD_REF:-main}" \
  --report --report-level error \
  --exclude-paths AstrBot \
  --no-interactive .
```

## dry-run

```bash
socket scan create --org test-org --report --exclude-paths AstrBot \
  --no-interactive --dry-run .
```

- 无 Token 也能做参数校验，成功时输出 `[DryRun]: Bailing now`。
- `--dry-run` 不会自动补 TARGET，省略 `.` 会报 `At least one TARGET (missing)`。
- `--dry-run` 不代表扫描真的执行。

## 配额与权限

- 1 unit；`full-scans:create`。
