#!/usr/bin/env bash
set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
  echo "请由 root 使用 sudo 执行。" >&2
  exit 1
fi
if [[ "$#" -lt 1 ]]; then
  echo "用法：sudo $0 student01 [student02 ...]" >&2
  exit 1
fi

READ_GROUP="${PROJECT_READ_GROUP:-eduflow-staff-read}"
ROLE_GROUPS="${PROJECT_READER_ROLE_GROUPS:-teacher assistant}"
getent group "$READ_GROUP" >/dev/null 2>&1 || groupadd "$READ_GROUP"

# Copy current teacher/assistant membership into a filesystem-only read group.
# This deliberately does not add assistants to teacher, which would expose
# teacher-group HAPI credentials and couple filesystem access to app roles.
declare -A readers=()
for role_group in $ROLE_GROUPS; do
  group_line=$(getent group "$role_group") || {
    echo "角色组不存在：$role_group" >&2
    exit 1
  }
  IFS=: read -r _ _ role_gid member_csv <<< "$group_line"
  IFS=, read -r -a members <<< "$member_csv"
  for member in "${members[@]}"; do
    [[ -n "$member" ]] && readers["$member"]=1
  done
  while IFS=: read -r username _ _ primary_gid _; do
    [[ "$primary_gid" == "$role_gid" ]] && readers["$username"]=1
  done < <(getent passwd)
done

for reader in "${!readers[@]}"; do
  usermod -aG "$READ_GROUP" "$reader"
  echo "已授权项目只读：$reader"
done

for username in "$@"; do
  if ! getent passwd "$username" >/dev/null; then
    echo "跳过不存在的 Linux 用户：$username" >&2
    continue
  fi
  workspace="/data/$username"
  if [[ ! -d "$workspace" ]]; then
    echo "跳过不存在的工作区：$workspace" >&2
    continue
  fi

  # Never follow symbolic links or cross into another filesystem.
  find -P "$workspace" -xdev -type d -exec chgrp "$READ_GROUP" {} +
  find -P "$workspace" -xdev -type d -exec chmod g+rX,g-w,g+s {} +
  find -P "$workspace" -xdev -type f -exec chgrp "$READ_GROUP" {} +
  find -P "$workspace" -xdev -type f -exec chmod g+r,g-w {} +
  chown "$username:$READ_GROUP" "$workspace"
  chmod 2750 "$workspace"
  echo "已迁移：$workspace（$username 可写，$READ_GROUP 只读）"
done

echo "PROJECT_READERS_SETUP_OK"
