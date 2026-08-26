#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo '请由 root 使用 sudo 执行。' >&2
  exit 1
fi

create_test_project=0
if [[ "${1:-}" == "--create-test-project" ]]; then
  create_test_project=1
  shift
fi
if [[ "$#" -lt 1 ]]; then
  echo "用法：sudo $0 [--create-test-project] student01 [student02 ...]" >&2
  exit 1
fi

READ_GROUP="${PROJECT_READ_GROUP:-eduflow-staff-read}"
if ! getent group "$READ_GROUP" >/dev/null; then
  echo "项目只读组不存在：$READ_GROUP" >&2
  exit 1
fi

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

  # Stay on the workspace filesystem and never follow symbolic links.
  find -P "$workspace" -xdev -type d -exec chgrp "$READ_GROUP" {} +
  find -P "$workspace" -xdev -type d -exec chmod g+rX,g-w,g+s {} +
  find -P "$workspace" -xdev -type f -exec chgrp "$READ_GROUP" {} +
  find -P "$workspace" -xdev -type f -exec chmod g+r,g-w {} +
  chown "$username:$READ_GROUP" "$workspace"
  chmod 2750 "$workspace"

  if [[ "$create_test_project" -eq 1 ]]; then
    install -d -m 2750 -o "$username" -g "$READ_GROUP" "$workspace/test-project"
    echo "已创建测试项目：$workspace/test-project"
  fi
  echo "已修正：$workspace（$username 可读写，$READ_GROUP 只读）"
done
