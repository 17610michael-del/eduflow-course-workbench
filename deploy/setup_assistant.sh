#!/usr/bin/env bash
set -euo pipefail

ASSISTANT_GROUP="assistant"
read -r -a ASSISTANTS <<< "${ASSISTANT_USERS:-assistant01 assistant02}"

if [[ $EUID -ne 0 ]]; then
  echo "请以 root 运行：sudo bash $0" >&2
  exit 1
fi

make_user() {
  local user="$1"
  useradd -m -s /bin/bash "$user"
  echo "请为 $user 设置临时密码："
  passwd "$user"
  chage -d 0 "$user"
}

getent group "$ASSISTANT_GROUP" >/dev/null 2>&1 || groupadd "$ASSISTANT_GROUP"

echo "=== EduFlow 助教账号创建结果 ==="
for a in "${ASSISTANTS[@]}"; do
  if id "$a" >/dev/null 2>&1; then
    echo "助教 $a  已存在，未改动密码"
    usermod -aG "$ASSISTANT_GROUP" "$a" 2>/dev/null || true
  else
    make_user "$a"
    usermod -aG "$ASSISTANT_GROUP" "$a"
    echo "助教 $a 已创建；首次登录必须修改密码"
  fi
done
