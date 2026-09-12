#!/usr/bin/env bash
set -euo pipefail

SERVICE_ROOT="${DEEPSEEK_HAPI_SERVICE_ROOT:-/data/kltst/homework/services/deepseek-hapi}"
PID_FILE="$SERVICE_ROOT/server.pid"
if [[ -s "$PID_FILE" ]]; then
  pid=$(cat "$PID_FILE")
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    kill -TERM "$pid"
    for _ in $(seq 1 30); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.2
    done
  fi
  : >"$PID_FILE"
fi
echo "DEEPSEEK_HAPI_STOPPED"
