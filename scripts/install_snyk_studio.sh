#!/usr/bin/env bash
#
# 为 Claude Code 配置 Snyk Studio（MCP 工具 + 安全钩子 + 修复命令与技能）。
#
# 对应官方 Getting Started：
#   https://docs.snyk.io/agent-security/agentic-security-with-snyk-studio/getting-started-with-snyk-studio
# 前置条件：Snyk CLI >= 1.1307.4（由 scripts/install_snyk_cli.sh 安装）。
#
# 认证：
#   - 设置了 SNYK_TOKEN（如 CNB 密钥）时，脚本用 API token 完成认证；
#   - 否则跳过认证，新开 Claude Code 会话后按 MCP 提示完成 `snyk auth`。
#
# 只配置用户级（--scope user）：安装器把 MCP 配置合并进 ~/.claude.json，
# 把安全钩子合并进 ~/.claude/settings.json，并复制 /snyk-fix 等命令。
# 安装或升级 CLI 后需重新执行本脚本，并新开 Claude Code 会话使配置生效。
#
# 用法：./scripts/install_snyk_studio.sh
# 可用 SNYK_STUDIO_ADES 覆盖目标 ADE（默认 claude，多个用逗号分隔）。

set -euo pipefail

ADES="${SNYK_STUDIO_ADES:-claude}"

if ! command -v snyk >/dev/null 2>&1; then
    echo "❌ 未找到 snyk，请先运行 scripts/install_snyk_cli.sh" >&2
    exit 1
fi

echo "Snyk CLI: $(snyk --version)"

if [ -n "${SNYK_TOKEN:-}" ]; then
    # 1.1293+ 默认走 OAuth 浏览器流程；无人值守场景必须显式使用 API token。
    snyk auth --auth-type=token "$SNYK_TOKEN" >/dev/null
    echo "✅ 已用 SNYK_TOKEN 完成认证"
else
    echo "⚠️  未设置 SNYK_TOKEN，跳过认证；请在新 Claude Code 会话中按 MCP 提示执行 snyk auth"
fi

# 显式指定用户级：配置写入当前用户的 ~/.claude.json 与 ~/.claude/settings.json。
snyk studio install --experimental --ade="$ADES" --scope user
# 校验安装资产与配置是否就位；对合并型配置文件只检查存在性。
snyk studio install --experimental --verify --ade="$ADES" --scope user

echo "Snyk Studio安装完成（新开 Claude Code 会话后生效）"
