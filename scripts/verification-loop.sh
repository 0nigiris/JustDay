#!/usr/bin/env bash
# Быстрая проверка после каждой правки файла (хук PostToolUse). Полный pytest здесь не гоняем: 12 секунд
# на каждую правку — это минуты зря за сессию (Р-72). Он идёт один раз, когда работа закончена:
# `scripts/stop-check.sh` (хук Stop).
set -u
cd "${CLAUDE_PROJECT_DIR:-$PWD}" || exit 2

file=$(python -c 'import json,sys; print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))') || exit 2
case "$file" in
    "$PWD"/*) file=${file#"$PWD"/} ;;
esac
failed=0

case "$file" in
    *.py) ruff check "$file" || failed=1 ;;
    *.qml) scripts/qmllint-ratchet.sh "$file" || failed=1 ;;
    *.sh) bash -n "$file" || failed=1 ;;
esac

if (( failed )); then
    printf 'Проверка после правки не прошла; исправь ошибки, показанные выше.\n' >&2
    exit 2
fi
