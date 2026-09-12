#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/eduflow}"
APP_DIR="${APP_DIR:-$APP_ROOT/app}"
DATA_DIR="${DATA_DIR:-$APP_ROOT/data}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$SCRIPT_DIR" != "$APP_DIR" ]]; then
  echo "请先把代码同步到 $APP_DIR，再在该目录运行 deploy.sh。" >&2
  exit 1
fi

mkdir -p "$DATA_DIR/uploads" "$DATA_DIR/server-files" "$APP_ROOT/backup"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [[ ! -f "$APP_DIR/.env" ]]; then
  SECRET_VALUE="$($APP_DIR/venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
  umask 077
  printf 'SECRET_KEY=%s\nCOURSE_NAME=学位+\nCOURSE_SUBTITLE=193 内网服务器\nCOURSE_BADGE=CS\nCOURSE_ONLY_SLUG=degree\nDEGREE_USERS=\nBIOINFORMATICS_USERS=\nBIOINFORMATICS_ASSISTANTS=\nBIO_UNDERGRAD_USERS=\nBIO_UNDERGRAD_ASSISTANTS=\nDATABASE=%s\nUPLOAD_FOLDER=%s\nSERVER_SUBMISSION_ROOT=%s\nTEACHERS=%s\nASSISTANTS=\nALLOWED_USERS=%s\nTEACHER_GROUP=teacher\nASSISTANT_GROUP=assistant\nDEEPSEEK_API_KEY=\nDEEPSEEK_BASE_URL=https://api.deepseek.com\nDEEPSEEK_CHAT_MODEL=deepseek-v4-flash\nDEEPSEEK_REASONING_MODEL=deepseek-v4-pro\nDEEPSEEK_3066_MENU_ENABLED=0\nHAPI_SERVER_HOST=10.98.103.193\nHAPI_PORT_BASE=32000\nHAPI_PUBLIC_URL_TEMPLATE=\nSESSION_COOKIE_SECURE=0\nSESSION_COOKIE_NAME=eduflow_degree_session\nREMEMBER_COOKIE_NAME=eduflow_degree_remember\nLOGIN_HINT_COOKIE_PREFIX=degree_\nSEED_DEMO_DATA=0\n' \
    "$SECRET_VALUE" "$DATA_DIR/app.db" "$DATA_DIR/uploads" "$DATA_DIR/server-files" "teacher01" "teacher01" > "$APP_DIR/.env"
fi

set -a
source "$APP_DIR/.env"
set +a
"$APP_DIR/venv/bin/flask" --app app init-db

if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
  sudo install -m 0644 "$APP_DIR/deploy/homework.service" /etc/systemd/system/homework.service
  sudo install -m 0644 "$APP_DIR/deploy/nginx-homework.conf" /etc/nginx/sites-available/homework
  sudo ln -sfn /etc/nginx/sites-available/homework /etc/nginx/sites-enabled/homework
  sudo systemctl daemon-reload
  sudo systemctl enable --now homework
  sudo nginx -t
  sudo systemctl reload nginx
  echo "部署完成：http://$(hostname -I | awk '{print $1}')/"
else
  mkdir -p "$HOME/.config/systemd/user"
  cp "$APP_DIR/deploy/homework-user.service" "$HOME/.config/systemd/user/homework.service"
  systemctl --user daemon-reload
  systemctl --user enable --now homework
  echo "无免密 sudo，已启动用户级服务：http://$(hostname -I | awk '{print $1}'):8000/"
  echo "要启用 80 端口和完整 PAM 多用户认证，请管理员执行 README 中的主机初始化步骤。"
fi
