#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "请使用 root 执行本脚本。" >&2
  exit 1
fi

APP_USER="${APP_USER:-eduflow}"
APP_ROOT="${APP_ROOT:-/opt/eduflow}"

apt-get update
apt-get install -y sudo python3 python3-venv python3-pip nginx git
if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --create-home --shell /bin/bash "$APP_USER"
fi
mkdir -p "$APP_ROOT/app" "$APP_ROOT/data/uploads" "$APP_ROOT/backup"
chown -R "$APP_USER:$APP_USER" "$APP_ROOT"
groupadd -f teacher
groupadd -f assistant
usermod -aG shadow "$APP_USER"

echo "主机初始化完成。请重新登录 $APP_USER，使 shadow 组权限生效。"
