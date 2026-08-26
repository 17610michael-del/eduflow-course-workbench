#!/usr/bin/env bash
set -euo pipefail

REAL_CLAUDE=/data/kltst/homework/services/hapi/runtime/global/bin/claude
[[ -x "$REAL_CLAUDE" ]] || { echo "Claude Code 运行时不存在。" >&2; exit 1; }

# EduFlow 不向学生暴露模型或供应商选择。即使 HAPI 客户端传入 model 参数，
# 也在服务器端丢弃并强制使用管理员配置的 DeepSeek 模型。
filtered=()
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --model|--fallback-model)
      shift
      [[ "$#" -gt 0 ]] && shift
      ;;
    --model=*|--fallback-model=*)
      shift
      ;;
    *)
      filtered+=("$1")
      shift
      ;;
  esac
done

export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
export ANTHROPIC_MODEL='deepseek-v4-pro[1m]'
export ANTHROPIC_DEFAULT_OPUS_MODEL='deepseek-v4-pro[1m]'
export ANTHROPIC_DEFAULT_SONNET_MODEL='deepseek-v4-pro[1m]'
export ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash
export CLAUDE_CODE_SUBAGENT_MODEL=deepseek-v4-flash
export CLAUDE_CODE_EFFORT_LEVEL=max
export DISABLE_AUTOUPDATER=1
unset ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY XAI_API_KEY

exec "$REAL_CLAUDE" --model 'deepseek-v4-pro[1m]' "${filtered[@]}"
