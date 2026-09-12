#!/usr/bin/env bash
# 批量创建学生 Linux 账号：degree00-20（学位+）、graduated00-25（生信·研）。
# 每个账号随机密码，凭据只写入服务器上的 600 权限 CSV，不打印到终端。
# 用法：sudo bash deploy/batch-create-students.sh
set -euo pipefail

[[ "${EUID:-$(id -u)}" -eq 0 ]] || { echo "请使用 sudo 执行此脚本" >&2; exit 1; }

CRED_DIR="/data/kltst/homework/credentials"
CRED_FILE="$CRED_DIR/student-accounts-$(date +%Y%m%dT%H%M%S).csv"
install -d -m 0700 -o kltst -g kltst "$CRED_DIR"
install -m 0600 -o kltst -g kltst /dev/null "$CRED_FILE"
echo "username,password" >>"$CRED_FILE"

create_user() {
  local username="$1"
  if getent passwd "$username" >/dev/null; then
    echo "SKIP_EXISTS $username"
    return 0
  fi
  local password
  password="$(openssl rand -hex 8)"
  useradd -m -s /bin/bash "$username"
  echo "${username}:${password}" | chpasswd
  install -d -m 0700 -o "$username" -g "$username" "/data/$username"
  echo "${username},${password}" >>"$CRED_FILE"
  echo "CREATED $username"
}

for i in $(seq -w 0 20); do create_user "degree$i"; done
for i in $(seq -w 0 25); do create_user "graduated$i"; done

chmod 0600 "$CRED_FILE"
chown kltst:kltst "$CRED_FILE"
echo "DONE 凭据文件：$CRED_FILE （仅 kltst 可读，分发后建议学生自行改密）"
