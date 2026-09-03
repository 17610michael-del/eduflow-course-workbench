#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
UNIT_NAME=eduflow-hangzhou-tunnel.service
UNIT_SOURCE="$SCRIPT_DIR/$UNIT_NAME"
UNIT_TARGET="/etc/systemd/system/$UNIT_NAME"
TUNNEL_USER=kltst
TUNNEL_KEY="/home/$TUNNEL_USER/.ssh/id_ed25519_eduflow_hz"
KNOWN_HOSTS="/home/$TUNNEL_USER/.ssh/known_hosts_eduflow_hz"
LEGACY_PID=/data/kltst/homework/logs/eduflow-hangzhou-tunnel.pid
PUBLIC_URL=https://eduflow.47.96.100.122.nip.io/

if [[ "$EUID" -ne 0 ]]; then
  echo "请在自己的终端使用 sudo 执行本脚本；不要把密码发送到聊天。" >&2
  exit 1
fi

[[ -f "$UNIT_SOURCE" ]] || { echo "缺少服务模板：$UNIT_SOURCE" >&2; exit 1; }
getent passwd "$TUNNEL_USER" >/dev/null || { echo "Linux 用户不存在：$TUNNEL_USER" >&2; exit 1; }
[[ -r "$TUNNEL_KEY" ]] || { echo "缺少隧道私钥：$TUNNEL_KEY" >&2; exit 1; }
[[ -r "$KNOWN_HOSTS" ]] || { echo "缺少固定主机密钥文件：$KNOWN_HOSTS" >&2; exit 1; }

key_mode=$(stat -c '%a' "$TUNNEL_KEY")
if [[ "$key_mode" != 600 ]]; then
  echo "隧道私钥权限必须为 600，当前为：$key_mode" >&2
  exit 1
fi
key_owner=$(stat -c '%U:%G' "$TUNNEL_KEY")
if [[ "$key_owner" != "$TUNNEL_USER:$TUNNEL_USER" ]]; then
  echo "隧道私钥属主必须为 $TUNNEL_USER:$TUNNEL_USER，当前为：$key_owner" >&2
  exit 1
fi
known_hosts_owner=$(stat -c '%U:%G' "$KNOWN_HOSTS")
if [[ "$known_hosts_owner" != "$TUNNEL_USER:$TUNNEL_USER" ]]; then
  echo "固定主机密钥文件属主必须为 $TUNNEL_USER:$TUNNEL_USER，当前为：$known_hosts_owner" >&2
  exit 1
fi

if [[ -f "$LEGACY_PID" ]]; then
  legacy_pid=$(cat "$LEGACY_PID" 2>/dev/null || true)
  if [[ "$legacy_pid" =~ ^[0-9]+$ ]] && [[ -r "/proc/$legacy_pid/cmdline" ]]; then
    legacy_cmd=$(tr '\0' ' ' <"/proc/$legacy_pid/cmdline")
    if [[ "$legacy_cmd" == *id_ed25519_eduflow_hz* && "$legacy_cmd" == *47.96.100.122* ]]; then
      kill "$legacy_pid"
      for _ in $(seq 1 20); do
        kill -0 "$legacy_pid" 2>/dev/null || break
        sleep 0.25
      done
      if kill -0 "$legacy_pid" 2>/dev/null; then
        kill -KILL "$legacy_pid"
        sleep 1
      fi
      if kill -0 "$legacy_pid" 2>/dev/null; then
        echo "无法停止旧隧道进程：$legacy_pid" >&2
        exit 1
      fi
    fi
  fi
  rm -f "$LEGACY_PID"
fi

backup_dir="/var/backups/eduflow-tunnel/$(date +%Y%m%d-%H%M%S)"
install -d -m 0700 -o root -g root "$backup_dir"
if [[ -f "$UNIT_TARGET" ]]; then
  cp -a "$UNIT_TARGET" "$backup_dir/$UNIT_NAME"
fi

restore_previous_unit() {
  set +e
  systemctl disable --now "$UNIT_NAME" >/dev/null 2>&1
  if [[ -f "$backup_dir/$UNIT_NAME" ]]; then
    install -m 0644 -o root -g root "$backup_dir/$UNIT_NAME" "$UNIT_TARGET"
  else
    rm -f "$UNIT_TARGET"
  fi
  systemctl daemon-reload
  if [[ -f "$backup_dir/$UNIT_NAME" ]]; then
    systemctl enable --now "$UNIT_NAME"
  fi
  set -e
}

install -m 0644 -o root -g root "$UNIT_SOURCE" "$UNIT_TARGET"
systemctl daemon-reload
if ! systemd-analyze verify "$UNIT_TARGET"; then
  restore_previous_unit
  exit 1
fi
if ! systemctl enable "$UNIT_NAME"; then
  restore_previous_unit
  exit 1
fi
# 必须显式 restart：enable --now 不会替换已在运行的旧隧道进程。
if ! systemctl restart "$UNIT_NAME"; then
  restore_previous_unit
  exit 1
fi

for _ in $(seq 1 30); do
  systemctl is-active --quiet "$UNIT_NAME" && break
  sleep 0.5
done
systemctl is-active --quiet "$UNIT_NAME" || {
  journalctl -u "$UNIT_NAME" --no-pager -n 40 >&2
  restore_previous_unit
  exit 1
}

sleep 5
if ! systemctl is-active --quiet "$UNIT_NAME"; then
  echo "隧道服务启动后未保持运行。" >&2
  journalctl -u "$UNIT_NAME" --no-pager -n 40 >&2
  restore_previous_unit
  echo "本次安装已回退；备份目录：$backup_dir" >&2
  exit 1
fi

# 部分内网主机无法经云主机公网 IP 回环访问，因此公网检查仅作提示。
if curl --silent --show-error --fail --location --connect-timeout 5 --max-time 15 "$PUBLIC_URL" >/dev/null; then
  echo "公网检查通过：$PUBLIC_URL"
else
  echo "提示：193 无法直接验证公网入口，请从外部浏览器复核；隧道服务本身已运行。" >&2
fi

echo "EDUFLOW_HANGZHOU_TUNNEL_READY $PUBLIC_URL"
echo "配置备份：$backup_dir"
