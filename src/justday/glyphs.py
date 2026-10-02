"""Выбиралка эмодзи: поиск по-русски, недавние, вставка в то окно, где курсор.

Зачем своя. Системные выбиралки ищут по английским словам («cat», не «кот»), открываются отдельным
окном поверх всего и ничего не знают о том, что человек уже выбирал. Здесь набор лежит рядом —
``data/emoji.json``, собранный из Unicode и CLDR (см. ``scripts/make-emoji.py``), — поиск идёт по
русским названиям и словам, а порядок начинается с того, что берут чаще.

Почему в демоне, а не в островке. Поиск один и тот же нужен двоим: сетке на экране и ассистенту.
«Вставь эмодзи с котиком» и открытая руками сетка должны находить одно и то же, а для этого искать
должно одно место.

    justday emoji            # сетку показывает островок
    justday emoji кот        # первый подходящий — сразу в то окно, где курсор
    justday emoji --list кот # что нашлось, без вставки
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time

from . import config

DATA = config.REPO_DIR / "data" / "emoji.json"
RECENT_FILE = config.STATE_DIR / "emoji-recent.json"
RECENT_MAX = 48
# Пока панель островка закрывается, клавиатура принадлежит ей, а не тому окну, куда человек
# печатал. Символ, набранный раньше времени, уходит в никуда: панель уже не слушает, а окно ещё не
# слушает. 0,12 с на это не хватало — композитор возвращает фокус заметно медленнее.
PASTE_DELAY = 0.28

_SET: dict | None = None


def load() -> dict:
    """Набор целиком: {"groups": [...], "items": [{c, n, g, k, e}]}. Читается один раз."""
    global _SET
    if _SET is None:
        try:
            _SET = json.loads(DATA.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _SET = {"groups": [], "items": []}
        for i, item in enumerate(_SET["items"]):
            item["i"] = i        # канонический порядок: им же разрешаем ничьи в поиске
    return _SET


def _flat(text: str) -> str:
    """К одному виду перед сравнением: ё и е — одна буква. В CLDR «самолет» без ё, а пишут его с ё,
    и без этого «самолёт» находил сначала пилотов, а сам самолёт — пятым."""
    return text.lower().replace("ё", "е")


def _names(item: dict) -> list[str]:
    """Названия символа: русское и английское. Английское — тоже название, а не слово для поиска:
    иначе «rocket» находил бы сначала космонавта, у которого это слово в описании."""
    return [_flat(item["n"]), _flat(item.get("e", ""))]


def _words(item: dict) -> list[str]:
    return [_flat(w) for w in item.get("k", []) if w]


def _stem(word: str) -> str:
    """Огрызок слова для последней попытки. Русский склоняется, и «россия» не начало «российской»,
    а «сердце» не начало «сердечек» — зато пять первых букв у них общие. Это не морфология, а
    ровно та мелочь, без которой поиск по-русски выглядит сломанным.

    Четыре буквы, а не пять: у «сердце» и «сердечки» пятая уже расходится."""
    return word[:4]


def _score(item: dict, words: list[str]) -> int:
    """Насколько символ подходит запросу. Меньше — лучше, 99 — не подходит.

    Порядок ровно такой, каким его ждут руки: «кот» сначала даёт кошку, а не «кота в шоке» — потому
    что у 🐱 название «морда кошки», а слово «кот» стоит в описании ровно. Слова запроса должны
    найтись все: «кот сердце» — это 😻, а не кот и сердце по отдельности."""
    best = 0
    names, extra = _names(item), _words(item)
    for word in words:
        if word in names:
            hit = 0
        elif any(n.startswith(word) for n in names) or word in extra:
            hit = 1
        elif any(part.startswith(word) for n in names for part in n.split()):
            hit = 2
        elif any(word in n for n in names):
            hit = 3
        elif any(h.startswith(word) for h in extra):
            hit = 4
        elif any(word in h for h in extra):
            hit = 5
        elif len(word) >= 4 and any(_stem(h).startswith(_stem(word)) or _stem(word).startswith(_stem(h))
                                    for h in names + extra if h):
            hit = 6
        else:
            return 99
        best = max(best, hit)
    return best


def search(query: str = "", limit: int = 400, group: str = "") -> list[dict]:
    """Символы под запрос. Пустой запрос — недавние, потом весь набор по порядку."""
    items = load()["items"]
    if group:
        items = [i for i in items if i["g"] == group]
    words = [w for w in _flat(query or "").split() if w]
    if not words:
        recent = [] if group else [i for i in (by_char(c) for c in recents()) if i]
        rest = [i for i in items if i not in recent]
        return (recent + rest)[:limit]
    scored = [(s, i["i"], i) for i in items if (s := _score(i, words)) < 99]
    scored.sort(key=lambda t: (t[0], t[1]))
    return [i for _, _, i in scored[:limit]]


def by_char(ch: str) -> dict | None:
    return next((i for i in load()["items"] if i["c"] == ch), None)


# ───────────────────────────── недавние ─────────────────────────────


def recents() -> list[str]:
    try:
        got = json.loads(RECENT_FILE.read_text(encoding="utf-8"))
        return [str(c) for c in got][:RECENT_MAX] if isinstance(got, list) else []
    except (OSError, ValueError):
        return []


def remember(ch: str) -> None:
    """Взятый символ — в начало списка. Порядок «чем недавнее, тем раньше», без счётчиков: частота
    ошибается ровно там, где человек однажды перебрал десяток символов и выбрал один."""
    if not ch:
        return
    keep = [ch] + [c for c in recents() if c != ch]
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        RECENT_FILE.write_text(json.dumps(keep[:RECENT_MAX], ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def forget_all() -> None:
    RECENT_FILE.unlink(missing_ok=True)


# ───────────────────────────── вставка ─────────────────────────────


def to_clipboard(text: str) -> bool:
    """Положить в буфер обмена. Wayland — wl-copy, X11 — xclip."""
    from . import face

    cmd = (["wl-copy", "--"] if face.session() == "wayland" and shutil.which("wl-copy")
           else ["xclip", "-selection", "clipboard"] if shutil.which("xclip") else [])
    if not cmd:
        return False
    try:
        # В аргументы символ не передаём: в буфер должен лечь ровно он, без перевода строки,
        # который добавил бы echo, и без забот о том, как оболочка понимает эмодзи.
        subprocess.run(cmd, input=text.encode(), timeout=5, check=False)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def type_out(text: str) -> tuple[bool, str]:
    """Напечатать символ в то окно, где курсор.

    На Wayland это делает `wtype` через протокол виртуальной клавиатуры — единственный
    разрешённый способ: синтетические события ввода протокол запрещает, а виртуальную клавиатуру
    KWin 6 поддерживает. На X11 — `xdotool type`.

    Возвращает (получилось, чем). Не получилось — символ всё равно уже в буфере, и об этом
    говорит островок: «в буфере, вставьте Ctrl+V»."""
    from . import face

    if face.session() == "wayland" and shutil.which("wtype"):
        cmd, how = ["wtype", "--", text], "wtype"
    elif face.session() == "x11" and shutil.which("xdotool"):
        cmd, how = ["xdotool", "type", "--clearmodifiers", "--", text], "xdotool"
    else:
        return False, ""
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=10)
        return p.returncode == 0, how
    except (OSError, subprocess.SubprocessError):
        return False, how


def paste_chord() -> tuple[bool, str]:
    """Вставить из буфера: Ctrl+V в то окно, где курсор (как ⌘V на macOS).

    Нужно для длинного и многострочного текста: набирать его посимвольно через
    type_out нельзя — редактор получит Enter на каждый перевод строки.
    """
    from . import face

    if face.session() == "wayland" and shutil.which("wtype"):
        cmd, how = ["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"], "wtype-ctrl-v"
    elif face.session() == "x11" and shutil.which("xdotool"):
        cmd, how = ["xdotool", "key", "--clearmodifiers", "ctrl+v"], "xdotool-ctrl-v"
    else:
        return False, ""
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=5)
        return p.returncode == 0, how
    except (OSError, subprocess.SubprocessError):
        return False, how


def use(ch: str, *, paste: bool = True) -> dict:
    """Выбрали символ: запомнить, положить в буфер и напечатать, если есть чем.

    Печатаем, а не только кладём в буфер: человек выбирает эмодзи, стоя курсором в строке, и
    «скопировано, вставьте сами» — это лишний шаг ровно там, где его меньше всего ждут.
    """
    remember(ch)
    copied = to_clipboard(ch)
    typed, how = (False, "")
    if paste:
        time.sleep(PASTE_DELAY)
        typed, how = type_out(ch)
    return {"ok": copied or typed, "char": ch, "typed": typed, "copied": copied, "how": how,
            "note": "" if typed else ("в буфере обмена — вставьте Ctrl+V" if copied
                                      else "нечем ни вставить, ни положить в буфер")}


def note_for(ch: str) -> str:
    item = by_char(ch)
    return f"{ch}  {item['n']}" if item else ch


def paste_hint() -> str:
    """Чем на этой машине будет вставляться символ — для настроек и `justday doctor`."""
    from . import face

    if face.session() == "wayland":
        return "wtype" if shutil.which("wtype") else "нет wtype — только в буфер обмена"
    if face.session() == "x11":
        return "xdotool" if shutil.which("xdotool") else "нет xdotool — только в буфер обмена"
    return "сеанс не опознан — только в буфер обмена"


def stats() -> dict:
    """Что в наборе — для `justday test glyphs`."""
    got = load()
    counts: dict[str, int] = {}
    for item in got["items"]:
        counts[item["g"]] = counts.get(item["g"], 0) + 1
    return {"total": len(got["items"]), "groups": counts, "recent": len(recents()),
            "paste": paste_hint(), "data": str(DATA) if DATA.is_file() else "нет файла"}


if __name__ == "__main__":  # быстрый взгляд: python -m justday.glyphs кот
    import sys

    for found in search(" ".join(sys.argv[1:]), limit=12):
        print(found["c"], found["n"], "·", ", ".join(found.get("k", [])[:4]))
    print(os.linesep + json.dumps(stats(), ensure_ascii=False, indent=2))
