# 结果解读与处置

## 先分清两个维度

| 维度 | 来源 | 含义 |
| --- | --- | --- |
| `severity` | 告警自身 | `low` / `middle` / `medium` / `high` / `critical`，表示风险强度 |
| `policy` | 组织策略 | `defer` < `ignore` < `monitor` < `warn` < `error`，决定是否影响 `healthy` |

**`policy=ignore` 不代表安全**，只表示默认不因此阻断。`severity=critical` 但 `policy=ignore` 的告警仍应人工判断。

## healthy 是怎么判定的

`healthy` 取决于报告级别（report level）：没有 `policy` 达到或高于该级别的告警，即为 healthy。

| 场景 | 默认 report level |
| --- | --- |
| `socket ci` | 固定 `error` |
| `socket scan create --report` | `error` |
| `socket scan report` | `warn` |
| 显式 `--report-level` | 以传入值为准；`defer` 表示纳入全部 |

因此同一个扫描：

- `ci` 可能 PASS（只看 error）；
- `scan report` 可能 FAIL（warn 也算）。

汇报时必须带上 report level，否则「通过/不通过」没有意义。

## 高信号告警类型

| 类型 | 默认策略 | 含义 | 建议处置 |
| --- | --- | --- | --- |
| `malware` | error | 明确恶意包 | 阻断合并；移除依赖；轮换可能泄露的密钥 |
| `gptMalware` | ignore | LLM 判定的疑似恶意 | 人工复核，按 `malware` 处理 |
| `criticalCVE` | warn | 严重漏洞 | 升级到修复版本；无补丁则替换或缓解 |
| `mediumCVE` / `mildCVE` | monitor | 中低危漏洞 | 排期升级，不必阻断 |
| `cve` | ignore | 一般 CVE | 结合可达性与利用条件评估 |
| `potentialVulnerability` | ignore | 潜在漏洞 | 人工确认是否适用 |
| `didYouMean` | warn | 疑似拼写错误/仿冒包 | 核对包名；替换为目标包 |
| `troll` | warn | 恶意/恶搞包 | 移除 |
| `compromisedSSHKey` | ignore | 包内泄露 SSH 密钥 | 视为高危；移除并轮换密钥 |
| `gitDependency` / `httpDependency` | warn | 依赖来自 git/HTTP 而非注册表 | 改为固定版本 + 注册表依赖 |
| `obfuscatedFile` | warn | 文件被混淆 | 审查来源；无法解释则移除 |
| `installScripts` | ignore | 安装期执行脚本 | 审查生命周期脚本；必要时禁用 scripts |
| `shellAccess` | ignore | 可执行 shell | 审查调用路径，评估是否必需 |
| `networkAccess` | ignore | 运行期网络访问 | 评估数据外发风险 |
| `filesystemAccess` | ignore | 文件系统访问 | 评估越权读写风险 |
| `envVars` | ignore | 读取环境变量 | 评估密钥泄露风险 |
| `debugAccess` | ignore | 调试/进程访问 | 评估沙箱逃逸风险 |
| `telemetry` | monitor | 遥测上报 | 隐私/合规评估 |
| `deprecated` | monitor | 已废弃 | 规划替换 |
| `unmaintained` | ignore | 缺乏维护 | 规划替换或 fork |
| `unpopularPackage` | monitor | 使用量低 | 评估替代方案 |
| `unstableOwnership` | monitor | 所有权频繁变更 | 关注供应链风险 |
| `shrinkwrap` | monitor | 锁定文件异常 | 检查 lockfile 一致性 |
| `highEntropyStrings` | ignore | 高熵字符串 | 排查硬编码密钥 |
| `invisibleChars` / `homoglyphs` / `bidi` / `zeroWidth` | ignore | 不可见字符/同形字 | 排查代码隐藏 |
| `copyleftLicense` / `nonpermissiveLicense` | ignore | 许可证限制 | 法务评估；必要时替换 |
| `licenseSpdxDisj` | warn | SPDX 表达式歧义 | 法务确认实际许可 |
| `noLicenseFound` / `missingLicense` | ignore | 未声明许可证 | 合规风险；要求上游补充或替换 |
| `socketUpgradeAvailable` | ignore | 有可用升级 | 非安全问题，按需升级 |

## 默认策略全量名单

以下是 Socket 公开默认策略（组织可覆盖）。`ignore` 不等于无风险，只是默认不阻断。

- **error（1）**：`malware`
- **warn（7）**：`criticalCVE`, `didYouMean`, `gitDependency`, `httpDependency`, `licenseSpdxDisj`, `obfuscatedFile`, `troll`
- **monitor（7）**：`deprecated`, `mediumCVE`, `mildCVE`, `shrinkwrap`, `telemetry`, `unpopularPackage`, `unstableOwnership`
- **ignore（85）**：`ambiguousClassifier`, `badEncoding`, `badSemver`, `badSemverDependency`, `bidi`, `binScriptConfusion`, `chromeContentScript`, `chromeHostPermission`, `chromePermission`, `chromeWildcardHostPermission`, `chronoAnomaly`, `compromisedSSHKey`, `copyleftLicense`, `cve`, `debugAccess`, `deprecatedLicense`, `deprecatedException`, `dynamicRequire`, `emptyPackage`, `envVars`, `explicitlyUnlicensedItem`, `extraneousDependency`, `fileDependency`, `filesystemAccess`, `floatingDependency`, `gitHubDependency`, `gptAnomaly`, `gptDidYouMean`, `gptMalware`, `gptSecurity`, `hasNativeCode`, `highEntropyStrings`, `homoglyphs`, `installScripts`, `invalidPackageJSON`, `invisibleChars`, `licenseChange`, `licenseException`, `longStrings`, `majorRefactor`, `manifestConfusion`, `minifiedFile`, `miscLicenseIssues`, `missingAuthor`, `missingDependency`, `missingLicense`, `missingTarball`, `mixedLicense`, `modifiedException`, `modifiedLicense`, `networkAccess`, `newAuthor`, `noAuthorData`, `noBugTracker`, `noLicenseFound`, `noREADME`, `noRepository`, `noTests`, `noV1`, `noWebsite`, `nonOSILicense`, `nonSPDXLicense`, `nonpermissiveLicense`, `notice`, `obfuscatedRequire`, `peerDependency`, `potentialVulnerability`, `semverAnomaly`, `shellAccess`, `shellScriptOverride`, `socketUpgradeAvailable`, `suspiciousStarActivity`, `suspiciousString`, `trivialPackage`, `typeModuleCompatibility`, `uncaughtOptionalDependency`, `unclearLicense`, `unidentifiedLicense`, `unmaintained`, `unpublished`, `unresolvedRequire`, `unsafeCopyright`, `unusedDependency`, `urlStrings`, `usesEval`

## 分诊顺序

1. **恶意/欺诈**：`malware`、`gptMalware`、`compromisedSSHKey`、`troll` —— 先阻断。
2. **可直接利用的漏洞**：`criticalCVE`，结合可达性和修复版本。
3. **供应链行为**：`installScripts`、`shellAccess`、`networkAccess`、`obfuscatedFile`、`didYouMean`、`gitDependency`。
4. **License/合规**：`licenseSpdxDisj`、`copyleftLicense`、`nonpermissiveLicense`。
5. **维护性/噪音**：`deprecated`、`unmaintained`、`unpopularPackage`、元数据类 `ignore` 项。

## 处置手册

| 场景 | 动作 |
| --- | --- |
| 明确恶意包 | 立即移除；检查 lockfile；轮换 CI/部署密钥；排查是否已运行安装脚本 |
| 严重 CVE | 升级到修复版本；无修复则替换；记录临时缓解措施与到期时间 |
| 拼写/仿冒风险 | 核对包名与发布者；替换为官方包；固定版本 |
| 安装脚本/网络/文件访问 | 审查脚本内容；评估必要性；无法接受则替换 |
| 混淆/不可见字符 | 审查源码；无法解释则视为高危 |
| License 风险 | 法务确认；替换依赖或取得例外 |
| 维护性差 | 排期替换；至少固定版本并监控 |
| 误报 | 走组织策略例外流程并记录原因，不要直接忽略 `malware` |

## 汇报模板

```markdown
## Socket 依赖体检

- 范围：<org / repo>，最近 <7/30/90> 天
- 结论：PASS / FAIL（report level = <error/warn/...>）
- 告警：error=<n> warn=<n> monitor=<n>
- 主要类型：<type:count, ...>
- 涉及包：<pkg@version, ...>
- 处置建议：<按分诊顺序给出 1-3 条>
- 备注：<是否为公开默认策略、是否含 License 策略、配额/权限限制>
```

单包评估可简化为：

```markdown
- 包：<purl>
- 自身总分：<overall>；含传递依赖：<overall>（依赖数 <n>）
- 低分维度：<lowest>
- 高危以上告警：<n>
- 建议：升级 / 替换 / 可接受
```

## 误报与策略

- 组织策略可覆盖公开默认值；以 `scan report` 返回的 `policy` 为准。
- 不要通过修改 CLI 或伪造报告来「消除」告警。
- 例外应有记录：包名、类型、原因、到期时间、批准人。
- `--license` 会把 License 策略纳入 healthy，做发布前复核时建议开启。
