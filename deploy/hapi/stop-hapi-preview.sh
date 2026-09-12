#!/usr/bin/env bash
set -euo pipefail

PREVIEW_ROOT="${HAPI_SERVICE_ROOT:-/data/kltst/homework/services/hapi}/preview"

stop_group_from_file() {
  local pid_file="$1" pid=""
  [[ -s "$pid_file" ]] || return 0
  pid=$(cat "$pid_file")
  if [[ "$pid" =~ ^[0-9]+$ ]]; then
    kill -TERM -- "-$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
      if ! kill -0 -- "-$pid" 2>/dev/null; then break; fi
      sleep 0.1
    done
    kill -KILL -- "-$pid" 2>/dev/null || true
  fi
  rm -f -- "$pid_file"
}

stop_group_from_file "$PREVIEW_ROOT/runner.pid"
stop_group_from_file "$PREVIEW_ROOT/hub.pid"
echo "HAPI_PREVIEW_STOPPED"
