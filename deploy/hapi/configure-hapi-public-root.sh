#!/usr/bin/env bash
set -euo pipefail

ENV_DIR=/etc/eduflow-hapi
APP_ENV=/data/kltst/homework/app/.env
BACKUP_ROOT=/var/backups/eduflow-hapi-public
DOMAIN_SUFFIX="${HAPI_PUBLIC_DOMAIN_SUFFIX:-47.96.100.122.nip.io}"

usage() {
  echo "用法：sudo bash $0 kltst michaelk student01 student02 student04 student05" >&2
}

if [[ "$EUID" -ne 0 ]]; then
  echo "请在自己的终端使用 sudo 执行本脚本；不要把密码发送到聊天。" >&2
  exit 1
fi
if [[ "$#" -lt 1 ]]; then
  usage
  exit 1
fi
[[ "$DOMAIN_SUFFIX" =~ ^[A-Za-z0-9.-]+$ ]] || {
  echo "HAPI_PUBLIC_DOMAIN_SUFFIX 格式不正确。" >&2
  exit 1
}
[[ -s "$APP_ENV" ]] || { echo "缺少应用环境文件：$APP_ENV" >&2; exit 1; }

backup_dir="$BACKUP_ROOT/$(date +%Y%m%d-%H%M%S)"
install -d -m 0700 -o root -g root "$backup_dir"
cp -a "$APP_ENV" "$backup_dir/app.env"
printf '%s\n' "$@" >"$backup_dir/users.txt"
chmod 0600 "$backup_dir/users.txt"

update_env() {
  local file="$1" key="$2" value="$3"
  local owner group mode tmp
  owner=$(stat -c %U "$file")
  group=$(stat -c %G "$file")
  mode=$(stat -c %a "$file")
  tmp=$(mktemp)
  chmod 0600 "$tmp"
  awk -v key="$key" -v replacement="$key=$value" '
    BEGIN { replaced = 0 }
    index($0, key "=") == 1 {
      if (!replaced) print replacement
      replaced = 1
      next
    }
    { print }
    END { if (!replaced) print replacement }
  ' "$file" >"$tmp"
  install -m "$mode" -o "$owner" -g "$group" "$tmp" "$file"
  rm -f "$tmp"
}

update_env "$APP_ENV" DEEPSEEK_3066_MENU_ENABLED 0
update_env "$APP_ENV" HAPI_PUBLIC_URL_TEMPLATE "https://hapi-{username}.$DOMAIN_SUFFIX/"

for username in "$@"; do
  [[ "$username" =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo "异常用户名：$username" >&2; exit 1; }
  getent passwd "$username" >/dev/null || { echo "Linux 用户不存在：$username" >&2; exit 1; }
  home_dir=$(getent passwd "$username" | cut -d: -f6)
  env_file="$ENV_DIR/$username.env"
  access_file="$home_dir/.config/eduflow-hapi/access.env"
  [[ -s "$env_file" ]] || { echo "缺少 $env_file" >&2; exit 1; }
  [[ -s "$access_file" ]] || { echo "缺少 $access_file" >&2; exit 1; }
  cp -a "$env_file" "$backup_dir/$username.env"
  cp -a "$access_file" "$backup_dir/$username.access.env"

  public_origin="https://hapi-$username.$DOMAIN_SUFFIX"
  update_env "$env_file" HAPI_PUBLIC_URL "$public_origin/"
  update_env "$env_file" CORS_ORIGINS "$public_origin"
  update_env "$access_file" HAPI_HUB_URL "$public_origin/"
done

for username in "$@"; do
  systemctl restart "eduflow-hapi-hub@$username.service"
done
systemctl restart homework.service

failed=0
for username in "$@"; do
  uid_number=$(id -u "$username")
  port=$((32000 + uid_number - 1000))
  ready=0
  for _ in $(seq 1 40); do
    if systemctl is-active --quiet "eduflow-hapi-hub@$username.service" \
      && curl --silent --fail --max-time 2 "http://127.0.0.1:$port/" >/dev/null; then
      ready=1
      break
    fi
    sleep 0.5
  done
  if [[ "$ready" -eq 1 ]]; then
    echo "READY $username https://hapi-$username.$DOMAIN_SUFFIX/"
  else
    echo "FAIL $username" >&2
    failed=1
  fi
done
systemctl is-active --quiet homework.service || {
  echo "FAIL homework.service" >&2
  failed=1
}

echo "配置备份：$backup_dir"
[[ "$failed" -eq 0 ]] || exit 1
echo "HAPI_PUBLIC_CONFIG_OK"
