#!/usr/bin/env bash
set -euo pipefail

NODE_VERSION="${NODE_VERSION:-24.18.0}"
HAPI_VERSION="${HAPI_VERSION:-0.20.2}"
CLAUDE_VERSION="${CLAUDE_VERSION:-2.1.196}"
SERVICE_ROOT="${HAPI_SERVICE_ROOT:-/data/kltst/homework/services/hapi}"
RUNTIME_ROOT="$SERVICE_ROOT/runtime"
NODE_HOME="$RUNTIME_ROOT/node-v$NODE_VERSION"
GLOBAL_HOME="$RUNTIME_ROOT/global"
BIN_HOME="$RUNTIME_ROOT/bin"
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

if [[ "$(id -u)" -eq 0 ]]; then
  echo "请使用 kltst 普通账号运行本脚本，不要使用 root。" >&2
  exit 1
fi

for command_name in curl tar sha256sum awk; do
  command -v "$command_name" >/dev/null || {
    echo "缺少系统命令：$command_name" >&2
    exit 1
  }
done

mkdir -p "$SERVICE_ROOT"
temporary=$(mktemp -d "/tmp/eduflow-hapi-runtime.XXXXXX")
cleanup() {
  case "$temporary" in
    /tmp/eduflow-hapi-runtime.*) rm -rf -- "$temporary" ;;
    *) echo "拒绝清理异常临时目录：$temporary" >&2 ;;
  esac
}
trap cleanup EXIT

archive="node-v${NODE_VERSION}-linux-x64.tar.xz"
base_url="https://nodejs.org/dist/v${NODE_VERSION}"
echo "下载并校验 Node.js ${NODE_VERSION}..."
curl --fail --location --silent --show-error "$base_url/$archive" -o "$temporary/$archive"
curl --fail --location --silent --show-error "$base_url/SHASUMS256.txt" -o "$temporary/SHASUMS256.txt"
(
  cd "$temporary"
  grep "  $archive\$" SHASUMS256.txt | sha256sum -c -
  tar -xJf "$archive"
)

new_runtime="$SERVICE_ROOT/.runtime-new-$$"
mkdir -p "$new_runtime"
mv "$temporary/node-v${NODE_VERSION}-linux-x64" "$new_runtime/node-v$NODE_VERSION"
mkdir -p "$new_runtime/global" "$new_runtime/bin"

export PATH="$new_runtime/node-v$NODE_VERSION/bin:$new_runtime/global/bin:$PATH"
echo "安装固定版本 HAPI ${HAPI_VERSION} 与 Claude Code ${CLAUDE_VERSION}..."
"$new_runtime/node-v$NODE_VERSION/bin/npm" install --global \
  --prefix "$new_runtime/global" \
  --registry=https://registry.npmjs.org \
  --no-audit --no-fund \
  "@twsxtd/hapi@$HAPI_VERSION" \
  "@anthropic-ai/claude-code@$CLAUDE_VERSION"

cat >"$new_runtime/bin/hapi" <<EOF
#!/usr/bin/env bash
export PATH="$RUNTIME_ROOT/node-v$NODE_VERSION/bin:$RUNTIME_ROOT/global/bin:\${PATH}"
exec "$RUNTIME_ROOT/global/bin/hapi" "\$@"
EOF
install -m 0755 "$SCRIPT_DIR/claude-deepseek-wrapper.sh" "$new_runtime/bin/claude"
chmod 0755 "$new_runtime/bin/hapi"

PATH="$new_runtime/node-v$NODE_VERSION/bin:$new_runtime/global/bin:$PATH" \
  "$new_runtime/global/bin/hapi" --version | grep -F "${HAPI_VERSION}" >/dev/null
PATH="$new_runtime/node-v$NODE_VERSION/bin:$new_runtime/global/bin:$PATH" \
  "$new_runtime/global/bin/claude" --version | grep -F "${CLAUDE_VERSION}" >/dev/null

if [[ -d "$RUNTIME_ROOT" ]]; then
  backup="$SERVICE_ROOT/runtime-backup-$(date +%Y%m%d-%H%M%S)"
  mv "$RUNTIME_ROOT" "$backup"
  echo "原运行时已备份到：$backup"
fi
mv "$new_runtime" "$RUNTIME_ROOT"
chmod -R a+rX,go-w "$RUNTIME_ROOT"

echo "HAPI_RUNTIME_INSTALL_OK"
"$BIN_HOME/hapi" --version
"$BIN_HOME/claude" --version
