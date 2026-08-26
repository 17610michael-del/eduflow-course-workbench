#!/usr/bin/env bash
set -euo pipefail

AGENT_PATH=/data/kltst/project/monitor/project_agent.py
TOKEN_DIR="$HOME/.config/eduflow-monitor"
TOKEN_FILE="$TOKEN_DIR/token"
WORKSPACE="/data/$(id -un)"

if [[ ! -f "$AGENT_PATH" ]]; then
  echo "未找到项目监控 Agent：$AGENT_PATH" >&2
  exit 1
fi
if [[ ! -d "$WORKSPACE" ]]; then
  echo "未找到项目目录：$WORKSPACE" >&2
  echo "请先让管理员创建并授权该目录。" >&2
  exit 1
fi

printf '为用户 %s 配置 EduFlow 项目监控。\n' "$(id -un)"
read -r -s -p '粘贴网页生成的 Agent Token：' AGENT_TOKEN
printf '\n'
if [[ "$AGENT_TOKEN" != epm_* ]]; then
  echo 'Token 格式不正确。' >&2
  exit 1
fi

umask 077
mkdir -p "$TOKEN_DIR"
printf '%s\n' "$AGENT_TOKEN" > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"
unset AGENT_TOKEN

python3 "$AGENT_PATH" \
  --server http://127.0.0.1:8000 \
  --token-file "$TOKEN_FILE" \
  --workspace "$WORKSPACE" \
  --once

echo '首次上报成功。请让管理员启用常驻服务：'
printf 'sudo systemctl enable --now eduflow-project-agent@%s\n' "$(id -un)"
