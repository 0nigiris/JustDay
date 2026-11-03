#!/usr/bin/env bash
# Текстовый Джарвис для машин без острова и без микрофона (X11, школьный ПК, issue 5): окно ввода,
# ответ окном. Ходит через `justday ask --silent`, то есть к тому же демону и той же памяти.
q=""
if command -v kdialog >/dev/null; then
  q=$(kdialog --title "JustDay" --inputbox "Что сделать?" "") || exit 0
elif command -v zenity >/dev/null; then
  q=$(zenity --entry --title "JustDay" --text "Что сделать?") || exit 0
else
  notify-send -a JustDay JustDay "Нет kdialog и zenity: окно ввода открыть нечем" 2>/dev/null; exit 1
fi
[[ -z "$q" ]] && exit 0
notify-send -a JustDay JustDay "Думаю…" -t 3000 2>/dev/null
ans=$(timeout 300 "$HOME/.local/bin/justday" ask --silent "$q" 2>&1)
[[ -z "$ans" ]] && ans="(сделано, без ответа)"
if command -v kdialog >/dev/null; then kdialog --title "JustDay" --msgbox "$ans"
else zenity --info --title "JustDay" --text "$ans" --width 480; fi
