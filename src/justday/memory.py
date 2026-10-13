"""Память ассистента: сколько её, что в ней давно не пригождалось и когда пора прибраться.

Память у Claude Code устроена двухслойно, и это удачно совпало с тем, как её хочет видеть человек.
Указатель (MEMORY.md) читается **каждый разговор** — он и есть «оперативная память», и каждая его
строка стоит токенов всегда, даже когда речь совсем о другом. Сами записи лежат рядом файлами и
читаются только тогда, когда разговор их коснулся, — это «долгая память», и она может быть сколь
угодно большой почти бесплатно.

Отсюда всё остальное. Разрастаться опасно не памяти вообще, а **указателю**: сто строк в нём — это
сто строк в начале каждого разговора. Поэтому следим за ним отдельно и первым.

Чего здесь нет: удаления. Решение забыть принимает человек, а наше дело — вовремя показать ему, что
накопилось и чем он не пользовался с лета.
"""
from __future__ import annotations

import os
import time

from . import config

INDEX = "MEMORY.md"
# Сколько строк указателя — уже много. Взято не с потолка: строка указателя это примерно 20 токенов,
# и сорок строк — около восьмисот токенов в начале **каждого** разговора.
BUSY_LINES = 40
STALE_DAYS = 60


def folder():
    """Где лежит память мозга. Claude Code делает имя папки из пути, заменяя всё лишнее на дефис."""
    import re

    brain = config.DATA_DIR / "brain"
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(brain))
    return config.HOME / ".claude/projects" / slug / "memory"


def entries() -> list[dict]:
    """Каждая запись: имя, размер, когда её трогали в последний раз."""
    out = []
    base = folder()
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return out
    now = time.time()
    for name in names:
        if not name.endswith(".md") or name == INDEX:
            continue
        path = base / name
        try:
            st = path.stat()
        except OSError:
            continue
        out.append({"name": name, "bytes": st.st_size,
                    "days": round((now - st.st_mtime) / 86400, 1)})
    return out


def state() -> dict:
    """Насколько память разрослась и чем давно не пользовались."""
    base = folder()
    items = entries()
    try:
        index = (base / INDEX).read_text(encoding="utf-8")
    except OSError:
        index = ""
    lines = [ln for ln in index.splitlines() if ln.strip().startswith("-")]
    stale = sorted((i for i in items if i["days"] >= STALE_DAYS), key=lambda i: -i["days"])
    return {
        "ok": base.exists(),
        "path": str(base),
        "count": len(items),
        "bytes": sum(i["bytes"] for i in items),
        # Строки указателя — главное число: они читаются в каждом разговоре.
        "index_lines": len(lines),
        "busy": len(lines) >= BUSY_LINES,
        "stale": stale[:12],
        "stale_count": len(stale),
    }


def summary(st: dict | None = None) -> str:
    """Одной фразой, как сказал бы сам ассистент."""
    st = st or state()
    if not st["ok"]:
        return "Памяти пока нет."
    kb = st["bytes"] // 1024
    line = f"В памяти {st['count']} записей на {kb} КБ, в указателе {st['index_lines']} строк."
    if st["stale_count"]:
        line += f" {st['stale_count']} не пригождались больше двух месяцев."
    if st["busy"]:
        line += " Указатель читается в каждом разговоре — его стоит проредить."
    return line


# ─────────────── «раз и навсегда»: жёсткие предпочтения ───────────────
#
# Беда: человек сказал «Temporarily — запомни раз и навсегда» (он про одну песню), а в следующий раз
# включился Эминем. Запись в обычной памяти — подсказка модели, и поиск её перебивает. Жёсткая запись
# лежит отдельно и применяется ДО поиска, кодом: слово → ровно этот запрос.
PINS = config.DATA_DIR / "pins.json"


def _key(phrase: str) -> str:
    return " ".join(phrase.lower().replace("ё", "е").split())


def pins() -> dict:
    import json

    try:
        return json.loads(PINS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def pin(phrase: str, target: str) -> None:
    import json

    data = pins()
    data[_key(phrase)] = target.strip()
    PINS.parent.mkdir(parents=True, exist_ok=True)
    PINS.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def unpin(phrase: str) -> bool:
    import json

    data = pins()
    if data.pop(_key(phrase), None) is None:
        return False
    PINS.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def resolve(query: str) -> str:
    """Запрос целиком совпал с закреплённым словом → закреплённый запрос; иначе без изменений."""
    return pins().get(_key(query), query)
