#!/usr/bin/env bash
# EduFlow native-DeepSeek HAPI test instance setup (runs as kltst, no sudo).
set -euo pipefail

SERVICE_ROOT=/data/kltst/homework/services/hapi
NATIVE_DIR="$SERVICE_ROOT/native"
SRC_BIN="$SERVICE_ROOT/source-v0.20.2/cli/dist-exe/bun-linux-x64-baseline/hapi"
VERSION_TAG="${HAPI_NATIVE_VERSION_TAG:-0.20.2-ds-20260826}"
TEST_ROOT="$SERVICE_ROOT/test-instance"
WORKSPACE=/data/kltst/hapi-ds-test
PORT=32099
APP_ENV=/data/kltst/homework/app/.env

[[ -x "$SRC_BIN" ]] || { echo "构建产物不存在：$SRC_BIN" >&2; exit 1; }
[[ -f "$APP_ENV" ]] || { echo "EduFlow .env 不存在。" >&2; exit 1; }

umask 077
mkdir -p "$NATIVE_DIR" "$TEST_ROOT/hub" "$TEST_ROOT/runner" "$WORKSPACE"
# The native binary is shared by per-user systemd services. Keep only the
# test state private; every HAPI account must be able to traverse this path.
chmod 0755 "$NATIVE_DIR"

# 版本化安装新二进制（保留旧副本用于回滚）
install -m 0755 "$SRC_BIN" "$NATIVE_DIR/hapi-$VERSION_TAG"
ln -sfn "hapi-$VERSION_TAG" "$NATIVE_DIR/hapi"
"$NATIVE_DIR/hapi" --version

# 测试 Token（只写入 0600 文件，不输出）
if [[ ! -s "$TEST_ROOT/access.env" ]]; then
  token="ehh_test_$(openssl rand -hex 32)"
  {
    printf 'HAPI_HUB_URL=http://10.98.103.193:%s\n' "$PORT"
    printf 'HAPI_HUB_TOKEN=%s\n' "$token"
    printf 'HAPI_WORKSPACE=%s\n' "$WORKSPACE"
  } >"$TEST_ROOT/access.env"
  chmod 0600 "$TEST_ROOT/access.env"
fi
token=$(sed -n 's/^HAPI_HUB_TOKEN=//p' "$TEST_ROOT/access.env")

pid_alive() {
  local pid_file="$1" pid=""
  [[ -s "$pid_file" ]] || return 1
  pid=$(cat "$pid_file")
  [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null
}

if ! pid_alive "$TEST_ROOT/hub.pid"; then
  if ss -ltn 2>/dev/null | grep -qE ":${PORT}[[:space:]]"; then
    echo "测试端口已被占用：$PORT" >&2; exit 1
  fi
  setsid nohup env HAPI_HOME="$TEST_ROOT/hub" CLI_API_TOKEN="$token" \
    HAPI_LISTEN_HOST=0.0.0.0 HAPI_LISTEN_PORT="$PORT" \
    "$NATIVE_DIR/hapi" hub --no-relay >"$TEST_ROOT/hub.log" 2>&1 </dev/null &
  printf '%s\n' "$!" >"$TEST_ROOT/hub.pid"
fi

ready=0
for _ in $(seq 1 50); do
  if curl --silent --fail --max-time 2 "http://127.0.0.1:$PORT/" >/dev/null; then ready=1; break; fi
  sleep 0.4
done
[[ "$ready" -eq 1 ]] || { echo "测试 Hub 启动失败。" >&2; tail -n 50 "$TEST_ROOT/hub.log" >&2; exit 1; }

if ! pid_alive "$TEST_ROOT/runner.pid"; then
  # DEEPSEEK_API_KEY 仅从环境变量注入 Runner 进程，不写入任何文件、不打印
  set -a; source "$APP_ENV"; set +a
  [[ -n "${DEEPSEEK_API_KEY:-}" ]] || { echo "环境缺少 DEEPSEEK_API_KEY。" >&2; exit 1; }
  setsid nohup env HAPI_HOME="$TEST_ROOT/runner" \
    HAPI_API_URL="http://127.0.0.1:$PORT" CLI_API_TOKEN="$token" \
    DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
    PATH="$NATIVE_DIR:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    "$NATIVE_DIR/hapi" runner start-sync --workspace-root "$WORKSPACE" \
    >"$TEST_ROOT/runner.log" 2>&1 </dev/null &
  printf '%s\n' "$!" >"$TEST_ROOT/runner.pid"
  unset DEEPSEEK_API_KEY
fi
sleep 2
pid_alive "$TEST_ROOT/runner.pid" || { echo "Runner 启动失败。" >&2; tail -n 50 "$TEST_ROOT/runner.log" >&2; exit 1; }

echo "HAPI_TEST_INSTANCE_READY"
echo "测试地址：http://10.98.103.193:$PORT/"
echo "Token 文件：$TEST_ROOT/access.env（0600，未输出）"
echo "测试工作区：$WORKSPACE"
