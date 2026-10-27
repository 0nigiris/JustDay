#!/usr/bin/env bash
# Проверка компьютера до установки: что у JustDay заработает здесь, а что нет. Ничего не ставит и не меняет.
# Нужна затем, что на школьном ПК (Ubuntu, X11, Qt5, без sudo) полная оболочка не запустится, и лучше узнать
# об этом за секунду, а не после получаса установки.
ok()   { printf '  \e[32m✓\e[0m %s\n' "$1"; }
warn() { printf '  \e[33m!\e[0m %s\n' "$1"; }
bad()  { printf '  \e[31m✗\e[0m %s\n' "$1"; }

printf '\nПроверка компьютера\n\n'
full=1
. /etc/os-release 2>/dev/null && ok "Система: ${PRETTY_NAME:-${ID:-?}}"

if python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
  ok "Python $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
else
  warn "Python 3.11 нет: JustDay поставит свой в домашнюю папку (через uv), sudo не нужен"
fi

case "${XDG_SESSION_TYPE:-}" in
  wayland) ok "Сеанс: Wayland" ;;
  *) bad "Сеанс: ${XDG_SESSION_TYPE:-неизвестно} (оболочка острова работает на Wayland)"; full=0 ;;
esac
if command -v qs >/dev/null || command -v quickshell >/dev/null; then ok "Quickshell есть"
else warn "Quickshell нет"; full=0; fi
if command -v qmake6 >/dev/null || [[ -d /usr/lib64/qt6 || -d /usr/lib/qt6 || -d /usr/lib/x86_64-linux-gnu/qt6 ]]; then ok "Qt 6 есть"
else warn "Qt 6 нет"; full=0; fi

if sudo -n true 2>/dev/null; then ok "Права администратора есть"
else warn "Прав администратора нет: всё ставится в домашнюю папку, системные пакеты пропускаются"; fi

mem=$(awk '/MemTotal/ {print int($2/1048576)}' /proc/meminfo)
((mem >= 4)) && ok "Память: ${mem} ГБ" || warn "Памяти ${mem} ГБ: тяжёлые голосовые модели не потянет"
free_gb=$(df -BG --output=avail "$HOME" | tail -1 | tr -dc 0-9)
((free_gb >= 5)) && ok "Места в домашней папке: ${free_gb} ГБ" || warn "Места ${free_gb} ГБ: нужно хотя бы 5"

command -v pw-record >/dev/null || command -v arecord >/dev/null && ok "Микрофон: есть чем записывать" || warn "Нет pw-record/arecord: голос в микрофон недоступен"
command -v secret-tool >/dev/null && ok "Связка ключей есть" || warn "secret-tool нет: ключи лягут в файл ~/.config/justday/secrets.env (права 0600)"
[[ $(curl -s -m 5 -o /dev/null -w "%{http_code}" https://api.anthropic.com 2>/dev/null) != 000 ]] && ok "Интернет до нейросети доходит" || warn "api.anthropic.com не отвечает: блокировка или нет сети"

printf '\n'
if ((full)); then printf 'Итог: заработает полностью — остров, док, голос.\n\n'
else printf 'Итог: остров здесь не запустится. Заработает Джарвис в терминале (`justday terminal`) и голос; без sudo, в домашней папке.\n\n'; fi
