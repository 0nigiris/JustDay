#!/usr/bin/env bash
# Снимок экрана. Устанавливается в ~/.local/share/remo32/scripts/.
#
# Действия вида shell_script специально требуют файл на диске: логику пишет
# пользователь, а API умеет только назвать уже существующий скрипт.
set -euo pipefail

out_dir="${REMO32_SCREENSHOT_DIR:-$HOME/Pictures}"
mkdir -p "$out_dir"
out="$out_dir/remo32-$(date +%Y%m%d-%H%M%S).png"

if [[ "${XDG_SESSION_TYPE:-}" == "wayland" ]] && command -v grim >/dev/null; then
    grim "$out"
elif command -v spectacle >/dev/null; then
    spectacle -b -n -o "$out"
elif command -v import >/dev/null; then
    import -window root "$out"
else
    echo "не найдено ни одной утилиты снимка экрана (grim, spectacle, import)" >&2
    exit 1
fi

echo "$out"
