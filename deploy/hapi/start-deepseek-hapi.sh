#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${EDUFLOW_APP_ROOT:-/data/kltst/homework/app}"
SERVICE_ROOT="${DEEPSEEK_HAPI_SERVICE_ROOT:-/data/kltst/homework/services/deepseek-hapi}"
PORT="${DEEPSEEK_HAPI_PORT:-3066}"
PID_FILE="$SERVICE_ROOT/server.pid"
LOG_FILE="$SERVICE_ROOT/server.log"
GUNICORN="$APP_ROOT/venv/bin/gunicorn"

[[ -x "$GUNICORN" ]] || { echo "Gunicorn 不存在：$GUNICORN" >&2; exit 1; }
[[ -f "$APP_ROOT/subsystems/deepseek_hapi/app.py" ]] || { echo "DeepSeek 工作台代码不存在。" >&2; exit 1; }
[[ "$PORT" =~ ^[0-9]+$ ]] || { echo "端口必须为整数。" >&2; exit 1; }

mkdir -p "$SERVICE_ROOT"
chmod 0700 "$SERVICE_ROOT"

if [[ -s "$PID_FILE" ]]; then
  pid=$(cat "$PID_FILE")
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    echo "DEEPSEEK_HAPI_READY"
    echo "地址：http://10.98.103.193:$PORT/"
    exit 0
  fi
fi
if ss -ltn 2>/dev/null | grep -qE ":${PORT}[[:space:]]"; then
  echo "端口已被其他服务占用：$PORT" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source "$APP_ROOT/.env"
set +a
export DEEPSEEK_HAPI_PORT="$PORT"
export DEEPSEEK_HAPI_DATABASE="$SERVICE_ROOT/workbench.db"
export PYTHONPATH="$APP_ROOT"

setsid nohup "$GUNICORN" --chdir "$APP_ROOT" --workers 2 --bind "0.0.0.0:$PORT" \
  --access-logfile - --error-logfile - subsystems.deepseek_hapi.app:app \
  >"$LOG_FILE" 2>&1 </dev/null &
printf '%s\n' "$!" >"$PID_FILE"

ready=0
for _ in $(seq 1 50); do
  if curl --silent --output /dev/null --max-time 2 --write-out '%{http_code}' "http://127.0.0.1:$PORT/" | grep -qE '^(200|302)$'; then
    ready=1
    break
  fi
  sleep 0.4
done
if [[ "$ready" -ne 1 ]]; then
  echo "DeepSeek 工作台启动失败。" >&2
  tail -n 60 "$LOG_FILE" >&2
  exit 1
fi
echo "DEEPSEEK_HAPI_READY"
echo "地址：http://10.98.103.193:$PORT/"
echo "模式：DeepSeek API 直连（无代理选择）"
