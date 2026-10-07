#!/usr/bin/env bash
# Глобальные сочетания клавиш KDE Plasma для JustDay.
#
# Все клавиши описаны одной таблицей ниже: имя, подпись, команда, значение по умолчанию. Добавить
# ещё одну — одна строка здесь и одна в src/justday/manage.py. Раньше каждая клавиша была прописана
# в четырёх местах, и пятая по счёту забывалась ровно в одном из них.
#
#   setup-hotkey.sh [--talk "Meta+J"] [--extra F19] [--cancel "Meta+Shift+J"] [--type Meta+K]
#                   [--yes Meta+Y] [--no Meta+N] [--apps "Alt+Space"] [--clip "Meta+V"]
#                   [--emoji "Meta+."] [--load ""] [--menu Meta] [--pin Meta+P] [--dock1 Meta+1] … [--dock9 Meta+9] [--mouse ExtraButton1] [--remove]
# Пустое значение — не регистрировать вовсе.
#
# kglobalacceld включает командные сочетания только для «служебных» составляющих, а те создаются из
# desktop-файлов с X-KDE-Shortcuts (через кэш KSycoca). Простой doRegister() по D-Bus даёт действие,
# которое не реагирует на нажатия, — отсюда desktop-файлы и kbuildsycoca6.
set -euo pipefail

# имя|подпись|команда|по умолчанию
KEYS=(
  "talk|говорить|toggle|Meta+J"
  "cancel|отмена|stop|Meta+Shift+J"
  "type|написать|compose|Meta+K"
  "yes|да / разрешить|approve|Meta+Y"
  "no|нет / отклонить|deny|Meta+N"
  "apps|Spotlight / поиск|tools apps|Alt+Space"
  "clip|буфер обмена|tools clip|Meta+V"
  "emoji|эмодзи|tools emoji|Meta+."
  "load|нагрузка машины|tools load|"
  "chat|чат с ассистентом|chat|"
  "menu|меню приложений|menu|Meta"
  "pin|закрепить в доке|dock pin|Meta+P"
  "closewin|закрыть окно|windows close-active|Meta+Q"
  "dock1|док слот 1|dock go 1|Meta+1"
  "dock2|док слот 2|dock go 2|Meta+2"
  "dock3|док слот 3|dock go 3|Meta+3"
  "dock4|док слот 4|dock go 4|Meta+4"
  "dock5|док слот 5|dock go 5|Meta+5"
  "dock6|док слот 6|dock go 6|Meta+6"
  "dock7|док слот 7|dock go 7|Meta+7"
  "dock8|док слот 8|dock go 8|Meta+8"
  "dock9|док слот 9|dock go 9|Meta+9"
)

declare -A KEY
for row in "${KEYS[@]}"; do
  IFS='|' read -r name _ _ def <<<"$row"
  KEY[$name]="$def"
done
EXTRA="F19"      # вторая клавиша «говорить»: например то, что шлёт кнопка мыши ("" — нет)
MOUSE=""
REMOVE=0

while (($#)); do
  case "$1" in
    --extra) EXTRA="$2"; shift ;;
    --mouse) MOUSE="$2"; shift ;;
    --remove) REMOVE=1 ;;
    --*)
      name="${1#--}"
      if [[ -v KEY[$name] ]]; then KEY[$name]="$2"; shift
      else echo "неизвестный ключ: $1" >&2; exit 2; fi ;;
    *) KEY[talk]="$1" ;;   # для совместимости: первый позиционный — клавиша «говорить»
  esac
  shift
done

APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"

# Plasma 6 или Plasma 5 — файлы и ключи те же, разные только имена утилит
KWRITE=$(command -v kwriteconfig6 || command -v kwriteconfig5 || true)
KBUILD=$(command -v kbuildsycoca6 || command -v kbuildsycoca5 || true)
QDBUS=$(command -v qdbus-qt6 || command -v qdbus6 || command -v qdbus || command -v qdbus-qt5 || true)
if [[ -z "$KWRITE" ]]; then
  echo "нужен kwriteconfig6 или kwriteconfig5 (KDE Plasma)" >&2
  exit 1
fi

id_of() { [[ "$1" == talk ]] && echo "net.local.justday.desktop" || echo "net.local.justday-$1.desktop"; }

# Имена, под которыми клавиши жили раньше: их файлы нужно убрать, иначе две составляющие спорят за
# одно сочетание и выигрывает старая.
LEGACY=(net.local.justday-stop.desktop net.local.justday-overlay.desktop)

SHORTCUTS="${XDG_CONFIG_HOME:-$HOME/.config}/kglobalshortcutsrc"

# Отобрать клавишу у того, кто её уже занял.
#
# Без этого привязка молча не работает: `Meta+V` в KDE занят «показать буфер обмена у курсора», и
# наша запись в файле есть, а нажатие уходит Klipper'у. Файл править бесполезно — сочетание держит
# живая служба, поэтому просим её отдать через ту же шину, на которой она его и получила.
# Прежнее значение остаётся в файле вторым полем, так что «По умолчанию» в системных настройках
# вернёт его на место.
free_key() {  # $1 — сочетание, $2 — наш desktop id (его не трогаем)
  local key="$1" mine="$2"
  [[ -z "$key" || ! -f "$SHORTCUTS" ]] && return 0
  awk -v key="$key" -v mine="$mine" '
    /^\[/ { line = $0; gsub(/^\[|\]$/, "", line); gsub(/\]\[/, "|", line); group = line; next }
    /=/ {
      eq = index($0, "=");  action = substr($0, 1, eq - 1);  rest = substr($0, eq + 1)
      split(rest, f, ",");  current = f[1]
      if (group ~ mine) next
      n = split(current, alts, "\t")
      for (i = 1; i <= n; i++) if (alts[i] == key) { print group "|" action "|" f[3]; next }
    }' "$SHORTCUTS" | while IFS='|' read -r group action friendly; do
    # Составляющая — первая часть группы: «plasmashell» или «services|net.local.x.desktop».
    local component="${group%%|*}"
    [[ "$component" == services ]] && component="${group#*|}"
    gdbus call --session --dest org.kde.kglobalaccel --object-path /kglobalaccel \
      --method org.kde.KGlobalAccel.setShortcut \
      "['$component','$action','$component','${friendly//\'/}']" "@ai []" 4 >/dev/null 2>&1 || true
    echo "  освободил $key: было у «${friendly:-$component/$action}»"
  done
}

unregister() {  # $1 desktop id
  gdbus call --session --dest org.kde.kglobalaccel --object-path /kglobalaccel \
    --method org.kde.KGlobalAccel.unregister "$1" "_launch" >/dev/null 2>&1 || true
  [[ -n "$QDBUS" ]] && "$QDBUS" org.kde.kglobalaccel "/component/${1//[.-]/_}" org.kde.kglobalaccel.Component.cleanUp >/dev/null 2>&1 || true
}

forget() {  # $1 desktop id — убрать и сочетание, и сам файл
  unregister "$1"
  "$KWRITE" --file kglobalshortcutsrc --group services --group "$1" --key _launch --delete
  rm -f "${APPS:?}/${1:?}"
}

# Свой значок в тему оформления. Без него все наши ярлыки показывались чужим микрофоном —
# и в меню, и в настройках сочетаний, и в переключателе окон.
icon() {
  local here src dst
  here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
  src="$here/brand/justday-icon.svg"
  dst="$HOME/.local/share/icons/hicolor/scalable/apps"
  [[ -f "$src" ]] || return 0
  mkdir -p "$dst" && cp -f "$src" "$dst/justday.svg"
  command -v gtk-update-icon-cache >/dev/null && \
    gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
}

register() {  # $1 desktop id, $2 подпись, $3 команда, $4.. клавиши
  local id="$1" name="$2" cmd="$3"; shift 3
  local keys_csv keys_tab
  keys_csv=$(IFS=,; echo "$*"); keys_tab=$(printf '%s\t' "$@"); keys_tab="${keys_tab%$'\t'}"
  cat > "$APPS/$id" <<EOF
[Desktop Entry]
Type=Application
Name=JustDay: $name
Exec=$cmd
Icon=justday
NoDisplay=true
X-KDE-GlobalAccel-CommandShortcut=true
X-KDE-Shortcuts=$keys_csv
EOF
  unregister "$id"
  "$KWRITE" --file kglobalshortcutsrc --group services --group "$id" --key _launch "$keys_tab"
  echo "сочетание ${keys_csv} → $cmd"
}

if ((REMOVE)); then
  for row in "${KEYS[@]}"; do
    IFS='|' read -r name _ _ _ <<<"$row"
    forget "$(id_of "$name")"
  done
  icon

for old_id in "${LEGACY[@]}"; do forget "$old_id"; done
  { [[ -n "$MOUSE" ]] && "$KWRITE" --file kcminputrc --group ButtonRebinds --group Mouse --key "$MOUSE" --delete --notify; } || true
  { [[ -n "$KBUILD" ]] && "$KBUILD" >/dev/null 2>&1; } || true
  echo "сочетания JustDay убраны"
  exit 0
fi

for old_id in "${LEGACY[@]}"; do forget "$old_id"; done

for row in "${KEYS[@]}"; do
  IFS='|' read -r name label cmd _ <<<"$row"
  id="$(id_of "$name")"
  keys=("${KEY[$name]}")
  # У «говорить» бывает вторая клавиша: кнопка мыши, перенастроенная на F19.
  [[ "$name" == talk && -n "$EXTRA" ]] && keys+=("$EXTRA")
  if [[ -n "${KEY[$name]}" ]]; then
    for k in "${keys[@]}"; do free_key "$k" "$id"; done
    register "$id" "$label" "$HOME/.local/bin/justday $cmd" "${keys[@]}"
  else
    forget "$id"
  fi
done
{ [[ -n "$KBUILD" ]] && "$KBUILD" >/dev/null 2>&1; } || true

if [[ -n "$MOUSE" ]]; then
  "$KWRITE" --file kcminputrc --group ButtonRebinds --group Mouse --key "$MOUSE" --notify "Key,${KEY[talk]}"
  echo "мышь $MOUSE → ${KEY[talk]}"
fi
