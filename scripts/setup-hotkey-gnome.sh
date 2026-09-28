#!/usr/bin/env bash
# Регистрирует горячие клавиши JustDay в GNOME (там, где нет KDE и kwriteconfig):
#   talk   (по умолчанию <Super>j)       → justday toggle
#   cancel (<Super><Shift>j)             → justday stop
#   type   (<Super>k)                    → justday compose
# Usage: setup-hotkey-gnome.sh [--talk "<Super>j"] [--cancel "<Super><Shift>j"] [--type "<Super>k"] [--remove]
#
# GNOME держит свои сочетания в media-keys/custom-keybindings: список путей плюс по три ключа на каждый.
set -euo pipefail
TALK="<Super>j"; CANCEL="<Super><Shift>j"; TYPE="<Super>k"; REMOVE=0
while (($#)); do
  case "$1" in
    --talk) TALK="$2"; shift ;;
    --cancel) CANCEL="$2"; shift ;;
    --type) TYPE="$2"; shift ;;
    --remove) REMOVE=1 ;;
  esac
  shift
done
command -v gsettings >/dev/null || { echo "нужен gsettings (GNOME)" >&2; exit 1; }
JUSTDAY="$HOME/.local/bin/justday"
ROOT=/org/gnome/settings-daemon/plugins/media-keys
SCHEMA=org.gnome.settings-daemon.plugins.media-keys

current=$(gsettings get $SCHEMA custom-keybindings 2>/dev/null || echo "@as []")
keep=$(printf '%s' "$current" | tr -d "[]@as '" | tr ',' '\n' | grep -v '/justday-' | grep -v '^$' || true)

add() {  # add NAME COMMAND BINDING
  local name=$1 cmd=$2 key=$3 path="$ROOT/custom-keybindings/justday-$1/"
  gsettings set "$SCHEMA.custom-keybinding:$path" name "JustDay: $name"
  gsettings set "$SCHEMA.custom-keybinding:$path" command "$cmd"
  gsettings set "$SCHEMA.custom-keybinding:$path" binding "$key"
  printf '%s\n' "$path"
}

if ((REMOVE)); then
  list=$(printf '%s\n' $keep | sed "s|.*|'&'|" | paste -sd, -)
  gsettings set $SCHEMA custom-keybindings "[${list}]"
  echo "JustDay shortcuts removed"
  exit 0
fi

paths=$(
  printf '%s\n' $keep
  [[ -n "$TALK" ]] && add talk "$JUSTDAY toggle" "$TALK"
  [[ -n "$CANCEL" ]] && add cancel "$JUSTDAY stop" "$CANCEL"
  [[ -n "$TYPE" ]] && add type "$JUSTDAY compose" "$TYPE"
)
list=$(printf '%s\n' $paths | grep -v '^$' | sed "s|.*|'&'|" | paste -sd, -)
gsettings set $SCHEMA custom-keybindings "[${list}]"
echo "shortcuts: talk=$TALK cancel=$CANCEL type=$TYPE"
