#!/usr/bin/env bash
# One-time move of an install made under the old name "jarvis" to "justday":
# config, data (brain, models, local LLM), state/journal, Claude Code memory of the brain, services, hotkeys.
# Safe to run again: does nothing when there is nothing old left.
set -uo pipefail
CFG="${XDG_CONFIG_HOME:-$HOME/.config}"; DATA="${XDG_DATA_HOME:-$HOME/.local/share}"; STATE="${XDG_STATE_HOME:-$HOME/.local/state}"
UNITS="$CFG/systemd/user"
moved=0

mv_dir() {  # $1 old, $2 new — merge when the new one already exists
  [[ -e "$1" ]] || return 0
  if [[ -e "$2" ]]; then cp -an "$1/." "$2/" && rm -rf "$1"; else mkdir -p "$(dirname "$2")" && mv "$1" "$2"; fi
  echo "moved $1 → $2"; moved=1
}

old_units=()
for u in jarvis.service jarvis-overlay.service jarvis-ollama.service; do [[ -f "$UNITS/$u" ]] && old_units+=("$u"); done
if ((${#old_units[@]})); then
  systemctl --user disable --now "${old_units[@]}" 2>/dev/null
  for u in "${old_units[@]}"; do rm -f "$UNITS/$u"; done
  systemctl --user daemon-reload
  moved=1
fi

mv_dir "$CFG/jarvis" "$CFG/justday"
mv_dir "$DATA/jarvis" "$DATA/justday"
mv_dir "$STATE/jarvis" "$STATE/justday"
# Claude Code keys a project's memory and transcripts by its working directory
mv_dir "$HOME/.claude/projects/$(echo "$DATA/jarvis/brain" | sed 's/[^A-Za-z0-9]/-/g')" \
       "$HOME/.claude/projects/$(echo "$DATA/justday/brain" | sed 's/[^A-Za-z0-9]/-/g')"

# paths written into the config by earlier versions
[[ -f "$CFG/justday/config.toml" ]] && sed -i 's#/\.config/jarvis/#/.config/justday/#g; s#/\.local/share/jarvis/#/.local/share/justday/#g' "$CFG/justday/config.toml"
# the old conversation cannot be resumed from the new directory
[[ -f "$STATE/justday/state.json" ]] && python3 - "$STATE/justday/state.json" <<'EOF'
import json, sys
p = sys.argv[1]; s = json.load(open(p)); s.pop("brain_session_id", None); json.dump(s, open(p, "w"), ensure_ascii=False, indent=1)
EOF

apps="$DATA/applications"
for id in net.local.jarvis.desktop net.local.jarvis-stop.desktop; do
  if [[ -f "$apps/$id" ]]; then
    gdbus call --session --dest org.kde.kglobalaccel --object-path /kglobalaccel \
      --method org.kde.KGlobalAccel.unregister "$id" "_launch" >/dev/null 2>&1
    kwriteconfig6 --file kglobalshortcutsrc --group services --group "$id" --key _launch --delete 2>/dev/null
    rm -f "$apps/$id"; moved=1
  fi
done
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1

((moved)) && echo "migration from jarvis done" || echo "nothing to migrate"
