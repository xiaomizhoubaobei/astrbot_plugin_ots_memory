# 安装、鉴权与排障

## 1. 检查与安装

```bash
command -v socket && socket --version
node --version
```

- `socket` 有输出：已安装。
- `node` 缺失或低于 22：先装 Node.js 22+。

```bash
# 从 nodejs.org 装当前 LTS，或用 nvm
nvm install 22
nvm use 22

# 全局安装 Socket CLI
npm install -g socket
socket --version
```

需要「检查→按需安装」：

```bash
command -v socket >/dev/null 2>&1 || npm install -g socket
```

这会修改全局 npm 环境，仅在确认需要时执行。

## 2. 鉴权

```bash
# 交互式：持久保存 Token，并配置默认 org
socket login

# 非交互 / CI：仅对本次命令生效
SOCKET_CLI_API_TOKEN=<token> socket analytics --help
```

- 旧变量名 `SOCKET_SECURITY_API_TOKEN` 仍兼容。
- 组织相关命令还需要默认 org：
  - `scan create`：用 `--org <slug>`；
  - `ci`：没有 `--org`，用 `SOCKET_CLI_ORG_SLUG=<slug>` 或 `socket config set defaultOrg <slug>`；
  - `scan list` / `scan report` / `repository list` 等：可用 `--org` 覆盖。
- `analytics` 没有 `--org`，组织范围由 Token 决定。
- 可用 `--config '<json>'` 或 `SOCKET_CLI_CONFIG` 传入整套配置。
- 想固定 CI 默认参数，可提交 `socket.json`（由 `socket scan setup` 生成）；结构见 [`advanced.md`](advanced.md)。
- 完整环境变量清单见 [`advanced.md`](advanced.md)。
- **不得**在命令、日志或回复中回显 Token，也不要把 Token 写进仓库。

## 3. 权限与配额

| 命令 | 配额 | 权限 |
| --- | --- | --- |
| `analytics` | 1 unit | `report:write` |
| `scan create` / `ci` | 1 unit | `full-scans:create` |
| `scan list/metadata/view/report/diff` | 1 unit | `full-scans:list` |
| `package score/shallow` | **100 units** | `packages:list` |
| `repository list/view` | 1 unit | `repo:list` |
| `scan reach` / `scan github` | 1 unit | `full-scans:create` |
| `scan del` | 1 unit | `full-scans:delete` |
| `organization dependencies/list` | 1 unit | 见 `--help` |
| `organization policy license` | 1 unit | `license-policy:read` |
| `threat-feed` | 1 unit + 许可 | `threat-feed:list` |

权限不足时 CLI 会明确报权限名；配额耗尽时不要重试，缩小范围或改用低成本命令。

## 4. CI 中注入

### GitHub Actions

```yaml
env:
  SOCKET_CLI_API_TOKEN: ${{ secrets.SOCKET_CLI_API_TOKEN }}
  SOCKET_CLI_ORG_SLUG: ${{ vars.SOCKET_ORG_SLUG }}

steps:
  - run: npm install -g socket
  - run: |
      socket scan create \
        --org "$SOCKET_CLI_ORG_SLUG" \
        --repo "${{ github.event.repository.name }}" \
        --branch "${GITHUB_HEAD_REF:-${GITHUB_REF_NAME}}" \
        --report --report-level error \
        --exclude-paths AstrBot \
        --no-interactive .
```

### CNB

把 Token 与 org 放进平台密钥/环境变量，步骤里只引用变量名：

```bash
SOCKET_CLI_API_TOKEN="$SOCKET_CLI_API_TOKEN" \
SOCKET_CLI_ORG_SLUG="$SOCKET_CLI_ORG_SLUG" \
socket scan create --org "$SOCKET_CLI_ORG_SLUG" --repo astrbot_plugin_ots_memory \
  --report --report-level error --exclude-paths AstrBot --no-interactive .
```

## 5. 常见问题

| 现象 | 处理 |
| --- | --- |
| 安装后 `socket: command not found` | npm 全局 bin 不在 `PATH`。用 `npm prefix -g` 查前缀，把 `<prefix>/bin`（Windows 为 `<prefix>`）加入 `PATH` 后重开终端。 |
| `EACCES` / `permission denied` | 不要用 `sudo`。改用 nvm，或 `npm config set prefix ~/.npm-global`，再把 `~/.npm-global/bin` 加入 `PATH`。 |
| `Unsupported engine` 或语法错误 | Node.js 低于 22，升级后重装。 |
| `401` / `Auth Error` | `socket login` 或设置 `SOCKET_CLI_API_TOKEN`。 |
| 提示需要 org / `org slug is required` | `scan create` 加 `--org`；`ci` 设 `SOCKET_CLI_ORG_SLUG` 或 `socket config set defaultOrg <slug>`。 |
| 权限不足 | 对照权限表换 Token。 |
| 配额耗尽 | 停止重试；缩小 `analytics` 时间窗，避免高频 `package score/shallow`。 |
| `--dry-run` 报缺少 TARGET | `scan create --dry-run` 不会自动补 `.`，显式传 TARGET。 |
| 扫描结果混入上游依赖 | 加 `--exclude-paths AstrBot`（或对应目录），并确认没有漏掉其他克隆/构建目录。 |
| `--exclude-paths` 被拒绝 | 去掉 `!` 取反、绝对路径、`..`、`.` / `**` / `/` 等匹配一切的模式；`{a,b}` 交替也不支持。 |
| 仓库级 analytics 找不到仓库 | 先用 `repository list --json` 确认真实 slug，不要按 git remote 猜。 |
| 交互式仪表盘卡住 | 非 TTY/Agent 环境不要裸调 `analytics`，加 `--json` 或 `--markdown`。 |

## 6. 验证安装与参数

```bash
socket --version
socket analytics --help
socket scan create --help

# 封装脚本预检（不打印 Token）
python .claude/skills/socket-analytics/scripts/socket_helper.py preflight

# 无 Token 也能校验参数（不消耗配额）
socket analytics --json repo test-repo 7 --dry-run --no-banner --no-spinner
socket ci --dry-run --no-banner --no-spinner
socket package score pypi aiohttp --json --dry-run --no-banner --no-spinner
```

`--dry-run` 输出 `[DryRun]: Bailing now` 即参数通过校验；它不代表扫描/查询真的成功。
