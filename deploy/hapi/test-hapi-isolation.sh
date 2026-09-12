#!/usr/bin/env bash
set -euo pipefail

SERVICE_ROOT="${HAPI_SERVICE_ROOT:-/data/kltst/homework/services/hapi}"
HAPI_BIN="$SERVICE_ROOT/runtime/bin/hapi"
CLAUDE_BIN="$SERVICE_ROOT/runtime/bin/claude"
WORKSPACE="${HAPI_TEST_WORKSPACE:-/data/kltst/hapi-isolated-test}"
TEST_PORT="${HAPI_TEST_PORT:-3066}"
TEST_ROOT="$SERVICE_ROOT/isolated-tests"

[[ -x "$HAPI_BIN" ]] || { echo "HAPI 运行时尚未安装：$HAPI_BIN" >&2; exit 1; }
[[ -x "$CLAUDE_BIN" ]] || { echo "Claude CLI 尚未安装：$CLAUDE_BIN" >&2; exit 1; }
for command_name in curl openssl setsid ss; do
  command -v "$command_name" >/dev/null || { echo "缺少测试命令：$command_name" >&2; exit 1; }
done
[[ "$WORKSPACE" == /data/kltst/hapi-isolated-test ]] || {
  echo "拒绝使用非隔离测试目录：$WORKSPACE" >&2
  exit 1
}
if ss -ltn 2>/dev/null | grep -qE ":${TEST_PORT}[[:space:]]"; then
  echo "隔离测试端口已占用：$TEST_PORT" >&2
  exit 1
fi

mkdir -p "$WORKSPACE" "$TEST_ROOT"
test_run=$(mktemp -d "$TEST_ROOT/run.XXXXXX")
hub_home="$test_run/hub"
runner_home="$test_run/runner"
mkdir -m 0700 "$hub_home" "$runner_home"
token=$(openssl rand -hex 32)
hub_group=""
runner_group=""

stop_group() {
  local process_group="${1:-}"
  [[ "$process_group" =~ ^[0-9]+$ ]] || return 0
  kill -TERM -- "-$process_group" 2>/dev/null || true
  for _ in $(seq 1 20); do
    if ! kill -0 -- "-$process_group" 2>/dev/null; then
      return 0
    fi
    sleep 0.1
  done
  kill -KILL -- "-$process_group" 2>/dev/null || true
}

cleanup() {
  stop_group "$runner_group"
  stop_group "$hub_group"
  case "$test_run" in
    "$TEST_ROOT"/run.*) rm -rf -- "$test_run" ;;
    *) echo "拒绝清理异常测试目录：$test_run" >&2 ;;
  esac
}
trap cleanup EXIT

setsid env HAPI_HOME="$hub_home" \
  CLI_API_TOKEN="$token" \
  HAPI_LISTEN_HOST=127.0.0.1 \
  HAPI_LISTEN_PORT="$TEST_PORT" \
  "$HAPI_BIN" hub --no-relay >"$test_run/hub.log" 2>&1 &
hub_group=$!

hub_ready=0
for _ in $(seq 1 40); do
  if curl --silent --fail --max-time 2 "http://127.0.0.1:$TEST_PORT/" >/dev/null; then
    hub_ready=1
    break
  fi
  sleep 0.5
done
[[ "$hub_ready" -eq 1 ]] || {
  echo "临时 HAPI Hub 未能启动。" >&2
  tail -n 40 "$test_run/hub.log" >&2
  exit 1
}

setsid env HAPI_HOME="$runner_home" \
  HAPI_API_URL="http://127.0.0.1:$TEST_PORT" \
  CLI_API_TOKEN="$token" \
  HAPI_CLAUDE_PATH="$CLAUDE_BIN" \
  ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic" \
  ANTHROPIC_AUTH_TOKEN="isolation-test-placeholder" \
  ANTHROPIC_MODEL="deepseek-v4-pro[1m]" \
  ANTHROPIC_DEFAULT_OPUS_MODEL="deepseek-v4-pro[1m]" \
  ANTHROPIC_DEFAULT_SONNET_MODEL="deepseek-v4-pro[1m]" \
  ANTHROPIC_DEFAULT_HAIKU_MODEL="deepseek-v4-flash" \
  CLAUDE_CODE_SUBAGENT_MODEL="deepseek-v4-flash" \
  "$HAPI_BIN" runner start-sync --workspace-root "$WORKSPACE" >"$test_run/runner.log" 2>&1 &
runner_group=$!

state_file="$runner_home/runner.state.json"
runner_ready=0
for _ in $(seq 1 60); do
  if [[ -s "$state_file" ]] && grep -Eq 'Workspace roots .*hub' "$test_run/runner.log"; then
    runner_ready=1
    break
  fi
  sleep 0.5
done
[[ "$runner_ready" -eq 1 ]] || {
  echo "临时 Runner 未向隔离 Hub 完成注册。" >&2
  tail -n 60 "$test_run/runner.log" >&2
  exit 1
}

/usr/bin/python3 - "$state_file" "$WORKSPACE" "$TEST_PORT" <<'PY'
import json
import pathlib
import sys

state = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
workspace = sys.argv[2]
port = sys.argv[3]
argv = state.get("startedWithArgv") or []
assert state.get("startedWithApiUrl") == f"http://127.0.0.1:{port}", state
assert "--workspace-root" in argv, argv
assert workspace in argv, argv
for forbidden in ("/data/student01", "/data/student02", "/data/student04", "/data/student05", "/data/michaelk"):
    assert forbidden not in argv, argv
print("HAPI_SCOPE_ASSERTIONS_OK")

runner_pid = int(state["pid"])
environment = pathlib.Path(f"/proc/{runner_pid}/environ").read_bytes().split(b"\0")
values = {}
for entry in environment:
    if b"=" in entry:
        key, value = entry.split(b"=", 1)
        values[key.decode("utf-8", "replace")] = value.decode("utf-8", "replace")
assert values.get("ANTHROPIC_BASE_URL") == "https://api.deepseek.com/anthropic"
assert values.get("ANTHROPIC_MODEL") == "deepseek-v4-pro[1m]"
assert values.get("ANTHROPIC_DEFAULT_HAIKU_MODEL") == "deepseek-v4-flash"
assert values.get("CLAUDE_CODE_SUBAGENT_MODEL") == "deepseek-v4-flash"
assert values.get("ANTHROPIC_AUTH_TOKEN") == "isolation-test-placeholder"
for forbidden_key in ("OPENAI_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY"):
    assert not values.get(forbidden_key), forbidden_key
print("DEEPSEEK_ONLY_ENV_OK")
PY

[[ "$(stat -c %U "$WORKSPACE")" == "kltst" ]] || {
  echo "隔离工作区所有者不是 kltst。" >&2
  exit 1
}

echo "HAPI_ISOLATION_TEST_OK"
echo "临时 Hub：127.0.0.1:$TEST_PORT（仅回环地址，测试结束即停止）"
echo "允许工作区：$WORKSPACE"
