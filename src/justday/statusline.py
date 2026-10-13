"""Статусная строка Claude Code: показать остаток лимита подписки и отдать его острову.

Сколько лимита осталось, Claude Code сообщает только статусной строке (`rate_limits` во входном JSON,
и только после первого ответа модели). Других источников нет: ни файла, ни команды. Поэтому строка
заодно кладёт эти числа в файл, а демон показывает их на странице сессий (Р2-39).

Запускается на каждое обновление строки, так что тут только стандартная библиотека: импорт пакета
`justday` занял бы заметную долю секунды на каждый ход.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

FILE = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "justday" / "claude-limits.json"
WINDOWS = (("five_hour", "5 ч"), ("seven_day", "неделя"))


def save(rate: dict) -> None:
    keep = {k: {"used": float(w["used_percentage"]), "resets_at": float(w.get("resets_at") or 0)}
            for k, _ in WINDOWS if isinstance(w := rate.get(k), dict) and w.get("used_percentage") is not None}
    if not keep:
        return
    keep["at"] = time.time()
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(keep), encoding="utf-8")
    os.replace(tmp, FILE)                 # остров не должен прочитать половину файла


def line(data: dict) -> str:
    model = (data.get("model") or {}).get("display_name") or ""
    rate = data.get("rate_limits") or {}
    parts = [f"{name} {round(float(w['used_percentage']))}%" for k, name in WINDOWS
             if isinstance(w := rate.get(k), dict) and w.get("used_percentage") is not None]
    return " · ".join(([model] if model else []) + parts)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    try:
        save(data.get("rate_limits") or {})
    except (OSError, TypeError, ValueError):
        pass                              # строка важнее файла: без неё Claude Code покажет ошибку
    print(line(data))


if __name__ == "__main__":
    main()
