#!/usr/bin/env bash
set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
  echo "请由管理员在自己的终端使用 sudo 执行。" >&2
  exit 1
fi

CONFIG_DIR=/etc/eduflow-ai
KEY_FILE="$CONFIG_DIR/deepseek.env"
DROPIN_DIR=/etc/systemd/system/homework.service.d

read -r -s -p "请输入新的 DeepSeek API Key（不会回显）：" DEEPSEEK_KEY
echo
if [[ ${#DEEPSEEK_KEY} -lt 20 || "$DEEPSEEK_KEY" =~ [[:space:]] ]]; then
  echo "DeepSeek API Key 格式不符合预期。" >&2
  unset DEEPSEEK_KEY
  exit 1
fi

echo "正在验证 DeepSeek API Key..."
if ! DEEPSEEK_API_KEY="$DEEPSEEK_KEY" /usr/bin/python3 - <<'PY'
import json
import os
import urllib.error
import urllib.request

request = urllib.request.Request(
    "https://api.deepseek.com/models",
    headers={"Authorization": "Bearer " + os.environ["DEEPSEEK_API_KEY"]},
)
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        json.load(response)
except urllib.error.HTTPError as exc:
    raise SystemExit(f"Key 验证失败：DeepSeek HTTP {exc.code}")
except (urllib.error.URLError, TimeoutError, ValueError) as exc:
    raise SystemExit(f"Key 验证失败：{type(exc).__name__}")
print("DEEPSEEK_KEY_VALID")
PY
then
  unset DEEPSEEK_KEY
  exit 1
fi

install -d -m 0700 -o root -g root "$CONFIG_DIR"
key_tmp=$(mktemp)
chmod 0600 "$key_tmp"
{
  printf 'DEEPSEEK_API_KEY=%s\n' "$DEEPSEEK_KEY"
  printf 'DEEPSEEK_BASE_URL=https://api.deepseek.com\n'
  printf 'DEEPSEEK_CHAT_MODEL=deepseek-v4-flash\n'
  printf 'DEEPSEEK_REASONING_MODEL=deepseek-v4-pro\n'
} >"$key_tmp"
install -m 0600 -o root -g root "$key_tmp" "$KEY_FILE"
rm -f -- "$key_tmp"
unset DEEPSEEK_KEY

install -d -m 0755 -o root -g root "$DROPIN_DIR"
dropin_tmp=$(mktemp)
cat >"$dropin_tmp" <<'EOF'
[Service]
EnvironmentFile=-/etc/eduflow-ai/deepseek.env
EOF
install -m 0644 -o root -g root "$dropin_tmp" "$DROPIN_DIR/deepseek.conf"
rm -f -- "$dropin_tmp"

systemctl daemon-reload
systemctl restart homework.service
while read -r service_name; do
  [[ -n "$service_name" ]] && systemctl restart "$service_name"
done < <(systemctl list-units --type=service --state=active 'eduflow-hapi-runner@*.service' \
  --no-legend --plain | awk '{print $1}')

systemctl is-active --quiet homework.service || {
  echo "Key 已保存，但 homework 服务重启失败，请检查 systemctl status homework。" >&2
  exit 1
}
echo "DEEPSEEK_KEY_CONFIGURED"
echo "Key 已保存到 root-only 环境文件，课程网站与原生 HAPI DeepSeek 驱动共用。"
