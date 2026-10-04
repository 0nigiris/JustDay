#!/usr/bin/env bash
# Повторяем тот же короткий набор проверок после каждого изменения файла.
set -u
cd "${CLAUDE_PROJECT_DIR:-$PWD}" || exit 2

file=$(python -c 'import json,sys; print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))') || exit 2
failed=0

ruff check . || failed=1
.venv/bin/python -m pytest -q || failed=1

if [[ "$file" == *.qml ]]; then
    case "$file" in
        "$PWD"/*) file=${file#"$PWD"/} ;;
    esac
    /usr/lib64/qt6/bin/qmllint -I . "$file" || failed=1
fi

if (( failed )); then
    printf 'Проверки после правки не прошли; исправь ошибки, показанные выше.\n' >&2
    exit 2
fi
