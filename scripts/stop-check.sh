#!/usr/bin/env bash
# Полная проверка, когда модель собралась закончить (хук Stop): ruff по всему и весь pytest.
# Упала — модель получает вывод и продолжает; `stop_hook_active` не даёт зациклиться: второй раз подряд
# не мешаем остановиться.
set -u
cd "${CLAUDE_PROJECT_DIR:-$PWD}" || exit 0

if python -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("stop_hook_active") else 1)'; then
    exit 0
fi

out=$( { ruff check . && .venv/bin/python -m pytest -q -W ignore; } 2>&1 ) || {
    printf '%s\n\nРабота не закончена: проверки не прошли.\n' "$(printf '%s' "$out" | tail -40)" >&2
    exit 2
}
