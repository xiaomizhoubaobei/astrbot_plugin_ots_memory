# analytics：告警趋势

## 语法

```bash
socket analytics [options] [ "org" | repo <reponame>] [TIME]
```

支持的输入形态：无参数、`org`、`org 30`、`repo <name>`、`repo <name> 30`、`30`。

- 默认 `org` 范围、`TIME=30`。
- `TIME` 只能是 `7` / `30` / `90`。
- 仓库级必须给 `<reponame>`（Socket 侧登记的 slug）。
- **没有 `--org` 参数**：组织范围由 API Token 决定。
- 不支持旧版 `--scope` / `--repo` / `--time` 标志；仓库必须用位置参数 `repo <name>`。

## 选项与校验

| 选项 | 作用 |
| --- | --- |
| `--json` | 原始 JSON；与 `--markdown` 互斥 |
| `--markdown` | 聚合后的 Markdown 表格 |
| `--file <path>` | 写文件；必须同时给 `--json` 或 `--markdown` |
| 不加输出选项 | 交互式仪表盘；Agent 禁止裸调用 |

- `--json` + `--markdown` 同时出现会直接报输入错误。
- 无 Token 时可用 `--dry-run` 校验参数，输出 `[DryRun]: Bailing now`。

## 配额与权限

- 1 unit；`report:write`。

## 输出：`--json`

原始**日粒度数组**，不是 markdown 的聚合表：

```json
{
  "ok": true,
  "data": [
    {
      "created_at": "2026-11-21T00:00:00.000Z",
      "top_five_alert_types": { "malware": 1, "didYouMean": 2 },
      "total_critical_alerts": 3,
      "total_high_alerts": 5,
      "total_medium_alerts": 7,
      "total_low_alerts": 9,
      "total_critical_added": 1,
      "total_high_added": 2,
      "total_medium_added": 3,
      "total_low_added": 4,
      "total_critical_prevented": 0,
      "total_high_prevented": 1,
      "total_medium_prevented": 2,
      "total_low_prevented": 3
    }
  ]
}
```

指标固定为 12 个 `total_*`；`top_five_alert_types` 是「类型 → 次数」。

## 输出：`--markdown`

按日期聚合，包含 critical/high 的存量、added、prevented，medium/low 的 prevented，以及 Top 5 alert types。仓库级对 top types 取各日最大值，组织级取总和。

## 常用 jq

```bash
# 最新一天
jq '.data | sort_by(.created_at) | last'

# 窗口内 critical 告警总量
jq '[.data[].total_critical_alerts] | add'

# 按天看 critical
jq -r '.data | sort_by(.created_at)[] | [.created_at[0:10], .total_critical_alerts] | @tsv'

# 汇总 top alert types（组织口径）
jq '[.data[] | (.top_five_alert_types // {}) | to_entries[]]
    | group_by(.key)
    | map({type: .[0].key, count: (map(.value) | add)})
    | sort_by(-.count) | .[:5]'
```

## 示例

```bash
# 组织级，最近 7 天
socket analytics org 7

# 仓库级，最近 30 天，非交互
socket analytics --json repo astrbot_plugin_ots_memory 30

# 写 Markdown 报表
socket analytics --markdown --no-banner --no-spinner \
  --file socket-weekly.md repo astrbot_plugin_ots_memory 7
```

## 注意

- 仓库级查询前先用 `repository list --json` 确认真实 slug。
- 组织级没有仓库参数；`repo` 不是组织名。
- 空数据是正常结果，不是错误：`data` 为空数组。
