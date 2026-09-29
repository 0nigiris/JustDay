#!/usr/bin/env bash
# Generates the initial CLAUDE.md profile for JustDay's workspace from facts detected on this machine.
set -uo pipefail
os=$(. /etc/os-release && echo "$PRETTY_NAME")
plasma=$(plasmashell --version 2>/dev/null | awk '{print $2}')
gpu=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1)
browser=$(xdg-settings get default-web-browser 2>/dev/null)
term=$(command -v kitty >/dev/null && echo kitty || echo konsole)
steam=$( { command -v steam >/dev/null && echo "native (/usr/bin/steam)"; flatpak info com.valvesoftware.Steam >/dev/null 2>&1 && echo "flatpak com.valvesoftware.Steam"; } | paste -sd ";" )
flatpaks=$(flatpak list --app --columns=application 2>/dev/null | tr '\n' ' ')
repos=$(find "$HOME" -maxdepth 2 -name .git -type d 2>/dev/null | sed "s|/.git$||; s|^$HOME|~|" | sort | tr '\n' ' ')
cat <<EOF
# Профиль пользователя и машины (JustDay)

Этот файл — долговременный контекст JustDay. Редактируй свободно; JustDay тоже может его дополнять.
Секреты (пароли, токены, ключи) сюда не пишем.

## Пользователь
- Имя: (не указано)
- Язык общения: русский
- Предпочтения: максимум автономии, минимум вопросов; короткие голосовые ответы.

## Машина
- ОС: $os, KDE Plasma ${plasma:-?}, сессия ${XDG_SESSION_TYPE:-?}
- GPU: ${gpu:-нет NVIDIA}
- Браузер по умолчанию: ${browser:-?}
- Терминал: $term
- Steam: ${steam:-не найден}
- Flatpak-приложения: $flatpaks

## Проекты (git-репозитории в домашней папке на момент установки)
$repos

## Полезные места
- Логи и журнал JustDay: ~/.local/state/justday/
- Конфиг JustDay: ~/.config/justday/config.toml
$(if [[ "${XDG_SESSION_TYPE:-}" != wayland || "${XDG_CURRENT_DESKTOP:-}" != *KDE* ]]; then cat <<'X11'

## Этот стол — не KDE 6 на Wayland
- Инструмента kwin (`look`, клики по разметке окна) здесь нет.
- Окна: `wmctrl -l -x` (список), `wmctrl -i -a ID` (переключиться), `wmctrl -i -c ID` (закрыть).
- Щёлкнуть и нажать: `justday click X Y` (`--button 3`, `--double`), `justday keys ctrl+s`. Напрямую то же — `xdotool mousemove X Y click 1`, `xdotool type "текст"`.
- Экран: `justday screenshot` (сам выберет spectacle / gnome-screenshot / maim / scrot) и потом Read по пути.
- Выделённый текст: `xclip -o -selection primary`.
X11
fi)
EOF
