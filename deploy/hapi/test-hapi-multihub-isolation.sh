#!/usr/bin/env bash
set -euo pipefail

SERVICE_ROOT="${HAPI_SERVICE_ROOT:-/data/kltst/homework/services/hapi}"
HAPI_BIN="$SERVICE_ROOT/runtime/bin/hapi"
CLAUDE_BIN="$SERVICE_ROOT/runtime/bin/claude"
WORKSPACE_ROOT="${HAPI_TEST_WORKSPACE_ROOT:-/data/kltst/hapi-multihub-test}"
TEST_ROOT="$SERVICE_ROOT/isolated-tests"
PORT_A="${HAPI_TEST_PORT_A:-3066}"
PORT_B="${HAPI_TEST_PORT_B:-3067}"

[[ -x "$HAPI_BIN" && -x "$CLAUDE_BIN" ]] || {
  echo "HAPI/Claude 运行时尚未安装。" >&2
  exit 1
}
[[ "$WORKSPACE_ROOT" == /data/kltst/hapi-multihub-test ]] || {
  echo "拒绝使用非隔离测试目录：$WORKSPACE_ROOT" >&2
  exit 1
}
for command_name in curl openssl setsid ss python3; do
  command -v "$command_name" >/dev/null || { echo "缺少测试命令：$command_name" >&2; exit 1; }
done
for port in "$PORT_A" "$PORT_B"; do
  [[ "$port" =~ ^[0-9]+$ ]] || { echo "测试端口不是整数：$port" >&2; exit 1; }
  if ss -ltn 2>/dev/null | grep -qE ":${port}[[:space:]]"; then
    echo "隔离测试端口已占用：$port" >&2
    exit 1
  fi
done

mkdir -p "$WORKSPACE_ROOT/student-a" "$WORKSPACE_ROOT/student-b" "$TEST_ROOT"
test_run=$(mktemp -d "$TEST_ROOT/multihub.XXXXXX")
token_a="ehh_test_$(openssl rand -hex 24)"
token_b="ehh_test_$(openssl rand -hex 24)"
[[ "$token_a" != "$token_b" ]] || { echo "两个测试 Token 不应相同。" >&2; exit 1; }

hub_a_group=""
hub_b_group=""
runner_a_group=""
runner_b_group=""

stop_group() {
  local process_group="${1:-}"
  [[ "$process_group" =~ ^[0-9]+$ ]] || return 0
  kill -TERM -- "-$process_group" 2>/dev/null || true
  for _ in $(seq 1 20); do
    if ! kill -0 -- "-$process_group" 2>/dev/null; then return 0; fi
    sleep 0.1
  done
  kill -KILL -- "-$process_group" 2>/dev/null || true
}

cleanup() {
  stop_group "$runner_a_group"
  stop_group "$runner_b_group"
  stop_group "$hub_a_group"
  stop_group "$hub_b_group"
  case "$test_run" in
    "$TEST_ROOT"/multihub.*) rm -rf -- "$test_run" ;;
    *) echo "拒绝清理异常测试目录：$test_run" >&2 ;;
  esac
}
trap cleanup EXIT

start_hub() {
  local name="$1" port="$2" token="$3"
  local home="$test_run/hub-$name"
  mkdir -m 0700 "$home"
  setsid env HAPI_HOME="$home" CLI_API_TOKEN="$token" \
    HAPI_LISTEN_HOST=127.0.0.1 HAPI_LISTEN_PORT="$port" \
    "$HAPI_BIN" hub --no-relay >"$test_run/hub-$name.log" 2>&1 &
  printf '%s' "$!"
}

hub_a_group=$(start_hub a "$PORT_A" "$token_a")
hub_b_group=$(start_hub b "$PORT_B" "$token_b")

for spec in "a:$PORT_A" "b:$PORT_B"; do
  name=${spec%%:*}
  port=${spec##*:}
  ready=0
  for _ in $(seq 1 50); do
    if curl --silent --fail --max-time 2 "http://127.0.0.1:$port/" >/dev/null; then ready=1; break; fi
    sleep 0.4
  done
  [[ "$ready" -eq 1 ]] || {
    echo "临时 Hub $name 未能启动。" >&2
    tail -n 50 "$test_run/hub-$name.log" >&2
    exit 1
  }
done

start_runner() {
  local name="$1" port="$2" token="$3" workspace="$4"
  local home="$test_run/runner-$name"
  mkdir -m 0700 "$home"
  setsid env HAPI_HOME="$home" HAPI_API_URL="http://127.0.0.1:$port" \
    CLI_API_TOKEN="$token" HAPI_CLAUDE_PATH="$CLAUDE_BIN" \
    ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic \
    ANTHROPIC_AUTH_TOKEN=isolation-test-placeholder \
    'ANTHROPIC_MODEL=deepseek-v4-pro[1m]' \
    'ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro[1m]' \
    'ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro[1m]' \
    ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash \
    CLAUDE_CODE_SUBAGENT_MODEL=deepseek-v4-flash \
    "$HAPI_BIN" runner start-sync --workspace-root "$workspace" >"$test_run/runner-$name.log" 2>&1 &
  printf '%s' "$!"
}

runner_a_group=$(start_runner a "$PORT_A" "$token_a" "$WORKSPACE_ROOT/student-a")
runner_b_group=$(start_runner b "$PORT_B" "$token_b" "$WORKSPACE_ROOT/student-b")

for name in a b; do
  ready=0
  for _ in $(seq 1 70); do
    if [[ -s "$test_run/runner-$name/runner.state.json" ]] && \
       grep -Eq 'Workspace roots .*hub' "$test_run/runner-$name.log"; then
      ready=1
      break
    fi
    sleep 0.4
  done
  [[ "$ready" -eq 1 ]] || {
    echo "临时 Runner $name 未完成注册。" >&2
    tail -n 60 "$test_run/runner-$name.log" >&2
    exit 1
  }
done

python3 - "$test_run" "$WORKSPACE_ROOT" "$PORT_A" "$PORT_B" "$token_a" "$token_b" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
workspace_root = pathlib.Path(sys.argv[2])
ports = {"a": sys.argv[3], "b": sys.argv[4]}
tokens = {"a": sys.argv[5], "b": sys.argv[6]}
assert tokens["a"] != tokens["b"]

for name, other in (("a", "b"), ("b", "a")):
    state = json.loads((root / f"runner-{name}" / "runner.state.json").read_text(encoding="utf-8"))
    own_workspace = str(workspace_root / f"student-{name}")
    other_workspace = str(workspace_root / f"student-{other}")
    argv = state.get("startedWithArgv") or []
    assert state.get("startedWithApiUrl") == f"http://127.0.0.1:{ports[name]}", state
    assert own_workspace in argv, argv
    assert other_workspace not in argv, argv

    pid = int(state["pid"])
    entries = pathlib.Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    env = dict(e.decode("utf-8", "replace").split("=", 1) for e in entries if b"=" in e)
    assert env.get("CLI_API_TOKEN") == tokens[name]
    assert env.get("CLI_API_TOKEN") != tokens[other]
    assert env.get("ANTHROPIC_BASE_URL") == "https://api.deepseek.com/anthropic"
    assert env.get("ANTHROPIC_MODEL") == "deepseek-v4-pro[1m]"
    assert env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL") == "deepseek-v4-flash"
    assert env.get("ANTHROPIC_AUTH_TOKEN") == "isolation-test-placeholder"
    for forbidden in ("OPENAI_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY"):
        assert not env.get(forbidden), forbidden

assert (root / "hub-a").resolve() != (root / "hub-b").resolve()
assert any((root / "hub-a").rglob("*")), "Hub A did not create isolated state"
assert any((root / "hub-b").rglob("*")), "Hub B did not create isolated state"
print("HAPI_TWO_HUB_TOKEN_AND_SCOPE_ASSERTIONS_OK")
print("DEEPSEEK_ONLY_ENV_OK")
PY

echo "HAPI_MULTIHUB_ISOLATION_TEST_OK"
echo "Hub A: 127.0.0.1:$PORT_A -> $WORKSPACE_ROOT/student-a"
echo "Hub B: 127.0.0.1:$PORT_B -> $WORKSPACE_ROOT/student-b"
