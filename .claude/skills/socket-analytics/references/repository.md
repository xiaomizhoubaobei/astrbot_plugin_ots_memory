# repository：仓库 slug 与元数据

## 用途

仓库级 `analytics`、`scan create`、`scan report` 都依赖 Socket 侧登记的仓库名。**不要根据 git remote 猜**，尤其 origin 指向 CNB 等非 GitHub 地址时。

## 命令

```bash
socket repository list [--all] [--page N] [--per-page N] [--sort field] [--direction asc|desc] [--json]
socket repository view <REPO> [--json]
```

- `list --all` 忽略分页，拉全量。
- `view` 查看单个仓库详情（可见性、默认分支、主页、是否归档等）。
- 两者都支持 `--org` 覆盖默认组织。

## 配额与权限

- 1 unit；`repo:list`。

## JSON 路径

| 命令 | 路径 | 字段 |
| --- | --- | --- |
| `repository list --json` | `.data.data.results[]` | `id`、`name`、`visibility`、`default_branch`、`archived` |
| `repository view --json` | `.data` | 单个仓库详情 |

注意 `list` 多一层 `data`：`.data.data.results[]`。

## 常用 jq

```bash
# 列出所有仓库名与默认分支
jq -r '.data.data.results[] | [.name, .default_branch] | @tsv' repos.json

# 模糊查找
jq -r '.data.data.results[] | select(.name | test("ots_memory")) | .name' repos.json
```

## 示例

```bash
# 确认本仓库在 Socket 侧的 slug
socket repository list --json | jq -r '.data.data.results[].name'

# 查看单个仓库
socket repository view astrbot_plugin_ots_memory --markdown
```
