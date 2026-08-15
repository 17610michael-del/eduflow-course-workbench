#!/usr/bin/env bash
set -euo pipefail

TEACHER_GROUP="teacher"
TEACHER_USER="${TEACHER_USER:-teacher01}"
read -r -a STUDENTS <<< "${STUDENT_USERS:-student01 student02 student03}"

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

echo "=== EduFlow 账号创建结果 ==="

if id "$TEACHER_USER" >/dev/null 2>&1; then
  echo "老师 $TEACHER_USER  已存在，未改动密码"
else
  make_user "$TEACHER_USER"
  usermod -aG "$TEACHER_GROUP" "$TEACHER_USER"
  echo "老师 $TEACHER_USER 已创建；首次登录必须修改密码"
fi

for s in "${STUDENTS[@]}"; do
  if id "$s" >/dev/null 2>&1; then
    echo "学生 $s  已存在，未改动密码"
  else
    make_user "$s"
    echo "学生 $s 已创建；首次登录必须修改密码"
  fi
done
