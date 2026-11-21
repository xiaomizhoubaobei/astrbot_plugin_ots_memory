# 可选能力：cdxgen 与 threat-feed

这两个命令不是日常门禁的必需项，按需使用。

## cdxgen：本地 SBOM

```bash
socket cdxgen -o bom.json
```

- 本地调用 CycloneDX Generator，**不消耗 Socket API 配额**。
- `-o` 指定输出文件，默认 `bom.json`；`-t` 可显式指定项目类型，默认递归扫描当前目录并自动识别。
- 适合把 SBOM 作为 Release 资产附加，或交给其他供应链工具。

常用选项：

| 选项 | 作用 |
| --- | --- |
| `-o, --output <file>` | 输出路径（默认 `bom.json`） |
| `-t, --type <type>` | 项目类型；可重复 |
| `--exclude-type <type>` | 排除项目类型 |
| `--spec-version <1.4\|1.5\|1.6\|1.7>` | CycloneDX 规范版本，默认 1.6 |
| `--no-recurse` | 关闭递归 |
| `--no-install-deps` | 不自动安装依赖 |
| `--no-validate` | 跳过 schema 校验 |

示例：

```bash
# 生成 SBOM
socket cdxgen -o bom.json

# 打印为表格，便于人工检查
socket cdxgen -p
```

## threat-feed：恶意/仿冒包

```bash
socket threat-feed [ECOSYSTEM] [TYPE_FILTER]
socket threat-feed pypi mal --json
```

- Beta；需要 **Threat Feed 许可**，普通 Token 会失败。
- 生态：`gem`、`golang`、`maven`、`npm`、`nuget`、`pypi`。
- 类型：`mal`（默认，恶意/疑似恶意）、`anom`（异常）、`joke`（玩笑包）、`fp`（误报）、`secret`（泄露密钥）、`c`（不过滤）。
- 常用过滤：`--org`、`--pkg`、`--version`、`--page`、`--per-page`、`--direction`。

### 配额与权限

- 1 unit；`threat-feed:list` + 特殊许可。

### JSON

```json
{
  "ok": true,
  "data": {
    "results": [
      { "description": "..." }
    ]
  }
}
```

```bash
# 与当前依赖比对：先列出依赖名，再按包名查询
socket threat-feed pypi mal --pkg aiohttp --json
```

## 对本类项目不适用的命令

| 命令 | 原因 |
| --- | --- |
| `socket npm` / `npx` / `raw-npm` / `raw-npx` / `pnpm` / `yarn` / `wrapper` | 面向 Node 包管理器，本仓库没有 `package.json` |
| `socket fix` / `optimize` / `patch` | 面向 npm 依赖树 |
| `socket manifest auto` | 面向需要构建工具解析的生态；`requirements.txt` 本身是静态清单 |
| `socket audit-log` / `organization` | 组织管理操作，与日常依赖分析无关 |
