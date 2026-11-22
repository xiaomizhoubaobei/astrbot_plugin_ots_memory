#!/usr/bin/env bash
#
# 安装 Snyk CLI，并为 Claude Code 配置 Snyk Studio。
#
# CLI 部分：使用官方独立二进制（不依赖 npm/Node.js）：
#   1. 用固定指纹的官方公钥验 `sha256sums.txt.asc` 的 GPG 签名；
#   2. 按已验签的清单校验 `snyk-linux[-arm64]` 的 SHA-256；
#   3. 校验通过后才安装到 /usr/local/bin/snyk。
#
# Studio 部分（官方 Getting Started）：
#   https://docs.snyk.io/agent-security/agentic-security-with-snyk-studio/getting-started-with-snyk-studio
#   - 设置 SNYK_TOKEN（如 CNB 密钥）时用 API token 认证，否则留到新会话按 MCP 提示认证；
#   - 安装 MCP 工具、安全钩子、/snyk-fix 等命令与依赖健康检查技能；
#   - 安装后执行 --verify，并在结束时提示新开 Claude Code 会话。
#
# 安装或升级 CLI 后重新执行本脚本即可同步 Studio 配置。
# 用法：./scripts/install_snyk.sh
# 可用 SNYK_STUDIO_ADES 覆盖目标 ADE（默认 claude，多个用逗号分隔）。

set -euo pipefail

SNYK_BASE="https://downloads.snyk.io/cli/stable"
SNYK_GPG_KEY_URL="https://raw.githubusercontent.com/snyk/cli/master/help/_about-this-project/snyk-code-signing-public.pgp"
# Snyk 官方公布的代码签名公钥指纹；指纹不符即中止，防止公钥被替换。
SNYK_GPG_FPR="467717A30B2B4658415975629691DA64D0025194"
ADES="${SNYK_STUDIO_ADES:-claude}"

install_snyk_cli() {
    echo "==> 安装 Snyk CLI"

    # 显式判断架构：CNB 开发容器为 linux/amd64，换架构时也不会装错包。
    local asset
    case "$(uname -m)" in
        x86_64 | amd64) asset="snyk-linux" ;;
        aarch64 | arm64) asset="snyk-linux-arm64" ;;
        *)
            echo "❌ 不支持的架构: $(uname -m)" >&2
            exit 1
            ;;
    esac

    # gpg 用于验签；缺失时补装，保证脚本可脱离 .cnb.yml 单独运行。
    if ! command -v gpg >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y gnupg
    fi

    # 临时目录的生命周期覆盖整个 CLI 安装；失败时由 EXIT trap 清理。
    local work
    work="$(mktemp -d)"
    trap 'rm -rf "$work"' EXIT

    curl --compressed -fsSL "$SNYK_BASE/sha256sums.txt.asc" -o "$work/sha256sums.txt.asc"
    curl -fsSL "$SNYK_GPG_KEY_URL" -o "$work/snyk-code-signing-public.pgp"

    # 独立 GNUPGHOME：不污染容器原有密钥环，也便于随临时目录清理。
    export GNUPGHOME="$work/gnupg"
    mkdir -m 700 "$GNUPGHOME"
    gpg --batch --quiet --import "$work/snyk-code-signing-public.pgp"

    local actual_fpr
    actual_fpr="$(gpg --batch --with-colons --fingerprint code-signing@snyk.io |
        awk -F: '/^fpr:/ {print $10; exit}')"
    if [ "$actual_fpr" != "$SNYK_GPG_FPR" ]; then
        echo "❌ Snyk 公钥指纹不符: $actual_fpr" >&2
        exit 1
    fi

    # 签名有效才信任清单内容；验签失败时 set -e 直接中止。
    gpg --batch --verify "$work/sha256sums.txt.asc"

    curl --compressed -fsSL "$SNYK_BASE/$asset" -o "$work/$asset"
    (
        cd "$work"
        grep " $asset$" sha256sums.txt.asc | sha256sum -c -
    )

    sudo install -m 0755 "$work/$asset" /usr/local/bin/snyk
    snyk --version

    rm -rf "$work"
    unset GNUPGHOME
    trap - EXIT
}

install_snyk_studio() {
    echo "==> 配置 Snyk Studio（Claude Code）"
    if ! command -v snyk >/dev/null 2>&1; then
        echo "❌ 未找到 snyk，CLI 安装未完成" >&2
        exit 1
    fi

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
}

install_snyk_cli
install_snyk_studio

echo "Snyk CLI与Studio安装完成（新开 Claude Code 会话后生效）"
