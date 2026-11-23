#!/usr/bin/env bash
# Видео вида островка без экрана: offscreen Quickshell, кадры через grabToImage с отметкой времени.
#
#   scripts/film.sh WelcomeView out.mp4 [ШxВ] ['{"step":0}'] [длительность_мс] ['JS до загрузки'] ['[[мс,"JS"],…]']
#   scripts/film.sh WelcomeView w.mp4 560x460 '{}' 4000 '' '[[800,"v.next()"],[2200,"v.next()"]]'
#
# Зачем: склейка неподвижных снимков (shot.sh) выглядела как лагучие анимации, и по ней нельзя
# понять, есть ли переход на самом деле. Здесь каждый кадр несёт своё время, и видео собирается
# с настоящими паузами между кадрами, поэтому скорость и плавность движения — как в живом островке.
# Во втором JS вид доступен как `v`, синглтон — как `JD`.
set -euo pipefail
view=${1:?вид}; out=$(realpath -m "${2:?out.mp4}"); size=${3:-560x460}; props=${4:-"{}"}
dur=${5:-3000}; prep=${6:-}; acts=${7:-"[]"}
root=$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
cp -r "$root/island" "$work/island"; rm -rf "$work/island/icons" "$work/island/i18n"
ln -s "$root/island/icons" "$work/island/icons"; ln -s "$root/island/i18n" "$work/island/i18n"
mkdir "$work/f"
cat > "$work/island/film.qml" <<EOF
import QtQuick
import Quickshell
ShellRoot {
    FloatingWindow {
        id: win
        implicitWidth: ${size%x*}; implicitHeight: ${size#*x}; color: "transparent"
        Item {
            id: host; anchors.fill: parent
            Rectangle { anchors.fill: parent; color: JD.ink; radius: 30 }
            Loader { id: ld; anchors.fill: parent; Component.onCompleted: { $prep; setSource("$view.qml", $props) } }
        }
        property double t0: Date.now()
        property var acts: $acts
        property int ai: 0
        property bool busy: false
        Timer { interval: 16; repeat: true; running: true; onTriggered: {
            const ms = Date.now() - win.t0
            while (win.ai < win.acts.length && win.acts[win.ai][0] <= ms) { (new Function("v", "JD", win.acts[win.ai][1]))(ld.item, JD); win.ai++ }
            if (ms > $dur) { console.warn("FILM ok"); Qt.exit(0); return }
            if (win.busy) return
            win.busy = true
            host.grabToImage(function (r) { r.saveToFile("$work/f/" + String(ms).padStart(6, "0") + ".png"); win.busy = false })
        } }
    }
}
EOF
log=$(QT_QPA_PLATFORM=offscreen QT_QPA_PLATFORMTHEME=${QT_QPA_PLATFORMTHEME:-kde} timeout $((dur / 1000 + 60)) quickshell -p "$work/island/film.qml" 2>&1 || true)
grep -q "FILM ok" <<<"$log" || { echo "$log" | tail -20 >&2; exit 1; }
# Длительность каждого кадра — до следующей отметки: скорость движения остаётся настоящей.
( cd "$work/f"; prev=""; for f in $(ls | sort); do t=${f%.png}; t=$((10#$t))
    [ -n "$prev" ] && echo "duration $(awk "BEGIN{print ($t-$pt)/1000}")"; echo "file '$work/f/$f'"; prev=$f; pt=$t; done
  echo "duration 0.5"; echo "file '$work/f/$prev'" ) > "$work/list.txt"
ffmpeg -v error -y -f concat -safe 0 -i "$work/list.txt" -vf "fps=30,format=yuv420p" -c:v libx264 -movflags +faststart "$out"
echo "$out $(ls "$work/f" | wc -l) кадров за ${dur} мс"
