---
name: vector-knowledge
description: 读写阿里云 OSS 向量知识库（按仓库隔离）。任务开始召回结论、收尾沉淀踩坑经验、检索或导入知识文档时使用。
---

# 向量知识库

阿里云上海 OSS 向量 Bucket 是组织级语义知识池，**按仓库隔离**：每条向量带 `repo` 元数据，检索时由服务端过滤，只召回当前仓库内容。只存结论性知识，不存任务流水、日志或密钥。

## 连接信息

- Bucket：`cnb-knowledge-base`
- 索引：`cnbknowledge`（`cn-shanghai`，1024 维 float32，cosine）
- 范围：**仅收纳 `XMZZUZHI/Astrbot/*` 子组织**；其他子组织不写入
- 工具：`.claude/skills/vector-knowledge/scripts/vector_ingest.py`（纯标准库，自实现百炼 embedding 与 OSS V4 签名，详细参数见同目录 `scripts/README.md`）

## 何时用

- **任务开始**：先检索当前仓库，命中优先复用；空结果属正常，不重试。
- **任务收尾**：仅当产出跨仓库可复用结论（平台约定、踩坑解法、字段口径）时写入。
- **不要用**：一次性任务、只依赖当前上下文、未脱敏的敏感信息。

## 命令

以下命令均从仓库根目录执行：

```bash
VECTOR_INGEST=.claude/skills/vector-knowledge/scripts/vector_ingest.py

# 0. 自检：验证 OSS 凭证、Bucket 与索引可访问
python "$VECTOR_INGEST" --check

# 1. 检索当前仓库（repo 默认从 origin 自动识别）
python "$VECTOR_INGEST" --query "<关键词或报错原文>" --top-k 5

# 2. 显式指定仓库
python "$VECTOR_INGEST" --repo "XMZZUZHI/Astrbot/astrbot_plugin_github_webhook" \
  --query "<关键词>" --top-k 5

# 3. 写入单个文件或目录（--kind / --tag 可选）
python "$VECTOR_INGEST" --kind pitfall --tag cnb docs/05-troubleshooting.md
python "$VECTOR_INGEST" --kind knowledge --tag cnb docs/

# 4. 写入并清理同来源中已不存在的旧切片
python "$VECTOR_INGEST" --prune docs/

# 5. 跨仓库检索（仅在明确需要组织级复用时使用）
python "$VECTOR_INGEST" --all-repos --query "<关键词>" --top-k 5

# 6. 仓库级审计
python "$VECTOR_INGEST" --list-repos

# 7. 删除：先 dry-run 核对数量，再加 --yes
python "$VECTOR_INGEST" --delete --repo "<仓库标识>" --dry-run
python "$VECTOR_INGEST" --delete --repo "<仓库标识>" --yes

# 8. 只删除某个来源的默认主键
python "$VECTOR_INGEST" --delete --repo "<仓库标识>" \
  --source docs/05-troubleshooting.md --dry-run
python "$VECTOR_INGEST" --delete --repo "<仓库标识>" \
  --source docs/05-troubleshooting.md --yes
```

环境变量：`DASHSCOPE_API_KEY`、`ALIBABA_CLOUD_ACCESS_KEY_ID`、`ALIBABA_CLOUD_ACCESS_KEY_SECRET`、`OSS_VECTOR_ACCOUNT_ID`。

## 输出与限制

- 写入成功会输出切片数与写入条数；`--dry-run` 只打印切片计划，不调用 API。
- `--prune` 在写入成功后删除同来源中已不存在的旧切片；`--dry-run` 会跳过远端检查。
- `--delete` 非 dry-run 必须加 `--yes`；`--source` 只删默认主键，自定义 JSONL `key` 不受影响。
- 检索输出 key、distance 与 `repo/source/title/kind/chunk/tags` 元数据；`--json` 输出原始结构。

| 限制 | 值 |
| --- | --- |
| 单次嵌入请求文本数 | 10 |
| 单次 `PutVectors` 向量数 | 500 |
| `--top-k` | 1~500 |
| 向量维度 | 默认 1024，必须与索引一致 |
| 索引更新延迟 | 写入后约数十秒 |

## 输出示例

```text
$ python "$VECTOR_INGEST" --query "GPG unknown_key" --top-k 3
scope: XMZZUZHI/Astrbot/astrbot_plugin_ots_memory
1. cnb:...  distance=0.12
   repo: XMZZUZHI/Astrbot/astrbot_plugin_ots_memory
   source: docs/05-troubleshooting.md
   title: GPG 签名
```

```text
$ python "$VECTOR_INGEST" --kind pitfall docs/05-troubleshooting.md
完成：42 个切片，写入 42 条向量到 cnb-knowledge-base/cnbknowledge
```

## 故障排查

| 现象 | 处理 |
| --- | --- |
| 401/403 | 检查 `ALIBABA_CLOUD_ACCESS_KEY_*`、账号 ID 与 Bucket 权限 |
| 404 / `NoSuchIndex` | 检查 `--bucket`、`--index`、`--region` 是否匹配 |
| 维度不一致 | 让 `--dimension` 与索引维度一致（默认 1024） |
| 429/5xx | 脚本会指数退避重试；仍失败时降低 `--embed-batch-size` / `--vector-batch-size` |
| 检索为空 | 索引更新有延迟；确认 `repo` 过滤是否正确，必要时用 `--all-repos` 排查 |
| 无法识别仓库 | origin 缺失或格式特殊时显式传 `--repo` |
| 删除被拒绝 | 非 dry-run 删除必须加 `--yes` |
| `--prune` 未执行 | `--dry-run` 会跳过远端检查，去掉 `--dry-run` 再执行 |

## 安全

- 凭证只从环境变量读取，不写入命令行参数，避免出现在进程列表。
- 错误信息默认只保留 status/code/request_id；`--debug` 才会附带 message 与响应体，**不要**在共享 CI 日志中开启。
- 删除不可逆：先 `--dry-run` 核对数量，再 `--yes`。
- 知识库是增强能力：调用失败只告警，不阻断主任务。

## 纪律

1. 写入必须落在具体仓库；`--all-repos` 只用于检索。
2. 同一仓库、同一来源重复写入会覆盖同序号切片；文件变短时用 `--prune` 或 `--delete --source` 清理。
3. 写入内容写清「结论 + 适用场景」，一条切片只讲一件事。
4. 写入后索引有约数十秒延迟，刚写入的内容可能暂时检索不到。
5. 仓库级清理使用 `--delete --repo`，删除前必须先跑 `--dry-run` 核对数量。
6. 详细参数、批量导入与故障排查见技能目录下的 `scripts/README.md`。
