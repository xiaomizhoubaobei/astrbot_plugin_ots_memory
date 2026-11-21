# 进阶命令与环境变量

日常用不到，但在固定 CI 配置、远程扫描、组织级排查时会用到。

## scan setup 与 socket.json

```bash
socket scan setup [CWD=.]
```

- 交互式生成 `socket.json`，为 `scan create` / `scan github` 保存默认参数。
- 生成的文件可以提交到仓库共享，也可以加入 `.gitignore`。
- `--default-on-read-error` 在读取失败时使用默认配置，可能覆盖已有文件，慎用。

### socket.json 结构

`scan create` 会读取 `defaults.scan.create` 下的这些键：

```json
{
  "defaults": {
    "scan": {
      "create": {
        "repo": "astrbot_plugin_ots_memory",
        "workspace": "",
        "branch": "main",
        "autoManifest": false,
        "report": true
      }
    }
  }
}
```

- 命令行显式参数优先于 `socket.json`。
- 没有交互环境时，可以直接提交上述文件，省去 CI 里的重复参数。
- `org` 不在这个文件里：用 `--org`、`defaultOrg` 配置或 `SOCKET_CLI_ORG_SLUG`。

## scan reach：可达性分析

```bash
socket scan reach [options] [CWD=.]
```

- 只做可达性分析，不创建扫描；结果写入 `.socket.facts.json`（可用 `--output` 指定，必须以 `.json` 结尾）。
- 配额 1 unit；权限 `full-scans:create`。
- 支持的生态包括 `pypi`、`npm`、`maven`、`nuget`、`golang`、`gem`、`cargo`、`composer`。
- 常用选项：
  - `--exclude-paths <glob>`：同 `scan create`，相对扫描根。
  - `--reach-advisories <GHSA|CVE,...>`：只分析指定公告。
  - `--reach-ecosystems <eco,...>`：限定生态。
  - `--reach-analysis-memory-limit` / `--reach-analysis-timeout` / `--reach-concurrency`：资源控制。
  - `--reach-continue-on-*`：分析/安装/缺 lockfile 时是否继续。
  - `--reach-disable-dependency-downloads`：只用已安装依赖。
  - `--reach-retain-facts-file`：保留报告文件。
- 输出可能很大；需要机器处理时加 `--json`。

```bash
socket scan reach --exclude-paths AstrBot --reach-ecosystems pypi --json
```

## scan del：删除扫描

```bash
socket scan del <SCAN_ID> [--org <slug>] [--json]
```

- 配额 1 unit；权限 `full-scans:delete`。
- **不可逆**。删除前确认 ID 与组织；批量清理时先 `scan list --json` 核对。
- 失败时原样转述错误，不要循环重试。

## scan github：不检出代码也能扫

```bash
socket scan github [options] [CWD=.]
```

- 从 GitHub 拉取文件创建扫描，不需要本地 clone。
- 配额 1 unit；权限 `full-scans:create`。
- 需要 GitHub Token，至少具备仓库 contents 只读权限：
  - `--github-token`，或环境变量 `GITHUB_TOKEN` / `SOCKET_CLI_GITHUB_TOKEN`。
- 常用选项：`--repos repo1,repo2`、`--all`、`--org-github`、`--github-api-url`、`--org`。
- 不能运行 `--auto-manifest`，因为它需要本地构建环境。

```bash
SOCKET_CLI_GITHUB_TOKEN=... socket scan github --repos astrbot_plugin_ots_memory --org my-org --json
```

## organization：组织级排查

```bash
socket organization list --json
socket organization dependencies [--purls pkg:pypi/requests] [--limit N] [--offset N] --json
socket organization policy license --json
```

| 命令 | 用途 | 配额 | 权限 |
| --- | --- | --- | --- |
| `organization list` | 列出 Token 关联的组织 | 1 | 见 `--help` |
| `organization dependencies` | 查某依赖在组织内的使用情况 | 1 | 见 `--help` |
| `organization policy license` | 读取 License 策略 | 1 | `license-policy:read` |

```bash
# 某个包在组织内哪些仓库被使用
socket organization dependencies --purls pkg:pypi/aiohttp --json
```

## config：本地配置

```bash
socket config list [--json]          # 不要加 --full，避免明文 Token
socket config get defaultOrg
socket config set defaultOrg my-org
socket config unset defaultOrg
```

可用键：

| 键 | 作用 |
| --- | --- |
| `apiBaseUrl` | Socket API 地址 |
| `apiProxy` | API 代理 |
| `apiToken` | API Token（**不要打印**） |
| `defaultOrg` / `org` | 默认组织 slug |
| `enforcedOrgs` | 强制执行策略的组织列表 |
| `skipAskToPersistDefaultOrg` | 不询问是否持久化默认组织 |

- `config set` 不做值校验，服务端可能拒绝；改错用 `config unset` 恢复。
- 禁止运行 `socket config list --full` 或 `config get apiToken`，避免 Token 进入日志。

## 环境变量

| 变量 | 用途 |
| --- | --- |
| `SOCKET_CLI_API_TOKEN` | API Token（旧名 `SOCKET_SECURITY_API_TOKEN`） |
| `SOCKET_CLI_ORG_SLUG` | 默认组织 slug，`ci` 尤其需要 |
| `SOCKET_CLI_CONFIG` | JSON 字符串形式的配置 |
| `SOCKET_CLI_API_BASE_URL` | 覆盖 API 地址 |
| `SOCKET_CLI_API_PROXY` | API 代理；也兼容 `HTTPS_PROXY` / `HTTP_PROXY` |
| `SOCKET_CLI_API_TIMEOUT` | API 超时（毫秒） |
| `SOCKET_CLI_DEBUG` | 开启 CLI 调试日志 |
| `SOCKET_CLI_NO_API_TOKEN` | 强制不使用默认 Token |
| `SOCKET_CLI_GITHUB_TOKEN` | `scan github` 的 GitHub Token（别名 `GITHUB_TOKEN`） |
| `SOCKET_CLI_GITHUB_API_URL` | GitHub API 地址 |
| `SOCKET_CLI_GIT_USER_NAME` / `SOCKET_CLI_GIT_USER_EMAIL` | CLI 执行 git 操作时的身份 |
| `SOCKET_CLI_ACCEPT_RISKS` / `SOCKET_CLI_VIEW_ALL_RISKS` | npm/npx 包装器的风险确认 |
| `SOCKET_CLI_NPM_PATH` / `SOCKET_CLI_SOCKET_PATCH_PATH` | 包装器/补丁工具路径 |

## 其他有用参数

| 参数 | 作用 |
| --- | --- |
| `--tmp` | 临时扫描，仪表盘可见性控制；会禁用 pending head |
| `--read-only` | 可读远程但停在创建报告之前 |
| `--no-set-as-alerts-page` | 不更新告警页的 pending head |
| `--workspace <name>` | 关联 Socket 组织内的 workspace |
| `--uv-members` | 按 `uv.lock` 扫描每个目标的完整依赖图 |
| `--cwd <path>` | 指定扫描根 |
| `--config '<json>'` | 单次覆盖本地配置 |

`scan del`、`scan reach`、`scan github`、`organization` 都属于低频高影响命令：执行前先确认组织、仓库和 ID，再运行。
