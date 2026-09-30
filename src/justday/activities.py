"""Живые дела: то, что происходит прямо сейчас и о чём островок рассказывает, пока оно идёт.

Чем это отличается от уведомления. Уведомление говорит, что что-то **случилось**, и на этом его
работа кончена. Живое дело говорит, что что-то **идёт**, и живёт ровно столько, сколько идёт: сборка
на шаге четыре из шести, скачивание на семидесяти трёх процентах, рендер с оставшимися сорока
секундами. Поэтому у дела есть состояние, прогресс и срок, а не текст и время показа.

Чем это отличается от «работ» (jobs), которые в проекте уже были. Работа — это то, что запустил
ассистент: у неё есть название и признак «идёт/кончилась». Дело может завести кто угодно — сборка,
`jii`, копирование файлов, ComfyUI, — и у него есть проценты, ожидаемый конец и срок годности
данных. Работы никуда не деваются; дела живут рядом и умеют больше.

Свежесть здесь не мелочь, а отдельное состояние. Показывать вчерашние проценты так же, как
сегодняшние, — значит врать; если обновления прекратились, дело помечается несвежим и говорит об
этом само.
"""
from __future__ import annotations

import secrets
import time

# Род дела задаёт значок и цвет — и то, насколько оно важно по умолчанию. Звонок важнее сборки не
# потому, что новее, а потому, что звонок.
KINDS: dict[str, tuple[str, str, int]] = {
    # род        значок            цвет      важность
    "call":     ("message-circle", "green",  100),
    "timer":    ("timer",          "orange",  90),
    "alarm":    ("bell-ring",      "red",     95),
    "record":   ("mic",            "red",     80),
    "build":    ("code",           "blue",    60),
    "install":  ("package",        "blue",    55),
    "download": ("download",       "blue",    50),
    "upload":   ("upload",         "blue",    50),
    "render":   ("palette",        "purple",  50),
    "copy":     ("folder-open",    "blue",    40),
    "media":    ("music",          "pink",    30),
    "sync":     ("refresh-cw",     "blue",    20),
    "system":   ("cpu",            "grey",    20),
}
DEFAULT_KIND = "system"
STATES = ("active", "done", "failed", "cancelled")
# Кончившееся дело держится на виду ещё немного: исчезнуть в тот же миг — значит не дать прочитать,
# чем всё кончилось.
LINGER_SECONDS = 6.0
MAX_ACTIVITIES = 24

_items: dict[str, dict] = {}


def _now() -> float:
    return time.time()


def kind_of(kind: str) -> tuple[str, str, int]:
    return KINDS.get(str(kind or "").lower(), KINDS[DEFAULT_KIND])


def start(kind: str, title: str, *, status: str = "", progress: float | None = None,
          ends_at: float | None = None, stale_after: float | None = None,
          app: str = "", relevance: int | None = None, actions: list[dict] | None = None,
          ident: str = "") -> dict:
    """Завести дело. Возвращает его целиком — вместе с выданным номером."""
    icon, tint, weight = kind_of(kind)
    item = {
        "id": ident or secrets.token_hex(4),
        "kind": str(kind or DEFAULT_KIND).lower(),
        "app": app,
        "title": title,
        "status": status,
        "progress": _clamp(progress),
        "icon": icon,
        "tint": tint,
        "started": _now(),
        "updated": _now(),
        "ends_at": ends_at,
        # Срок годности данных: после него дело считается несвежим, даже если никто ничего не сказал.
        "stale_after": stale_after,
        "state": "active",
        "relevance": weight if relevance is None else int(relevance),
        "actions": list(actions or []),
        "ended": None,
    }
    _items[item["id"]] = item
    _trim()
    return item


def update(ident: str, **fields) -> dict | None:
    """Поменять то, что изменилось. Незнакомое дело — не ошибка: оно могло уже кончиться."""
    item = _items.get(ident)
    if not item:
        return None
    for key in ("status", "title", "app", "ends_at", "stale_after", "actions"):
        if key in fields and fields[key] is not None:
            item[key] = fields[key]
    if "progress" in fields:
        item["progress"] = _clamp(fields["progress"])
    if "relevance" in fields and fields["relevance"] is not None:
        item["relevance"] = int(fields["relevance"])
    if fields.get("kind"):
        item["kind"] = str(fields["kind"]).lower()
        item["icon"], item["tint"], _ = kind_of(item["kind"])
    item["updated"] = _now()
    return item


def end(ident: str, state: str = "done", *, status: str = "") -> dict | None:
    """Кончить дело. Оно не исчезает сразу: чем всё кончилось, надо успеть прочитать."""
    item = _items.get(ident)
    if not item:
        return None
    item["state"] = state if state in STATES else "done"
    item["ended"] = _now()
    item["updated"] = _now()
    if status:
        item["status"] = status
    if item["state"] == "done" and item["progress"] is not None:
        item["progress"] = 1.0
    return item


def drop(ident: str) -> bool:
    return _items.pop(ident, None) is not None


def clear() -> None:
    _items.clear()


def _clamp(value) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _trim() -> None:
    if len(_items) <= MAX_ACTIVITIES:
        return
    for ident in [i["id"] for i in sorted(_items.values(), key=lambda x: x["started"])][:-MAX_ACTIVITIES]:
        _items.pop(ident, None)


def stale(item: dict, now: float | None = None) -> bool:
    """Данные могли протухнуть: обновлений давно нет, а дело считается идущим."""
    if item["state"] != "active" or not item.get("stale_after"):
        return False
    return (now or _now()) - item["updated"] >= float(item["stale_after"])


def prune(now: float | None = None) -> int:
    """Убрать то, что уже досмотрели. Возвращает, сколько убрали."""
    now = now or _now()
    gone = [i["id"] for i in _items.values()
            if i["ended"] is not None and now - i["ended"] >= LINGER_SECONDS]
    for ident in gone:
        _items.pop(ident, None)
    return len(gone)


def score(item: dict, now: float | None = None) -> float:
    """Насколько дело важно прямо сейчас.

    Важность, а не время появления: скачивание, начатое час назад и досчитавшее до девяноста
    восьми процентов, интереснее сборки, запущенной секунду назад. Спецификация на этом настаивает
    отдельно, и правильно: «самое новое» — это не «самое нужное».
    """
    now = now or _now()
    value = float(item.get("relevance", 0))
    if item["state"] == "failed":
        value += 40                      # сломалось — про это надо узнать сразу
    elif item["state"] in ("done", "cancelled"):
        value += 15                      # кончилось только что: пусть побудет сверху, пока видно
        value -= min(15, (now - (item["ended"] or now)) * 3)
    progress = item.get("progress")
    if progress is not None and progress >= 0.9 and item["state"] == "active":
        value += 10                      # вот-вот кончится — интереснее, чем в начале
    if item.get("ends_at") and item["state"] == "active":
        left = float(item["ends_at"]) - now
        if 0 <= left <= 30:
            value += 12                  # осталось меньше полминуты
    if stale(item, now):
        value -= 25                      # неизвестно, живо ли оно вообще
    return value


def ranked(now: float | None = None) -> list[dict]:
    """Все дела, самое важное первым, с уже посчитанной свежестью."""
    now = now or _now()
    out = []
    for item in _items.values():
        got = dict(item)
        got["stale"] = stale(item, now)
        got["score"] = round(score(item, now), 1)
        got["elapsed"] = round(now - item["started"], 1)
        got["left"] = round(float(item["ends_at"]) - now, 1) if item.get("ends_at") else None
        out.append(got)
    out.sort(key=lambda i: (-i["score"], i["started"]))
    return out


def state(now: float | None = None) -> dict:
    """То, что уходит островку: главное дело, второстепенные и сколько их всего."""
    prune(now)
    items = ranked(now)
    return {"items": items, "primary": items[0] if items else None,
            "minimal": items[1:4], "count": len(items)}
