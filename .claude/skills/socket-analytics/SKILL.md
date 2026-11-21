---
name: socket-analytics
description: 调用 Socket CLI 拉取组织或仓库的依赖安全分析数据。用户要求查看 Socket.dev 分析报表、依赖告警趋势、组织/仓库级安全统计，或明确提到 socket analytics 时使用。
---

# Socket Analytics

用 `socket analytics` 获取 Socket.dev 组织级或仓库级的依赖安全分析数据。该命令只读，不会修改仓库或依赖。

官方文档：<https://docs.socket.dev/docs/socket-analytics>

## 前置条件

- Node.js 22+；未安装 CLI 时见下方「安装指南」。
- 鉴权二选一：
  - 交互式登录（持久保存 API Token）：`socket login`
  - 单次通过环境变量传入：`SOCKET_CLI_API_TOKEN=<token> socket analytics ...`
    （旧变量名 `SOCKET_SECURITY_API_TOKEN` 仍兼容）
- Token 需具备 `report:write` 权限；每次调用消耗 1 个配额单位。
- **不得**在命令、日志或回复中回显 Token，也不要把 Token 写进仓库。

## 命令

```bash
socket analytics [options] [ "org" | repo <reponame>] [TIME]
```

- 默认范围：组织级，可省略 `org`。
- 仓库级：必须给出仓库 slug，例如 `repo test-repo`。
- `TIME` 只接受 `7`、`30`、`90`（天），省略时默认 `30`。

## 选项

| 选项 | 作用 |
| --- | --- |
| `--json` | JSON 输出，便于 `jq` 等工具处理 |
| `--markdown` | Markdown 输出，便于贴进 Issue / PR |
| `--file <path>` | 写入文件；**必须**同时指定 `--json` 或 `--markdown` |
| 不加输出选项 | 启动交互式终端仪表盘（`q` 或 `Esc` 退出） |

全局选项：`--no-banner`、`--no-spinner`、`--config`、`--dry-run`、`--help`、`--help-full`、`--version`。

## 示例

```bash
# 组织级，最近 7 天
socket analytics org 7

# 仓库级，最近 30 天
socket analytics repo test-repo 30

# 组织级，最近 90 天
socket analytics 90

# 非交互输出
socket analytics --json repo test-repo 30
socket analytics --json --no-spinner --no-banner org 7

# 写入文件
socket analytics --markdown --file analytics.md org 90
```

## 安装指南（未安装时）

### 1. 检查现状

```bash
command -v socket && socket --version
node --version
```

- `socket` 有输出：已安装，直接跳到第 4 步「鉴权」。
- `node` 缺失或低于 22：先执行第 2 步。
- 确认未安装后执行第 3 步。

### 2. 安装 Node.js 22+（仅在缺失或版本过低时）

从 <https://nodejs.org/> 安装当前 LTS，或使用 nvm：

```bash
nvm install 22
nvm use 22
node --version
```

nvm 自身的安装见 <https://github.com/nvm-sh/nvm>。

### 3. 全局安装 Socket CLI

```bash
npm install -g socket
socket --version
```

需要「检查→按需安装」一条命令时：

```bash
command -v socket >/dev/null 2>&1 || npm install -g socket
```

该命令会修改全局 npm 环境，仅在确认需要安装时执行。

### 4. 鉴权

```bash
# 交互式：持久保存 Token 并配置 CLI 默认值
socket login

# 非交互 / CI：仅对本次命令生效
SOCKET_CLI_API_TOKEN=<token> socket analytics --help
```

### 5. 验证安装

```bash
socket --version
socket analytics --help
```

能打印版本与命令帮助即安装完成；真正取数时再检查登录状态与 `report:write` 权限。

### 常见问题

| 现象 | 处理 |
| --- | --- |
| 安装后 `socket: command not found` | npm 全局 bin 不在 `PATH`。用 `npm prefix -g` 查前缀，把 `<prefix>/bin`（Windows 为 `<prefix>`）加入 `PATH` 后重开终端。 |
| `EACCES` / `permission denied` | 不要用 `sudo`。改用 nvm，或设置用户级前缀：`npm config set prefix ~/.npm-global`，再把 `~/.npm-global/bin` 加入 `PATH`。 |
| `Unsupported engine` 或语法错误 | Node.js 低于 22，升级后重新 `npm install -g socket`。 |
| 提示未登录 / `401` | 运行 `socket login`，或设置 `SOCKET_CLI_API_TOKEN`（旧名 `SOCKET_SECURITY_API_TOKEN`）。 |
| 提示权限不足 | 检查 Token 是否具备 `report:write` 权限。 |

## 执行纪律

1. Agent 或脚本调用必须带 `--json` 或 `--markdown`；裸调用会进入交互式仪表盘并阻塞会话。
2. `--file` 不能单独使用，必须与 `--json` 或 `--markdown` 搭配。
3. `TIME` 只传 `7` / `30` / `90`，不要传其它数值或日期区间。
4. 仓库级查询先确认仓库 slug；不确定时先用组织级查询。
5. 鉴权失败、权限不足或配额耗尽时，原样转述错误并提示 `socket login` 或设置 `SOCKET_CLI_API_TOKEN`，不要反复重试。
6. 需要进一步处理 JSON 时优先用 `jq` 管道，例如：

   ```bash
   socket analytics --json org 30 | jq .
   ```
