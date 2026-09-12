#!/usr/bin/env bash
# 创建单个 PAM 学生账号；随机初始密码仅保存到服务器 0600 文件，不输出到终端。
# 用法：sudo bash deploy/create-student-account.sh test_s2
set -euo pipefail

[[ "${EUID:-$(id -u)}" -eq 0 ]] || { echo "请使用 sudo 执行此脚本" >&2; exit 1; }
[[ "$#" -eq 1 ]] || { echo "用法：sudo bash $0 <用户名>" >&2; exit 2; }

username="$1"
[[ "$username" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || { echo "用户名格式不合法" >&2; exit 2; }
if getent passwd "$username" >/dev/null; then
  echo "账号已存在，未修改密码：$username"
  exit 0
fi
[[ ! -e "/data/$username" ]] || {
  echo "检测到同名数据目录 /data/$username；为避免覆盖或删除既有数据，已停止。" >&2
  exit 3
}

owner="${SUDO_USER:-root}"
group="$(id -gn "$owner")"
cred_dir="/data/kltst/homework/credentials"
cred_file="$cred_dir/${username}-account-$(date +%Y%m%dT%H%M%S).csv"
password="$(openssl rand -hex 8)"
account_created=0
success=0

cleanup() {
  local status=$?
  unset password
  if [[ "$success" -ne 1 ]]; then
    rm -f -- "$cred_file"
    if [[ "$account_created" -eq 1 ]]; then
      userdel -r "$username" >/dev/null 2>&1 || true
      rm -rf -- "/data/$username"
    fi
  fi
  exit "$status"
}
trap cleanup EXIT

install -d -m 0700 -o "$owner" -g "$group" "$cred_dir"
useradd -m -s /bin/bash "$username"
account_created=1
printf '%s:%s\n' "$username" "$password" | chpasswd
student_group="$(id -gn "$username")"
install -d -m 0700 -o "$username" -g "$student_group" "/data/$username"
install -m 0600 -o "$owner" -g "$group" /dev/null "$cred_file"
printf 'username,password\n%s,%s\n' "$username" "$password" >"$cred_file"
chown "$owner:$group" "$cred_file"
chmod 0600 "$cred_file"
success=1
unset password
trap - EXIT

echo "CREATED $username"
echo "凭据文件：$cred_file（仅 $owner 可读；请安全分发并要求首次使用后修改）"
