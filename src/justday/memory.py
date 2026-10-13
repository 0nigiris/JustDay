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

import difflib
import os
import time

from . import config

INDEX = "MEMORY.md"
LONG = "ДОЛГАЯ.md"  # указатель долгой памяти: лежит рядом, но сам в разговор не читается
# Сколько дней запись о текущем деле держится в оперативной. Его слова: оперативная — «то, что нужно
# прямо сейчас, в пределах недели»; две недели — запас на дело, которое просто стояло на паузе.
HOT_DAYS = 14
# Переезжают только записи о делах и ссылки: они стареют. Его предпочтения и поправки («не говорить
# брат») нужны в каждом разговоре, сколько бы их ни трогали, — они остаются горячими всегда.
AGING = {"project", "reference"}
LONG_LINK = f"- [Долгая память]({LONG}) — старые дела и рецепты; загляни, если разговор о прошлом или что-то сломалось снова"
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
        if not name.endswith(".md") or name in (INDEX, LONG):
            continue
        path = base / name
        try:
            st = path.stat()
        except OSError:
            continue
        out.append({"name": name, "bytes": st.st_size,
                    "days": round((now - st.st_mtime) / 86400, 1)})
    return out


def state(warn_lines: int = BUSY_LINES) -> dict:
    """Насколько память разрослась и чем давно не пользовались. Порог — из настроек, 0 — не предупреждать."""
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
        "busy": bool(warn_lines) and len(lines) >= warn_lines,
        "warn_lines": warn_lines,
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


def _kind(path) -> str:
    import re

    try:
        head = path.read_text(encoding="utf-8")[:600]
    except OSError:
        return ""
    m = re.search(r"^\s*type:\s*(\w+)", head, re.M)
    return m.group(1) if m else ""


def tidy(now: float | None = None) -> dict:
    """Свести память: остывшие дела — из оперативной в долгую, тронутые снова — обратно.

    Ничего не удаляется: строка указателя переезжает между MEMORY.md и ДОЛГАЯ.md, файл записи на месте.
    ponytail: «давность» — время последней правки, не чтения; atime не годится, его сбивает экран
    памяти в настройках (он читает все записи разом). Дело, которое только читают, уедет в долгую — и
    вернётся, как только мозг его поправит.
    """
    import re

    now = time.time() if now is None else now
    base = folder()
    hot_path, long_path = base / INDEX, base / LONG
    if not hot_path.exists():
        return {"moved_out": [], "moved_in": []}
    hot = hot_path.read_text(encoding="utf-8").splitlines()
    cold = long_path.read_text(encoding="utf-8").splitlines() if long_path.exists() else []

    def cooled(line: str) -> bool | None:
        """True — остыла, False — горячая, None — не запись (заголовок, ссылка на долгую, нет файла)."""
        m = re.match(r"\s*-\s*\[.*?\]\(([^)/]+\.md)\)", line)
        if not m or m.group(1) in (INDEX, LONG):
            return None
        path = base / m.group(1)
        try:
            age = (now - path.stat().st_mtime) / 86400
        except OSError:
            return None
        return _kind(path) in AGING and age >= HOT_DAYS

    out = [ln for ln in hot if cooled(ln)]
    back = [ln for ln in cold if cooled(ln) is False]
    if not out and not back:
        return {"moved_out": [], "moved_in": []}
    hot = [ln for ln in hot if ln not in out and ln != LONG_LINK] + back
    cold = [ln for ln in cold if ln not in back] + out
    if any(cooled(ln) for ln in cold):
        hot.append(LONG_LINK)
    for path, lines in ((long_path, cold), (hot_path, hot)):
        tmp = path.with_suffix(".tmp")
        tmp.write_text("\n".join(lines).strip("\n") + "\n", encoding="utf-8")
        os.replace(tmp, path)
    return {"moved_out": out, "moved_in": back}


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


# ─────────────── deduplication ───────────────
#
# Находит похожие записи в памяти (по заголовку и описанию) и предлагает их объединить.
# Пункт 17.9: «чистка дублей».


def _title(path) -> str:
    """Извлечь заголовок из memory note (metadata.name)."""
    try:
        head = path.read_text(encoding="utf-8")[:500]
    except OSError:
        return ""
    import re
    m = re.search(r"^\s*name:\s*(.+)", head, re.M)
    return m.group(1).strip() if m else ""


def _description(path) -> str:
    """Извлечь описание из memory note (metadata.description)."""
    try:
        head = path.read_text(encoding="utf-8")[:500]
    except OSError:
        return ""
    import re
    m = re.search(r"^\s*description:\s*(.+)", head, re.M)
    return m.group(1).strip() if m else ""


def find_duplicates(threshold: float = 0.85) -> list[dict]:
    """Найти пары похожих записей в памяти.

    Сравнивает заголовки и описания через difflib.SequenceMatcher.
    Возвращает список пар с коэффициентом схожести.
    """
    base = folder()
    items = []
    try:
        for name in os.listdir(base):
            if not name.endswith(".md") or name in (INDEX, LONG):
                continue
            path = base / name
            title = _title(path)
            desc = _description(path)
            if title:
                items.append({"file": name, "path": path, "title": title, "desc": desc})
    except OSError:
        return []

    dupes = []
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            # Сравниваем заголовки
            title_ratio = difflib.SequenceMatcher(None, a["title"].lower(), b["title"].lower()).ratio()
            # Сравниваем описания, если есть
            desc_ratio = 0.0
            if a["desc"] and b["desc"]:
                desc_ratio = difflib.SequenceMatcher(None, a["desc"].lower(), b["desc"].lower()).ratio()
            # Берём максимум
            ratio = max(title_ratio, desc_ratio)
            if ratio >= threshold:
                dupes.append({
                    "file_a": a["file"],
                    "file_b": b["file"],
                    "title_a": a["title"],
                    "title_b": b["title"],
                    "similarity": round(ratio, 3),
                    "reason": "title" if title_ratio >= desc_ratio else "description",
                })
    # Сортируем по убыванию схожести
    dupes.sort(key=lambda x: -x["similarity"])
    return dupes


def deduplicate_report(threshold: float = 0.85) -> str:
    """Текстовый отчёт о дубликатах для показа человеку."""
    dupes = find_duplicates(threshold)
    if not dupes:
        return f"Дубликатов не найдено (порог схожести {threshold:.0%})."
    lines = [f"Найдено {len(dupes)} пар похожих записей (порог {threshold:.0%}):"]
    for d in dupes[:15]:  # ограничиваем вывод
        lines.append("  {:.0%} [{}]  {}  ↔  {}".format(
            d["similarity"], d["reason"], d["title_a"][:50], d["title_b"][:50]))
    if len(dupes) > 15:
        lines.append(f"  ... и ещё {len(dupes) - 15} пар")
    lines.append("\nДля объединения: `justday memory merge ФАЙЛ1 ФАЙЛ2`")
    return "\n".join(lines)
