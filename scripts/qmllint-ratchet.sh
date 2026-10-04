#!/usr/bin/env bash
# qmllint «храповиком»: число предупреждений в файле может только падать (Р-72 ревизии).
#
# Почему не просто `qmllint`: на shell.qml он выдаёт ~1500 предупреждений (синглтон JD и типы Quickshell он
# не видит), и код выхода при этом 0 — то есть проверка не могла упасть, и новая опечатка тонула в старом
# шуме. Здесь для каждого файла записано, сколько предупреждений было на момент последней чистки
# (`.qmllint-baseline`); больше — ошибка, меньше — подсказка записать новое число.
#
#   scripts/qmllint-ratchet.sh island/Файл.qml ...   проверить
#   scripts/qmllint-ratchet.sh --update              пересчитать для всех island/*.qml
set -u
cd "$(dirname "$0")/.." || exit 2
LINT=${QMLLINT:-/usr/lib64/qt6/bin/qmllint}
BASE=.qmllint-baseline
[[ -x $LINT ]] || { echo "qmllint не найден ($LINT) — пропускаю" >&2; exit 0; }

count() { "$LINT" -I . "$1" 2>&1 | grep -c '^Warning'; }

if [[ ${1:-} == --update ]]; then
    for f in island/*.qml; do echo "$(count "$f") $f"; done > "$BASE"
    echo "записано: $BASE"
    exit 0
fi

failed=0
for f in "$@"; do
    [[ $f == *.qml && -f $f ]] || continue
    # Синтаксическая ошибка — код выхода ≠ 0 при любом пороге.
    if ! "$LINT" -I . -W 1000000 "$f" >/dev/null 2>&1; then
        "$LINT" -I . "$f" 2>&1 | grep -A3 '^Error' | head -20
        echo "qmllint: $f не разбирается" >&2
        failed=1
        continue
    fi
    now=$(count "$f")
    allowed=$(awk -v f="$f" '$2 == f {print $1}' "$BASE" 2>/dev/null)
    allowed=${allowed:-0}
    if (( now > allowed )); then
        echo "qmllint: $f — предупреждений $now, было $allowed. Новые смотри так: $LINT -I . $f" >&2
        failed=1
    elif (( now < allowed )); then
        echo "qmllint: $f стал чище ($allowed → $now): scripts/qmllint-ratchet.sh --update"
    fi
done
exit $failed
