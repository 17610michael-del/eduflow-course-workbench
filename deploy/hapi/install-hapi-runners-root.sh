#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
RUNTIME_ROOT="${HAPI_RUNTIME_ROOT:-/data/kltst/homework/services/hapi/runtime}"
NATIVE_BIN="${HAPI_NATIVE_BIN:-/data/kltst/homework/services/hapi/native/hapi}"
HAPI_BIN="$NATIVE_BIN"
ENV_DIR=/etc/eduflow-hapi
SECRET_FILE="$ENV_DIR/token-secret"
DEEPSEEK_ENV=/etc/eduflow-ai/deepseek.env
SERVER_HOST="${HAPI_SERVER_HOST:-10.98.103.193}"
PORT_BASE="${HAPI_PORT_BASE:-32000}"
TEACHER_GROUP="${HAPI_TEACHER_GROUP:-teacher}"

usage() {
  echo "用法：sudo $0 student01 [student02 ...]" >&2
}

if [[ "$EUID" -ne 0 ]]; then
  echo "请由管理员在自己的终端使用 sudo 执行。" >&2
  exit 1
fi
if [[ "$#" -lt 1 ]]; then
  usage
  exit 1
fi
[[ "$PORT_BASE" =~ ^[0-9]+$ && "$PORT_BASE" -ge 20000 && "$PORT_BASE" -le 40000 ]] || {
  echo "HAPI_PORT_BASE 必须是 20000-40000 之间的整数。" >&2
  exit 1
}
[[ "$SERVER_HOST" =~ ^[A-Za-z0-9._:-]+$ ]] || {
  echo "HAPI_SERVER_HOST 格式不正确。" >&2
  exit 1
}
[[ -x "$HAPI_BIN" ]] || {
  echo "原生 HAPI 二进制不存在：$HAPI_BIN，请先在 kltst 下完成构建与测试。" >&2
  exit 1
}
if [[ ! -s "$DEEPSEEK_ENV" ]]; then
  echo "警告：$DEEPSEEK_ENV 不存在，Runner 将缺少 DEEPSEEK_API_KEY。" >&2
  echo "请先执行：sudo configure-deepseek-key-root.sh" >&2
  exit 1
fi
command -v python3 >/dev/null || { echo "缺少 python3。" >&2; exit 1; }
command -v openssl >/dev/null || { echo "缺少 openssl。" >&2; exit 1; }
command -v curl >/dev/null || { echo "缺少 curl。" >&2; exit 1; }

install -d -m 0700 -o root -g root "$ENV_DIR"
if [[ ! -s "$SECRET_FILE" ]]; then
  secret_tmp=$(mktemp)
  openssl rand -hex 32 >"$secret_tmp"
  install -m 0600 -o root -g root "$secret_tmp" "$SECRET_FILE"
  rm -f -- "$secret_tmp"
fi
[[ "$(stat -c %U:%G "$SECRET_FILE")" == "root:root" ]] || {
  echo "Token 派生密钥必须属于 root:root。" >&2
  exit 1
}
chmod 0600 "$SECRET_FILE"

install -m 0644 "$SCRIPT_DIR/eduflow-hapi-hub@.service" /etc/systemd/system/eduflow-hapi-hub@.service
install -m 0644 "$SCRIPT_DIR/eduflow-hapi-runner@.service" /etc/systemd/system/eduflow-hapi-runner@.service
systemctl daemon-reload

derive_token() {
  local username="$1"
  python3 - "$SECRET_FILE" "$username" <<'PY'
import base64
import hashlib
import hmac
import pathlib
import sys

secret_hex = pathlib.Path(sys.argv[1]).read_text(encoding="ascii").strip()
secret = bytes.fromhex(secret_hex)
digest = hmac.new(secret, f"eduflow-hapi-hub:{sys.argv[2]}".encode(), hashlib.sha256).digest()
print("ehh_" + base64.urlsafe_b64encode(digest).decode().rstrip("="))
PY
}

for username in "$@"; do
  if [[ ! "$username" =~ ^[a-z_][a-z0-9_-]*$ ]]; then
    echo "跳过异常用户名：$username" >&2
    continue
  fi
  if ! getent passwd "$username" >/dev/null; then
    echo "跳过不存在的 Linux 用户：$username" >&2
    continue
  fi
  if [[ ! -d "/data/$username" ]]; then
    echo "跳过 $username：工作区 /data/$username 不存在" >&2
    continue
  fi

  home_dir=$(getent passwd "$username" | cut -d: -f6)
  primary_group=$(id -gn "$username")
  uid_number=$(id -u "$username")
  port=$((PORT_BASE + uid_number - 1000))
  if [[ "$port" -lt 20000 || "$port" -gt 60000 ]]; then
    echo "跳过 $username：根据 UID 计算的端口超出范围 ($port)" >&2
    continue
  fi

  token=$(derive_token "$username")
  [[ "$token" =~ ^ehh_[A-Za-z0-9_-]{40,}$ ]] || {
    echo "无法为 $username 派生 Token。" >&2
    exit 1
  }

  install -d -m 0700 -o "$username" -g "$primary_group" \
    "$home_dir/.hapi-hub" "$home_dir/.hapi-runner"
  # EduFlow runs as a separate Linux account and must traverse .config to read
  # the teacher-group-protected HAPI access file. 0751 permits traversal only;
  # it does not permit other users to list the student's configuration files.
  install -d -m 0751 -o "$username" -g "$primary_group" "$home_dir/.config"
  access_group="$primary_group"
  if getent group "$TEACHER_GROUP" >/dev/null; then
    access_group="$TEACHER_GROUP"
  fi
  install -d -m 0750 -o "$username" -g "$access_group" "$home_dir/.config/eduflow-hapi"

  env_tmp=$(mktemp)
  access_tmp=$(mktemp)
  chmod 0600 "$env_tmp" "$access_tmp"
  {
    printf 'CLI_API_TOKEN=%s\n' "$token"
    printf 'HAPI_API_URL=http://127.0.0.1:%s\n' "$port"
    printf 'HAPI_LISTEN_HOST=0.0.0.0\n'
    printf 'HAPI_LISTEN_PORT=%s\n' "$port"
    printf 'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n'
  } >"$env_tmp"
  {
    printf 'HAPI_HUB_URL=http://%s:%s\n' "$SERVER_HOST" "$port"
    printf 'HAPI_HUB_TOKEN=%s\n' "$token"
    printf 'HAPI_WORKSPACE=/data/%s\n' "$username"
  } >"$access_tmp"
  install -m 0600 -o root -g root "$env_tmp" "$ENV_DIR/$username.env"
  install -m 0640 -o "$username" -g "$access_group" "$access_tmp" "$home_dir/.config/eduflow-hapi/access.env"
  rm -f -- "$env_tmp" "$access_tmp"
  unset token

  systemctl enable "eduflow-hapi-hub@$username.service" "eduflow-hapi-runner@$username.service" >/dev/null
  systemctl restart "eduflow-hapi-hub@$username.service"

  hub_ready=0
  for _ in $(seq 1 40); do
    if curl --silent --fail --max-time 2 "http://127.0.0.1:$port/" >/dev/null; then
      hub_ready=1
      break
    fi
    sleep 0.5
  done
  if [[ "$hub_ready" -ne 1 ]]; then
    echo "Hub 启动失败：$username（端口 $port）" >&2
    systemctl --no-pager --full status "eduflow-hapi-hub@$username.service" >&2 || true
    continue
  fi

  systemctl restart "eduflow-hapi-runner@$username.service"
  if systemctl is-active --quiet "eduflow-hapi-runner@$username.service"; then
    echo "已启用 $username：独立 Hub http://$SERVER_HOST:$port，仅允许 /data/$username"
    echo "  学生/教师凭据文件：$home_dir/.config/eduflow-hapi/access.env"
  else
    echo "Runner 启动失败：$username" >&2
    systemctl --no-pager --full status "eduflow-hapi-runner@$username.service" >&2 || true
  fi
done

echo "HAPI_INDEPENDENT_HUBS_INSTALL_OK"
