#!/usr/bin/env bash
set -euo pipefail

APP_ENV=/data/kltst/homework/app/.env

if [[ "$EUID" -ne 0 ]]; then
  echo "请在自己的终端使用 sudo 执行本脚本；不要把密码发送到聊天。" >&2
  exit 1
fi
if [[ "$#" -ne 1 || ! -d "$1" ]]; then
  echo "用法：sudo bash $0 /var/backups/eduflow-hapi-public/<时间戳>" >&2
  exit 1
fi

backup_dir=$(readlink -f "$1")
case "$backup_dir" in
  /var/backups/eduflow-hapi-public/*) ;;
  *) echo "拒绝使用备份目录之外的路径。" >&2; exit 1 ;;
esac
[[ -s "$backup_dir/app.env" && -s "$backup_dir/users.txt" ]] || {
  echo "备份不完整：$backup_dir" >&2
  exit 1
}

cp -a "$backup_dir/app.env" "$APP_ENV"
mapfile -t users <"$backup_dir/users.txt"
for username in "${users[@]}"; do
  [[ "$username" =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo "备份用户名异常。" >&2; exit 1; }
  home_dir=$(getent passwd "$username" | cut -d: -f6)
  cp -a "$backup_dir/$username.env" "/etc/eduflow-hapi/$username.env"
  cp -a "$backup_dir/$username.access.env" "$home_dir/.config/eduflow-hapi/access.env"
  systemctl restart "eduflow-hapi-hub@$username.service"
done
systemctl restart homework.service
echo "HAPI_PUBLIC_CONFIG_ROLLBACK_OK $backup_dir"
