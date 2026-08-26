#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo '请由 root 使用 sudo 执行。' >&2
  exit 1
fi
if [[ "$#" -lt 1 ]]; then
  echo "用法：sudo $0 student01 [student02 ...]" >&2
  exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
APP_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)
READ_GROUP="${PROJECT_READ_GROUP:-eduflow-staff-read}"
if ! getent group "$READ_GROUP" >/dev/null; then
  echo "项目只读组不存在：$READ_GROUP" >&2
  exit 1
fi
install -m 0644 "$SCRIPT_DIR/eduflow-project-agent@.service" /etc/systemd/system/eduflow-project-agent@.service
systemctl daemon-reload

for username in "$@"; do
  if ! getent passwd "$username" >/dev/null; then
    echo "跳过不存在的 Linux 用户：$username" >&2
    continue
  fi
  install -d -m 2750 -o "$username" -g "$READ_GROUP" "/data/$username"
  echo "项目目录已准备：/data/$username（教师/助教只读组 $READ_GROUP 可读）"
  home_dir=$(getent passwd "$username" | cut -d: -f6)
  token_file="$home_dir/.config/eduflow-monitor/token"
  if ! "$APP_DIR/venv/bin/python" "$SCRIPT_DIR/provision_project_agent.py" "$username"; then
    echo "跳过 $username：Token 自动配置失败" >&2
    continue
  fi
  if ! runuser -u "$username" -- /usr/bin/python3 /data/kltst/project/monitor/project_agent.py \
    --server http://127.0.0.1:8000 \
    --token-file "$token_file" \
    --workspace "/data/$username" \
    --once; then
    echo "跳过 $username：首次上报失败，未启用服务" >&2
    continue
  fi
  systemctl enable --now "eduflow-project-agent@${username}.service"
  echo "已启用：$username"
done
