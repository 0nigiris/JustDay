#!/usr/bin/env bash
# Глобальные сочетания клавиш KDE Plasma для JustDay.
#
# Все клавиши описаны одной таблицей ниже: имя, подпись, команда, значение по умолчанию. Добавить
# ещё одну — одна строка здесь и одна в src/justday/manage.py. Раньше каждая клавиша была прописана
# в четырёх местах, и пятая по счёту забывалась ровно в одном из них.
#
#   setup-hotkey.sh [--talk "Meta+J"] [--extra F19] [--cancel "Meta+Shift+J"] [--type Meta+K]
#                   [--yes Meta+Y] [--no Meta+N] [--apps "Alt+Space"] [--clip "Meta+V"]
#                   [--emoji "Meta+."] [--load ""] [--mouse ExtraButton1] [--remove]
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
  "apps|поиск программ|tools apps|Alt+Space"
  "clip|буфер обмена|tools clip|Meta+V"
  "emoji|эмодзи|tools emoji|Meta+."
  "load|нагрузка машины|tools load|"
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

register() {  # $1 desktop id, $2 подпись, $3 команда, $4.. клавиши
  local id="$1" name="$2" cmd="$3"; shift 3
  local keys_csv keys_tab
  keys_csv=$(IFS=,; echo "$*"); keys_tab=$(printf '%s\t' "$@"); keys_tab="${keys_tab%$'\t'}"
  cat > "$APPS/$id" <<EOF
[Desktop Entry]
Type=Application
Name=JustDay: $name
Exec=$cmd
Icon=audio-input-microphone
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
  { [[ -n "$MOUSE" ]] && "$KWRITE" --file kcminputrc --group ButtonRebinds --group Mouse --key "$MOUSE" --delete --notify; } || true
  { [[ -n "$KBUILD" ]] && "$KBUILD" >/dev/null 2>&1; } || true
  echo "сочетания JustDay убраны"
  exit 0
fi

for row in "${KEYS[@]}"; do
  IFS='|' read -r name label cmd _ <<<"$row"
  id="$(id_of "$name")"
  keys=("${KEY[$name]}")
  # У «говорить» бывает вторая клавиша: кнопка мыши, перенастроенная на F19.
  [[ "$name" == talk && -n "$EXTRA" ]] && keys+=("$EXTRA")
  if [[ -n "${KEY[$name]}" ]]; then
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
