#!/usr/bin/env bash
#
# 安装 Snyk CLI（官方独立二进制版）。
#
# 为什么不用 `npm install -g snyk`：
#   1. 不依赖 Node.js/npm，开发镜像里少一层运行时；
#   2. 官方为独立二进制提供 GPG 签名的校验和清单，可校验供应链完整性。
#
# 校验顺序（任一失败即退出）：
#   1. 用官方公钥验 `sha256sums.txt.asc` 的 GPG 签名，并核对公钥指纹；
#   2. 按已验签的清单校验 `snyk-linux[-arm64]` 的 SHA-256；
#   3. 校验通过后才安装到 /usr/local/bin/snyk。
#
# 只装 CLI，不做认证：交互式认证用 `snyk auth`，CI 里用 SNYK_TOKEN 环境变量。
# 用法：./scripts/install_snyk_cli.sh（已提交可执行位；换检出环境丢权限时先 chmod +x）

set -euo pipefail

SNYK_BASE="https://downloads.snyk.io/cli/stable"
SNYK_GPG_KEY_URL="https://raw.githubusercontent.com/snyk/cli/master/help/_about-this-project/snyk-code-signing-public.pgp"
# Snyk 官方公布的代码签名公钥指纹；指纹不符即中止，防止公钥被替换。
SNYK_GPG_FPR="467717A30B2B4658415975629691DA64D0025194"

# 显式判断架构：CNB 开发容器为 linux/amd64，换架构时也不会装错包。
case "$(uname -m)" in
    x86_64 | amd64) SNYK_ASSET="snyk-linux" ;;
    aarch64 | arm64) SNYK_ASSET="snyk-linux-arm64" ;;
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

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

curl --compressed -fsSL "$SNYK_BASE/sha256sums.txt.asc" -o "$work/sha256sums.txt.asc"
curl -fsSL "$SNYK_GPG_KEY_URL" -o "$work/snyk-code-signing-public.pgp"

# 独立 GNUPGHOME：不污染容器原有密钥环，也便于随临时目录清理。
export GNUPGHOME="$work/gnupg"
mkdir -m 700 "$GNUPGHOME"
gpg --batch --quiet --import "$work/snyk-code-signing-public.pgp"

actual_fpr="$(gpg --batch --with-colons --fingerprint code-signing@snyk.io |
    awk -F: '/^fpr:/ {print $10; exit}')"
if [ "$actual_fpr" != "$SNYK_GPG_FPR" ]; then
    echo "❌ Snyk 公钥指纹不符: $actual_fpr" >&2
    exit 1
fi

# 签名有效才信任清单内容；验签失败时 set -e 直接中止。
gpg --batch --verify "$work/sha256sums.txt.asc"

curl --compressed -fsSL "$SNYK_BASE/$SNYK_ASSET" -o "$work/$SNYK_ASSET"
(
    cd "$work"
    grep " $SNYK_ASSET$" sha256sums.txt.asc | sha256sum -c -
)

sudo install -m 0755 "$work/$SNYK_ASSET" /usr/local/bin/snyk
snyk --version
echo "Snyk CLI安装完成"
