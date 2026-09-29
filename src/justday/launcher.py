"""Поиск программ для островка — то, что в других оболочках зовут «спотлайтом».

Отличие от чужих лаунчеров одно, и оно же главное: поле не обязано быть командой. Не нашлось
программы — строка уходит ассистенту, и «поставь таймер на десять минут» работает там же, где
«открой дискорд». Поэтому лаунчер и живёт внутри островка, а не рядом с ним.

Что он ищет: установленные программы, игры (Steam, Lutris, Heroic — их знает desktop.list_games)
и открытые окна. Порядок ответов — как у эмодзи: сначала ровное совпадение, потом начало слова,
потом вхождение; при равенстве выше то, что запускали недавно.

Недавние важнее любой хитрой оценки: человек открывает одно и то же, и пустое поле должно
показывать это, а не алфавит.
"""
from __future__ import annotations

import json
import time

from . import config, desktop

RECENT_FILE = config.STATE_DIR / "launcher-recent.json"
RECENT_MAX = 40


def recents() -> list[str]:
    """Что запускали, самое свежее первым. Ключ — «вид:идентификатор»."""
    try:
        got = json.loads(RECENT_FILE.read_text(encoding="utf-8"))
        return [str(k) for k in got][:RECENT_MAX] if isinstance(got, list) else []
    except (OSError, ValueError):
        return []


def remember(kind: str, ident: str) -> None:
    key = f"{kind}:{ident}"
    keep = [key] + [k for k in recents() if k != key]
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        RECENT_FILE.write_text(json.dumps(keep[:RECENT_MAX], ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


# Раскладка, в которой начали печатать. «Вшысщкв» — это Discord, набранный не глядя на строку;
# без этого лаунчер отвечает пустотой ровно в тот момент, когда человек спешит.
RU_KEYS = "йцукенгшщзхъфывапролджэячсмитьбю.ёЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮ,Ё"
EN_KEYS = "qwertyuiop[]asdfghjkl;'zxcvbnm,./`QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>?~"
_TO_EN = str.maketrans(RU_KEYS, EN_KEYS)
_TO_RU = str.maketrans(EN_KEYS, RU_KEYS)


def swap_layout(text: str) -> str:
    """Та же строка, набранная в другой раскладке."""
    ru = sum(1 for c in text if c in RU_KEYS)
    return text.translate(_TO_EN) if ru > len(text) / 2 else text.translate(_TO_RU)


def _flat(text: str) -> str:
    return str(text or "").lower().replace("ё", "е")


def _score(words: list[str], name: str, extra: list[str]) -> int:
    """Насколько запись подходит запросу. Меньше — лучше, 99 — не подходит."""
    name = _flat(name)
    extra = [_flat(e) for e in extra if e]
    best = 0
    for word in words:
        if name == word:
            hit = 0
        elif name.startswith(word):
            hit = 1
        elif any(part.startswith(word) for part in name.replace("-", " ").replace(".", " ").split()):
            hit = 2
        elif word in name:
            hit = 3
        elif any(e.startswith(word) for e in extra):
            hit = 4
        elif any(word in e for e in extra):
            hit = 5
        else:
            return 99
        best = max(best, hit)
    return best


def items(query: str = "", limit: int = 40, *, windows: bool = True) -> list[dict]:
    """Что показать на запрос. Пустой запрос — недавние, потом остальное по алфавиту.

    Ничего не нашлось — пробуем ту же строку в другой раскладке, и только потом отвечаем пустотой."""
    got = _items(query, limit, windows=windows)
    if not got and query.strip():
        got = _items(swap_layout(query), limit, windows=windows)
    return got


def _items(query: str, limit: int, *, windows: bool) -> list[dict]:
    words = [w for w in _flat(query).split() if w]
    order = {key: n for n, key in enumerate(recents())}
    rows: list[tuple[int, int, str, dict]] = []

    for app in desktop.list_apps():
        name = app.get("name_ru") or app.get("name") or app["id"]
        extra = [app.get("name", ""), app.get("generic", ""), app["id"], *app.get("keywords", "").split(";")]
        score = _score(words, name, extra) if words else 0
        if score >= 99:
            continue
        rows.append((score, order.get(f"app:{app['id']}", 999), _flat(name),
                     {"kind": "app", "id": app["id"], "name": name, "icon": app.get("icon", ""),
                      "sub": app.get("generic", "")}))

    for game in desktop.list_games():
        score = _score(words, game["name"], [game.get("source", "")]) if words else 0
        if score >= 99:
            continue
        rows.append((score, order.get(f"game:{game['id']}", 999), _flat(game["name"]),
                     {"kind": "game", "id": str(game["id"]), "name": game["name"],
                      "icon": "applications-games", "sub": game.get("source", "")}))

    # Открытые окна: «перейти к дискорду» — это не запуск второго дискорда, а переход к тому,
    # что уже открыто. Поэтому они идут отдельным видом и, при равном совпадении, выше запуска.
    if windows and words:
        try:
            for win in desktop.windows("list"):
                title, app = win.get("title", ""), win.get("app", "")
                score = _score(words, title or app, [app])
                if score >= 99:
                    continue
                rows.append((score, -1, _flat(title),
                             {"kind": "window", "id": str(win.get("id") or win.get("win") or ""),
                              "name": title or app, "icon": "preferences-system-windows",
                              "sub": "открыто · " + app}))
        except Exception:
            pass    # окнами может быть нечем управлять — это не повод ломать поиск программ

    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    out, seen = [], set()
    for _, _, _, row in rows:
        key = (row["kind"], row["id"])
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def run(kind: str, ident: str) -> dict:
    """Запустить программу или игру, перейти к окну."""
    try:
        if kind == "window":
            desktop.windows("focus", ident)
            return {"ok": True, "kind": kind, "id": ident}
        if kind == "game":
            got = desktop.launch_game(ident)
            remember(kind, ident)
            return {"ok": True, "kind": kind, "name": got.get("name", ident)}
        desktop.launch_app_id(f"{ident}.desktop" if not ident.endswith(".desktop") else ident)
        remember("app", ident)
        return {"ok": True, "kind": "app", "id": ident}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def stats() -> dict:
    """Что лаунчер видит — для `justday test launcher`."""
    return {"apps": len(desktop.list_apps()), "games": len(desktop.list_games()),
            "recent": len(recents()), "at": time.time()}
