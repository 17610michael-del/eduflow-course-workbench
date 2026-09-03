#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
NATIVE_DIR=/data/kltst/homework/services/hapi/native
HAPI_LINK="$NATIVE_DIR/hapi"
KEY_ENV=/etc/eduflow-ai/deepseek.env
BACKUP_ROOT=/var/backups/eduflow-hapi
SERVER_HOST="${HAPI_SERVER_HOST:-10.98.103.193}"

if [[ "$EUID" -ne 0 ]]; then
  echo "请在自己的终端使用 sudo 执行本脚本；不要把密码发送到聊天。" >&2
  exit 1
fi
if [[ "$#" -lt 1 ]]; then
  echo "用法：sudo bash $0 <linux-user> [linux-user ...]" >&2
  exit 1
fi
[[ -x "$HAPI_LINK" ]] || { echo "原生 HAPI 二进制不存在：$HAPI_LINK" >&2; exit 1; }
current_binary=$(readlink -f "$HAPI_LINK")
case "$current_binary" in
  "$NATIVE_DIR"/hapi-*) ;;
  *) echo "拒绝使用 native 目录之外的二进制：$current_binary" >&2; exit 1 ;;
esac
[[ -s "$KEY_ENV" ]] || { echo "缺少 root-only DeepSeek 环境文件：$KEY_ENV" >&2; exit 1; }
grep -q '^DEEPSEEK_API_KEY=.' "$KEY_ENV" || { echo "$KEY_ENV 缺少 DEEPSEEK_API_KEY。" >&2; exit 1; }

timestamp=$(date +%Y%m%d-%H%M%S)
backup_dir="$BACKUP_ROOT/$timestamp"
install -d -m 0700 -o root -g root "$backup_dir"
for unit in eduflow-hapi-hub@.service eduflow-hapi-runner@.service; do
  [[ -f "/etc/systemd/system/$unit" ]] && cp -a "/etc/systemd/system/$unit" "$backup_dir/$unit"
  install -m 0644 "$SCRIPT_DIR/$unit" "/etc/systemd/system/$unit"
done
previous_binary=$(find "$NATIVE_DIR" -maxdepth 1 -type f -name 'hapi-*' ! -samefile "$current_binary" -printf '%T@ %p\n' \
  | sort -nr | awk 'NR==1 {print $2}')
{
  printf 'CURRENT_BINARY=%s\n' "$current_binary"
  printf 'PREVIOUS_BINARY=%s\n' "${previous_binary:-}"
} >"$backup_dir/binaries.env"
chmod 0600 "$backup_dir/binaries.env"

systemctl daemon-reload
systemd-analyze verify \
  /etc/systemd/system/eduflow-hapi-hub@.service \
  /etc/systemd/system/eduflow-hapi-runner@.service

failed=0
for username in "$@"; do
  if [[ ! "$username" =~ ^[a-z_][a-z0-9_-]*$ ]] || ! getent passwd "$username" >/dev/null; then
    echo "FAIL $username：Linux 用户不存在或名称异常" >&2
    failed=1
    continue
  fi
  env_file="/etc/eduflow-hapi/$username.env"
  if [[ ! -s "$env_file" ]]; then
    echo "FAIL $username：缺少 $env_file" >&2
    failed=1
    continue
  fi
  port=$(sed -n 's/^HAPI_LISTEN_PORT=//p' "$env_file" | tail -n 1)
  if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 20000 || port > 60000 )); then
    echo "FAIL $username：HAPI_LISTEN_PORT 异常" >&2
    failed=1
    continue
  fi

  systemctl restart "eduflow-hapi-hub@$username.service"
  ready=0
  for _ in $(seq 1 40); do
    if curl --silent --fail --max-time 2 "http://127.0.0.1:$port/" >/dev/null; then
      ready=1
      break
    fi
    sleep 0.5
  done
  if [[ "$ready" -ne 1 ]]; then
    echo "FAIL $username：Hub 未在端口 $port 就绪" >&2
    failed=1
    continue
  fi

  systemctl restart "eduflow-hapi-runner@$username.service"
  if systemctl is-active --quiet "eduflow-hapi-hub@$username.service" \
    && systemctl is-active --quiet "eduflow-hapi-runner@$username.service"; then
    echo "READY $username http://$SERVER_HOST:$port/"
  else
    echo "FAIL $username：Hub 或 Runner 未运行" >&2
    failed=1
  fi
done

echo "当前二进制：$current_binary"
echo "配置备份：$backup_dir"
[[ "$failed" -eq 0 ]] || exit 1
echo "HAPI_NATIVE_FINALIZE_OK"
