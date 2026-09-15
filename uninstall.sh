#!/usr/bin/env bash
# Removes JustDay. Keeps Claude Code, system packages and (unless --purge) your config, memory and logs.
set -uo pipefail
PURGE=0; [[ "${1:-}" == "--purge" ]] && PURGE=1
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

systemctl --user disable --now justday.service justday-overlay.service justday-island.service justday-ollama.service 2>/dev/null
for u in justday.service justday-overlay.service justday-island.service justday-ollama.service; do rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/$u"; done
systemctl --user daemon-reload
"$APP_DIR/scripts/setup-hotkey.sh" --remove --mouse ExtraButton1 2>/dev/null
rm -f "$HOME/.local/bin/justday" "$HOME/.local/bin/jarvis"
providers_secrets() { for k in mail openrouter deepseek custom; do secret-tool clear service justday key "$k" 2>/dev/null; done; }
uv tool uninstall kwin-mcp 2>/dev/null
rm -rf "$APP_DIR/.venv"
if ((PURGE)); then
  brain="${XDG_DATA_HOME:-$HOME/.local/share}/justday/brain"
  rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/justday" "${XDG_DATA_HOME:-$HOME/.local/share}/justday" \
         "${XDG_STATE_HOME:-$HOME/.local/state}/justday" "$HOME/.claude/projects/$(echo "$brain" | sed 's/[^A-Za-z0-9]/-/g')"
  providers_secrets
  echo "Purged config, models (incl. the local LLM), memory, logs and stored keys."
fi
echo "JustDay removed. (Code directory $APP_DIR left in place — delete it yourself if you want.)"
