# socket_helper.py

Socket CLI 的轻量封装，只用 Python 标准库。它负责三件事：

1. 预检 Node / socket / Token / org；
2. 调用 `socket`，统一加 `--json --no-banner --no-spinner`；
3. 把 JSON 信封压成可读摘要，或把原始 JSON 落盘。

## 前置

- Python 3.10+
- Node.js 22+
- `socket` CLI（`npm install -g socket`）
- 凭据按 Socket CLI 的方式提供：`socket login` 或 `SOCKET_CLI_API_TOKEN` / `SOCKET_CLI_ORG_SLUG`

脚本**不读取、不打印 Token**，也不会写 `socket config list --full`。

## 命令

```bash
HELPER=.claude/skills/socket-analytics/scripts/socket_helper.py

# 预检
python "$HELPER" preflight
python "$HELPER" preflight --json

# 告警趋势（默认组织级、30 天）
python "$HELPER" analytics --days 7
python "$HELPER" analytics --repo astrbot_plugin_ots_memory --days 30
python "$HELPER" analytics --repo astrbot_plugin_ots_memory --days 7 \
  --json-out analytics.json

# 扫描报告摘要（不健康时退出码 2）
python "$HELPER" scan-report <SCAN_ID>
python "$HELPER" scan-report <SCAN_ID> --fold version --license --json

# 单包深度评分
python "$HELPER" package-score pypi aiohttp
python "$HELPER" package-score pypi aiohttp --json-out score.json

# 多包浅分
python "$HELPER" package-shallow pypi pytest pytest-asyncio coverage

# 仓库 slug
python "$HELPER" repos --filter ots
python "$HELPER" repo-view astrbot_plugin_ots_memory
```

每个命令都支持：

| 选项 | 作用 |
| --- | --- |
| `--json` | 摘要以 JSON 输出 |
| `--json-out PATH` | 原始 socket 信封写盘 |
| `--dry-run` | 只做参数校验，不消耗配额；无 Token 时也可用，但涉及组织的命令仍需 `--org` 或默认 org |

## 退出码

| 码 | 含义 |
| --- | --- |
| `0` | 成功；`scan-report` 表示 healthy |
| `1` | 预检失败，或 socket/JSON/网络错误 |
| `2` | `scan-report` 返回 unhealthy |

## 输出示例

```text
$ python socket_helper.py analytics --repo astrbot_plugin_ots_memory --days 7
范围: repo:astrbot_plugin_ots_memory / 最近 7 天 / 数据点 7
告警总量: critical=3 high=5 medium=7 low=9
新增: critical=1 high=2 medium=3 low=4
已拦截: critical=0 high=1 medium=2 low=3
最新一天 2026-11-21T00:00:00.000Z: critical=0 high=1
Top 类型: malware=2, criticalCVE=1
```

## 注意

- 摘要字段来自 Socket 原始 JSON；字段缺失时显示 `-` 或 `0`，不代表接口错误。
- `scan-report --short` 只输出 `healthy=true|false`。
- 原始 JSON 可能包含包名、扫描 ID 等；不要把它和 Token 一起贴到公开 Issue。
- 需要更细的 jq 处理时，用 `--json-out` 落盘后按命令文件里的字段路径处理。
