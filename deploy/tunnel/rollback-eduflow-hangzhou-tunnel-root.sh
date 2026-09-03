#!/usr/bin/env bash
set -euo pipefail

UNIT_NAME=eduflow-hangzhou-tunnel.service
UNIT_TARGET="/etc/systemd/system/$UNIT_NAME"
BACKUP_ROOT=/var/backups/eduflow-tunnel

if [[ "$EUID" -ne 0 ]]; then
  echo "请在自己的终端使用 sudo 执行本脚本；不要把密码发送到聊天。" >&2
  exit 1
fi

backup_dir="${1:-}"
if [[ -z "$backup_dir" && -d "$BACKUP_ROOT" ]]; then
  backup_dir=$(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
    | sort -nr | awk 'NR==1 {print $2}')
fi

systemctl disable --now "$UNIT_NAME" 2>/dev/null || true
if [[ -n "$backup_dir" && -f "$backup_dir/$UNIT_NAME" ]]; then
  install -m 0644 -o root -g root "$backup_dir/$UNIT_NAME" "$UNIT_TARGET"
  systemctl daemon-reload
  systemd-analyze verify "$UNIT_TARGET"
  systemctl enable --now "$UNIT_NAME"
  echo "EDUFLOW_HANGZHOU_TUNNEL_RESTORED $backup_dir/$UNIT_NAME"
else
  rm -f "$UNIT_TARGET"
  systemctl daemon-reload
  systemctl reset-failed "$UNIT_NAME" 2>/dev/null || true
  echo "没有可恢复的旧 unit；已卸载当前隧道服务。"
  echo "EDUFLOW_HANGZHOU_TUNNEL_REMOVED"
fi
