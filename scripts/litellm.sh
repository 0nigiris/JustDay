#!/usr/bin/env bash
# Переводчик для бесплатных моделей. Слушает только 127.0.0.1: свои порты наружу не смотрят.
set -euo pipefail
key() { secret-tool lookup service justday key "$1" 2>/dev/null || true; }
export NVIDIA_NIM_API_KEY="$(key nvidia)" CLOUDFLARE_API_KEY="$(key cloudflare)" LITELLM_MASTER_KEY="$(key litellm)"
export POLLINATIONS_API_KEY="$(key pollinations)"; POLLINATIONS_API_KEY="${POLLINATIONS_API_KEY:-anon}"
export CLOUDFLARE_ACCOUNT_ID="$(sed -n 's/^cloudflare_account *= *"\(.*\)"/\1/p' "${XDG_CONFIG_HOME:-$HOME/.config}/justday/config.toml" | head -1)"
# родной протокол Cloudflare принимает только строку в content, а Claude Code шлёт список частей
export CLOUDFLARE_OPENAI_BASE="https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/ai/v1"
[[ -n $LITELLM_MASTER_KEY ]] || { echo "нет ключа litellm в связке: justday secret set litellm" >&2; exit 1; }
exec "$HOME/.local/bin/litellm" --config "$(dirname "$0")/../shell/litellm/config.yaml" --host 127.0.0.1 --port 4000
