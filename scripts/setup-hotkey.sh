#!/usr/bin/env bash
# Registers KDE Plasma 6 global shortcuts for JustDay:
#   talk   (default Meta+J, plus F19 for a remapped mouse button; F13 is XF86Tools = System Settings in KDE) → `justday toggle`
#   cancel (default Meta+Shift+J)                                 → `justday stop`
#   type   (default Meta+K)  → `justday compose`  (text field, takes the selected text along)
#   yes / no (Meta+Y / Meta+N) → `justday approve` / `justday deny`  (answer the island's question from the keyboard)
# Usage: setup-hotkey.sh [--talk "Meta+J"] [--extra F19] [--cancel "Meta+Shift+J"] [--type Meta+K] [--yes Meta+Y]
#                        [--no Meta+N] [--mouse ExtraButton1] [--remove]      (an empty key = don't register it)
#
# kglobalacceld only activates command shortcuts for *service* components, which it creates from
# desktop files carrying X-KDE-Shortcuts (found through the KSycoca cache). A plain D-Bus doRegister()
# yields an inactive action that ignores key presses — hence desktop files + kbuildsycoca6.
set -euo pipefail
TALK="Meta+J"; CANCEL="Meta+Shift+J"; EXTRA="F19"; TYPE="Meta+K"; YES="Meta+Y"; NO="Meta+N"; MOUSE=""; REMOVE=0
while (($#)); do
  case "$1" in
    --talk) TALK="$2"; shift ;;
    --extra) EXTRA="$2"; shift ;;   # second talk key, e.g. what a gaming mouse button sends ("" = none)
    --cancel) CANCEL="$2"; shift ;;
    --type) TYPE="$2"; shift ;;
    --yes) YES="$2"; shift ;;
    --no) NO="$2"; shift ;;
    --mouse) MOUSE="$2"; shift ;;
    --remove) REMOVE=1 ;;
    *) TALK="$1" ;;  # backwards compatible: first positional = talk key
  esac
  shift
done
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"

unregister() {  # $1 desktop id
  gdbus call --session --dest org.kde.kglobalaccel --object-path /kglobalaccel \
    --method org.kde.KGlobalAccel.unregister "$1" "_launch" >/dev/null 2>&1 || true
  qdbus-qt6 org.kde.kglobalaccel "/component/${1//[.-]/_}" org.kde.kglobalaccel.Component.cleanUp >/dev/null 2>&1 || true
}

register() {  # $1 desktop id, $2 name, $3 command, $4.. keys
  local id="$1" name="$2" cmd="$3"; shift 3
  local keys_csv keys_tab
  keys_csv=$(IFS=,; echo "$*"); keys_tab=$(printf '%s\t' "$@"); keys_tab="${keys_tab%$'\t'}"
  cat > "$APPS/$id" <<EOF
[Desktop Entry]
Type=Application
Name=$name
Exec=$cmd
Icon=audio-input-microphone
NoDisplay=true
X-KDE-GlobalAccel-CommandShortcut=true
X-KDE-Shortcuts=$keys_csv
EOF
  unregister "$id"
  kwriteconfig6 --file kglobalshortcutsrc --group services --group "$id" --key _launch "$keys_tab"
  echo "shortcut ${keys_csv} → $cmd"
}

if ((REMOVE)); then
  for id in net.local.justday.desktop net.local.justday-stop.desktop net.local.justday-type.desktop \
            net.local.justday-yes.desktop net.local.justday-no.desktop; do
    unregister "$id"
    kwriteconfig6 --file kglobalshortcutsrc --group services --group "$id" --key _launch --delete
    rm -f "$APPS/$id"
  done
  [[ -n "$MOUSE" ]] && kwriteconfig6 --file kcminputrc --group ButtonRebinds --group Mouse --key "$MOUSE" --delete --notify
  kbuildsycoca6 >/dev/null 2>&1
  echo "JustDay shortcuts removed"
  exit 0
fi

if [[ -n "$EXTRA" ]]; then
  register net.local.justday.desktop "JustDay: говорить" "$HOME/.local/bin/justday toggle" "$TALK" "$EXTRA"
else
  register net.local.justday.desktop "JustDay: говорить" "$HOME/.local/bin/justday toggle" "$TALK"
fi
register net.local.justday-stop.desktop "JustDay: отмена" "$HOME/.local/bin/justday stop" "$CANCEL"
optional() {  # $1 desktop id, $2 name, $3 command, $4 key ("" = remove)
  if [[ -n "$4" ]]; then
    register "$1" "$2" "$3" "$4"
  else
    unregister "$1"
    kwriteconfig6 --file kglobalshortcutsrc --group services --group "$1" --key _launch --delete
    rm -f "$APPS/$1"
  fi
}
optional net.local.justday-type.desktop "JustDay: написать" "$HOME/.local/bin/justday compose" "$TYPE"
optional net.local.justday-yes.desktop "JustDay: да / разрешить" "$HOME/.local/bin/justday approve" "$YES"
optional net.local.justday-no.desktop "JustDay: нет / отклонить" "$HOME/.local/bin/justday deny" "$NO"
kbuildsycoca6 >/dev/null 2>&1

if [[ -n "$MOUSE" ]]; then
  kwriteconfig6 --file kcminputrc --group ButtonRebinds --group Mouse --key "$MOUSE" --notify "Key,$TALK"
  echo "mouse $MOUSE → $TALK"
fi
