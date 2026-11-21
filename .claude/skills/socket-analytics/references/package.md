# package：单包信任评估

## 语法

```bash
socket package score   pypi <pkg>[@version]
socket package shallow pypi <pkg> [<pkg> ...]
```

- `score` 计入包自身及全部传递依赖；`shallow` 只看包自身，可一次多个。
- 支持 `npm`、`pypi`、`nuget`、`gem`、`golang`、`maven`。
- 也接受 purl，如 `pkg:pypi/aiohttp@3.14.5`。
- 版本可选；给了就必须精确匹配。
- 输出：`--json` 原始结构、`--markdown` 可读报告；文本模式也会打印分数卡片。

## 配额与权限

- 每次调用 **100 units**；`packages:list`。
- 不要在高频循环或批量脚本里反复调用；`shallow` 可以一次传多个包。

## 分数解读

- 0–100，越高越健康。
- 浅分文本报告按 `>=80` 绿、`>=60` 黄、`<60` 红着色，可作团队阈值参考；官方没有统一及格线。
- 子项：`supplyChain` / `maintenance` / `quality` / `vulnerability` / `license`。
- `self` 只看包本身，`transitively` 是包 + 全部直接/传递依赖的合并结果。
- `transitively.lowest` 给出每个维度分数最低的依赖，用于定位「谁拉低了总分」。
- `alerts[].severity` 常见为 `low` / `medium` / `high` / `critical`；部分接口用 `middle`，按语义归入中危。

## score 的 JSON

```json
{
  "ok": true,
  "data": {
    "purl": "pkg:pypi/aiohttp@3.14.5",
    "self": {
      "purl": "pkg:pypi/aiohttp@3.14.5",
      "score": {
        "license": 100,
        "maintenance": 96,
        "overall": 94,
        "quality": 92,
        "supplyChain": 99,
        "vulnerability": 100
      },
      "capabilities": [],
      "alerts": [
        { "name": "...", "severity": "low", "category": "...", "example": "..." }
      ]
    },
    "transitively": {
      "dependencyCount": 12,
      "func": "...",
      "score": {
        "license": 90,
        "maintenance": 88,
        "overall": 87,
        "quality": 90,
        "supplyChain": 95,
        "vulnerability": 92
      },
      "lowest": {
        "license": "pkg:pypi/foo@1.0.0",
        "maintenance": "pkg:pypi/bar@2.0.0",
        "overall": "pkg:pypi/baz@3.0.0",
        "quality": "...",
        "supplyChain": "...",
        "vulnerability": "..."
      },
      "capabilities": [],
      "alerts": []
    }
  }
}
```

### 常用 jq

```bash
# 包自身与整体总分
jq '{self: .data.self.score.overall, all: .data.transitively.score.overall}' score.json

# 自身的高危以上告警
jq '[.data.self.alerts[] | select(.severity == "high" or .severity == "critical")]' score.json

# 哪个依赖拉低了各维度
jq '.data.transitively.lowest' score.json
```

## shallow 的 JSON

`data` 是 artifact 数组，常用字段：

```json
{
  "ok": true,
  "data": [
    {
      "ecosystem": "pypi",
      "namespace": "",
      "name": "pytest",
      "version": "9.1.1",
      "score": {
        "supplyChain": 100,
        "maintenance": 95,
        "quality": 90,
        "vulnerability": 100,
        "license": 100
      },
      "alerts": []
    }
  ]
}
```

```bash
# 包名、版本、总分（没有 overall 时显示 -）
jq -r '.data[] | [.name, .version, (.score.overall // "-")] | @tsv' shallow.json

# 有告警的包
jq '[.data[] | select((.alerts | length) > 0) | .name]' shallow.json
```

注意：shallow 的 `score` 通常只有各子项分数，不一定有 `overall`；要总分用 `score`（深分）。

## 示例

```bash
# 升级前评估运行期依赖
socket package score pypi aiohttp --markdown

# 一批开发依赖只看自身
socket package shallow pypi pytest pytest-asyncio coverage --json

# 无 Token 校验参数
socket package score pypi aiohttp --json --dry-run --no-banner --no-spinner
```
