#!/usr/bin/env bash
# Передвинуть ветку stable на проверенный коммит (по умолчанию — на текущий HEAD).
# Звать только после того, как человек сам посидел и убедился, что всё работает: именно stable
# получают те, кто обновляется командой `justday update`. main — рабочая, в ней бывает сломано.
set -euo pipefail
cd "$(dirname "$0")/.."
sha="${1:-HEAD}"
ruff check . >/dev/null
.venv/bin/python -m pytest -q >/dev/null
git push origin "$(git rev-parse "$sha"):refs/heads/stable"
echo "stable → $(git rev-parse --short "$sha")"
