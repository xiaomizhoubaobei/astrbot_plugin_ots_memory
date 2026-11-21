# scan list / metadata / view / report / diff：扫描审计

## 命令总览

| 命令 | 用法 | 关键选项 |
| --- | --- | --- |
| `scan list` | `socket scan list [REPO [BRANCH]]` | `--branch`、`--page`、`--per-page`、`--sort`、`--direction`、`--from-time`、`--until-time` |
| `scan metadata` | `socket scan metadata <SCAN_ID>` | `--json` / `--markdown` |
| `scan view` | `socket scan view <SCAN_ID> [OUTPUT_FILE]` | `--stream`（仅配合 `--json`，ndjson） |
| `scan report` | `socket scan report <SCAN_ID> [OUTPUT_PATH]` | `--fold`、`--license`、`--short`、`--report-level` |
| `scan diff` | `socket scan diff <OLD_ID> <NEW_ID>` | `--depth`、`--file -` |

- 都支持 `--org` 覆盖默认组织。
- 配额 1 unit；权限 `full-scans:list`。

## scan list

```bash
socket scan list [REPO [BRANCH]] --json
```

- 可按仓库/分支过滤；不指定仓库时也可用 `--branch` 跨仓库过滤。
- `--from-time` / `--until-time` 是 Unix 时间戳。
- 排序：`--sort name|created_at`、`--direction asc|desc`；分页：`--page`、`--per-page`。

JSON 路径：`.data.results[]`，每项含 `id`、`html_report_url`、`created_at`、`repo`、`branch`。

```bash
# 最近一次扫描
jq -r '.data.results | sort_by(.created_at) | last | [.id, .branch, .created_at] | @tsv' scans.json
```

## scan metadata

```bash
socket scan metadata <SCAN_ID> --json
```

JSON 路径：`.data`。用于确认仓库、分支、提交、扫描时间等元信息。

## scan view

```bash
socket scan view <SCAN_ID> --json
socket scan view <SCAN_ID> --json --stream > stream.ndjson
```

- 原始扫描结果，适合需要完整数据时使用。
- `--stream` 只与 `--json` 搭配，按 ndjson 分块输出。

## scan report

```bash
socket scan report <SCAN_ID> [OUTPUT_PATH] --json
socket scan report <SCAN_ID> --fold=version --license --markdown
socket scan report <SCAN_ID> --short --json
```

- `--fold` 可选 `pkg` / `version` / `file` / `none`，把重复告警折叠到指定层级。
- `--license` 把 License 策略纳入结论。
- `--report-level` 决定纳入报告的最低策略层级。
- **不健康时进程非零退出**，即使没加 `--short`。
- `--short` 只输出 `{"ok":true,"data":{"healthy":true|false}}`。
- `--file` 可按扩展名 `.json` / `.md` 写盘；`-` 表示 stdout。

### JSON 结构

```json
{
  "ok": true,
  "data": {
    "includeLicensePolicy": false,
    "orgSlug": "my-org",
    "scanId": "00000000-0000-0000-0000-000000000000",
    "options": { "fold": "version", "reportLevel": "error" },
    "healthy": false,
    "alerts": {
      "pypi": {
        "aiohttp": {
          "3.14.5": {
            "requirements.txt": {
              "1:1": {
                "type": "cve",
                "policy": "error",
                "url": "https://socket.dev/...",
                "manifest": ["requirements.txt"]
              }
            }
          }
        }
      }
    }
  }
}
```

`alerts` 是 `生态 → 包 → 版本 → 文件 → 行:列 → 告警`。

### 常用 jq

```bash
# 只看成败
jq '.data.healthy'

# 告警条数
jq '[.data.alerts | .. | objects | select(has("policy"))] | length'

# 按 type 聚合 error 级告警
jq '[.data.alerts | .. | objects | select(.policy == "error") | .type]
    | group_by(.) | map({type: .[0], count: length}) | sort_by(-.count)'

# 列出涉及的生态/包
jq '.data.alerts | to_entries[] | {ecosystem: .key, packages: (.value | keys)}'
```

## scan diff

```bash
socket scan diff <OLD_ID> <NEW_ID> --json --file diff.json
```

- 第一个 ID 被视为较旧，影响 added/removed 的方向。
- 输出可能很大，建议 `--json --file diff.json` 落盘后再分析；`--file -` 强制 stdout。
- JSON 路径：`.data`，含 `diff_report_url` 等字段。

## 常见用法

```bash
# PR 前后对比
socket scan diff "$OLD_SCAN" "$NEW_SCAN" --json --file diff.json

# 发布前复核 License 与 error 级告警
socket scan report "$SCAN_ID" --license --fold=version --json

# 只拿 healthy 给脚本用
socket scan report "$SCAN_ID" --short --json | jq -e '.data.healthy'
```
