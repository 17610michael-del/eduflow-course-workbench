#!/usr/bin/env bash
set -euo pipefail

NATIVE_DIR=/data/kltst/homework/services/hapi/native
HAPI_LINK="$NATIVE_DIR/hapi"

if [[ "$EUID" -ne 0 ]]; then
  echo "请在自己的终端使用 sudo 执行本脚本；不要把密码发送到聊天。" >&2
  exit 1
fi
if [[ "$#" -lt 2 ]]; then
  echo "用法：sudo bash $0 /data/.../native/hapi-<version> <linux-user> [linux-user ...]" >&2
  exit 1
fi

rollback_binary=$(readlink -f "$1")
shift
case "$rollback_binary" in
  "$NATIVE_DIR"/hapi-*) ;;
  *) echo "拒绝回滚到 native 目录之外的文件：$rollback_binary" >&2; exit 1 ;;
esac
[[ -x "$rollback_binary" ]] || { echo "回滚二进制不可执行：$rollback_binary" >&2; exit 1; }

ln -sfn "$(basename "$rollback_binary")" "$HAPI_LINK"
for username in "$@"; do
  systemctl restart "eduflow-hapi-hub@$username.service"
  systemctl restart "eduflow-hapi-runner@$username.service"
  systemctl is-active --quiet "eduflow-hapi-hub@$username.service"
  systemctl is-active --quiet "eduflow-hapi-runner@$username.service"
  echo "ROLLED_BACK $username"
done
echo "当前二进制：$(readlink -f "$HAPI_LINK")"
echo "HAPI_NATIVE_ROLLBACK_OK"
