#!/usr/bin/env bash
# Снимок вида островка в PNG без экрана: offscreen Quickshell, ничего не показывается и не трогается.
#
#   scripts/shot.sh SettingsView out.png [ШxВ] ['{"page":"cycle"}'] [ждать_мс] ['JS до загрузки']
#   scripts/shot.sh ToolsView t.png 860x560 '{}' 3500 'JD.openTools("emoji")'
#
# Зачем: в ПЕРЕДАЧЕ копились «глазами не смотрел» — сеанс заперт или человек смотрит кино, а снимок
# экрана его бы потревожил. Отрисовка вне экрана даёт ту же картинку, что живой движок, и её можно
# прочитать глазами модели. Данные — от живого демона (JD подключается к сокету сам), фон — цвет
# карточки островка, потому что сами виды прозрачные и без него белый текст на белом не виден.
#
# Чего на снимке нет: значков с цветом (tint не JD.text1). Их красит MultiEffect, а вне экрана Qt
# рисует программно (backend software), без шейдеров; принудительный RHI вне экрана виснет. Пустое
# место слева от подписи на снимке — это они, а не беда.
set -euo pipefail

view=${1:?вид, например SettingsView}
out=$(realpath -m "${2:-/tmp/justday-shot.png}")
size=${3:-940x640}
props=${4:-"{}"}
wait=${5:-3000}
prep=${6:-}

root=$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
# Копия, а не сам каталог: shot.qml не должен попасть рядом с живыми файлами, которые читает служба.
cp -r "$root/island" "$work/island"
rm -rf "$work/island/icons" "$work/island/i18n"
ln -s "$root/island/icons" "$work/island/icons"
ln -s "$root/island/i18n" "$work/island/i18n"

cat > "$work/island/shot.qml" <<EOF
import QtQuick
import Quickshell

ShellRoot {
    FloatingWindow {
        implicitWidth: ${size%x*}
        implicitHeight: ${size#*x}
        color: "transparent"
        Item {
            id: host
            anchors.fill: parent
            Rectangle { anchors.fill: parent; color: JD.ink; radius: 30 }
            Loader { anchors.fill: parent; Component.onCompleted: { $prep; setSource("$view.qml", $props) } }
        }
        Timer { interval: $wait; running: true; onTriggered: host.grabToImage(function (r) {
            r.saveToFile("$out"); console.warn("SHOT ok"); Qt.exit(0) }) }
    }
}
EOF

# Тема KDE — явно: вне экрана Qt её сам не грузит, и значки программ (док, лоток) выходят
# пурпурными клетками «нет значка».
log=$(QT_QPA_PLATFORM=offscreen QT_QPA_PLATFORMTHEME=${QT_QPA_PLATFORMTHEME:-kde} timeout 90 quickshell -p "$work/island/shot.qml" 2>&1 || true)
if ! grep -q "SHOT ok" <<<"$log"; then
    echo "$log" | tail -20 >&2
    exit 1
fi
grep -E "ReferenceError|TypeError|is not defined" <<<"$log" | head -5 >&2 || true
echo "$out"
