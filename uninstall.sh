#!/usr/bin/env bash
# Removes JustDay. Keeps Claude Code, system packages and (unless --purge) your config, memory and logs.
set -uo pipefail
PURGE=0; [[ "${1:-}" == "--purge" ]] && PURGE=1
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Все наши юниты по маске, а не списком: список отстал (justday-ui, voice, guard, chatterbox и их сокеты
# оставались жить после удаления и падали без программы). justday-night — временная, файла у неё нет.
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
units=$(cd "$UNIT_DIR" 2>/dev/null && ls justday*.service justday*.socket justday*.timer 2>/dev/null)
systemctl --user stop justday-night.service 2>/dev/null
[[ -n "$units" ]] && systemctl --user disable --now $units 2>/dev/null
for u in $units; do rm -f "$UNIT_DIR/$u"; done
systemctl --user daemon-reload
# Сначала вернуть соседям забранные клавиши (Meta → меню Plasma, Alt+Space → KRunner), пока есть venv.
"$HOME/.local/bin/justday" hotkey restore 2>/dev/null
"$APP_DIR/scripts/setup-hotkey.sh" --remove --mouse ExtraButton1 2>/dev/null
rm -f "$HOME/.local/bin/justday" "$HOME/.local/bin/jarvis"
# Все ключи JustDay лежат с атрибутом service=justday (config.set_secret): чистим по нему, а не списком —
# список забывал ElevenLabs, Telegram, Telnyx и календарь.
providers_secrets() { secret-tool clear service justday 2>/dev/null; }
uv tool uninstall kwin-mcp 2>/dev/null
rm -rf "$APP_DIR/.venv"
if ((PURGE)); then
  brain="${XDG_DATA_HOME:-$HOME/.local/share}/justday/brain"
  rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/justday" "${XDG_DATA_HOME:-$HOME/.local/share}/justday" \
         "${XDG_STATE_HOME:-$HOME/.local/state}/justday" "$HOME/.claude/projects/$(echo "$brain" | sed 's/[^A-Za-z0-9]/-/g')" \
         "${XDG_CACHE_HOME:-$HOME/.cache}/justday"  # обложки и видео острова: по ним видно, что он смотрел и слушал
  providers_secrets
  echo "Purged config, models (incl. the local LLM), memory, logs and stored keys."
fi
echo "JustDay removed. (Code directory $APP_DIR left in place — delete it yourself if you want.)"
