#!/usr/bin/env bash
set -euo pipefail

SERVICE_ROOT="${HAPI_SERVICE_ROOT:-/data/kltst/homework/services/hapi}"
RUNTIME_ROOT="$SERVICE_ROOT/runtime"
HAPI_BIN="$RUNTIME_ROOT/bin/hapi"
CLAUDE_BIN="$RUNTIME_ROOT/bin/claude"
PREVIEW_ROOT="$SERVICE_ROOT/preview"
WORKSPACE="${HAPI_PREVIEW_WORKSPACE:-/data/kltst/hapi-preview-workspace}"
PORT="${HAPI_PREVIEW_PORT:-3066}"
ACCESS_FILE="$PREVIEW_ROOT/access.env"
HUB_PID_FILE="$PREVIEW_ROOT/hub.pid"
RUNNER_PID_FILE="$PREVIEW_ROOT/runner.pid"

[[ -x "$HAPI_BIN" && -x "$CLAUDE_BIN" ]] || {
  echo "HAPI 运行时不存在：$RUNTIME_ROOT" >&2
  exit 1
}
for command_name in curl openssl setsid ss; do
  command -v "$command_name" >/dev/null || { echo "缺少命令：$command_name" >&2; exit 1; }
done
[[ "$PORT" =~ ^[0-9]+$ ]] || { echo "端口必须是整数。" >&2; exit 1; }

umask 077
mkdir -p "$PREVIEW_ROOT/hub" "$PREVIEW_ROOT/runner" "$WORKSPACE"
chmod 0700 "$PREVIEW_ROOT" "$PREVIEW_ROOT/hub" "$PREVIEW_ROOT/runner"

if [[ ! -s "$ACCESS_FILE" ]]; then
  token="ehh_preview_$(openssl rand -hex 32)"
  {
    printf 'HAPI_HUB_URL=http://10.98.103.193:%s\n' "$PORT"
    printf 'HAPI_HUB_TOKEN=%s\n' "$token"
    printf 'HAPI_WORKSPACE=%s\n' "$WORKSPACE"
  } >"$ACCESS_FILE"
  chmod 0600 "$ACCESS_FILE"
fi

token=$(sed -n 's/^HAPI_HUB_TOKEN=//p' "$ACCESS_FILE")
[[ "$token" == ehh_preview_* ]] || { echo "预览 Token 文件格式错误。" >&2; exit 1; }

pid_alive() {
  local pid_file="$1" pid=""
  [[ -s "$pid_file" ]] || return 1
  pid=$(cat "$pid_file")
  [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null
}

if ! pid_alive "$HUB_PID_FILE"; then
  if ss -ltn 2>/dev/null | grep -qE ":${PORT}[[:space:]]"; then
    echo "预览端口已被其他进程占用：$PORT" >&2
    exit 1
  fi
  setsid nohup env HAPI_HOME="$PREVIEW_ROOT/hub" CLI_API_TOKEN="$token" \
    HAPI_LISTEN_HOST=0.0.0.0 HAPI_LISTEN_PORT="$PORT" \
    "$HAPI_BIN" hub --no-relay >"$PREVIEW_ROOT/hub.log" 2>&1 </dev/null &
  printf '%s\n' "$!" >"$HUB_PID_FILE"
fi

ready=0
for _ in $(seq 1 50); do
  if curl --silent --fail --max-time 2 "http://127.0.0.1:$PORT/" >/dev/null; then ready=1; break; fi
  sleep 0.4
done
[[ "$ready" -eq 1 ]] || {
  echo "预览 Hub 未能启动。" >&2
  tail -n 50 "$PREVIEW_ROOT/hub.log" >&2
  exit 1
}

if ! pid_alive "$RUNNER_PID_FILE"; then
  setsid nohup env HAPI_HOME="$PREVIEW_ROOT/runner" \
    HAPI_API_URL="http://127.0.0.1:$PORT" CLI_API_TOKEN="$token" \
    HAPI_CLAUDE_PATH="$CLAUDE_BIN" ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic \
    ANTHROPIC_AUTH_TOKEN=preview-disabled ANTHROPIC_MODEL='deepseek-v4-pro[1m]' \
    ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash CLAUDE_CODE_SUBAGENT_MODEL=deepseek-v4-flash \
    "$HAPI_BIN" runner start-sync --workspace-root "$WORKSPACE" >"$PREVIEW_ROOT/runner.log" 2>&1 </dev/null &
  printf '%s\n' "$!" >"$RUNNER_PID_FILE"
fi

echo "HAPI_PREVIEW_READY"
echo "预览地址：http://10.98.103.193:$PORT/"
echo "Token 文件：$ACCESS_FILE（权限 0600，未输出 Token）"
echo "预览工作区：$WORKSPACE（不读取学生目录）"
