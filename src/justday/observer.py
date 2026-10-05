"""Наблюдатель: Джарвис пишет первым (пункт 20 плана, ступени 2–3).

Раз в минуту смотрит на календарь и решает, надо ли вмешаться. Правило вмешательства важнее самого
наблюдателя, поэтому оно узкое и по умолчанию молчит: пишет только о встрече, до начала которой
осталось не больше `observer.lead_minutes` (20), и один раз о каждой. Письма от незнакомых, события
на весь день и уже начавшееся — не повод.

Чего здесь нет нарочно. Звонка: он стоит денег, а деньги без его слова не тратятся. Канал наружу —
уведомление, Telegram и голос, если он за компьютером; всё это бесплатно.

«Успеете ли» (ступень 4): если он отдал боту живую геопозицию (`geo.py`), а у встречи есть место, срок
напоминания растёт на дорогу — встреча в сорока минутах езды объявляется за пятьдесят, а не за двадцать,
иначе сообщение приходило бы тогда, когда выезжать уже поздно. Без позиции всё как раньше.

Календарь и доставка передаются снаружи, чтобы правило проверялось без сети и без живого бота.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from . import config

STATE = config.STATE_DIR / "observer.json"
MAX_PER_TICK = 3       # три встречи подряд — это уже один разговор, а не три сообщения
BUFFER_MIN = 10        # запас сверх дороги: собраться, найти вход
LOOKAHEAD_MIN = 180    # дальше этого дорогу не считаем: до такой встречи ещё нечего подсказывать


def key(item: dict) -> str:
    return f"{item['start']}|{item['title']}"


def plan(items: list[dict], now: dt.datetime, sent: dict, lead_minutes: float,
         drive: dict | None = None) -> list[dict]:
    """Какие из событий стоит объявить сейчас: ещё не начались, начнутся в пределах `lead_minutes`, о них не говорили.

    `drive` — {ключ события: минут езды до места}. Для такого события срок — дорога плюс запас, если он дольше."""
    out = []
    for e in items:
        if e.get("all_day"):
            continue
        start = dt.datetime.fromisoformat(e["start"])
        left = (start - now).total_seconds() / 60
        road = (drive or {}).get(key(e))
        reach = max(lead_minutes, road + BUFFER_MIN) if road is not None else lead_minutes
        if left <= 0 or left > reach or key(e) in sent:
            continue
        out.append({"key": key(e), "title": e["title"], "start": start, "minutes": max(1, round(left)),
                    "location": e.get("location", ""), "drive": None if road is None else max(1, round(road))})
    out.sort(key=lambda n: n["start"])
    return out[:MAX_PER_TICK]


def line(n: dict, address: str = "") -> str:
    """Одна фраза, как сказал бы человек: без «уведомление» и без «событие календаря»."""
    head = f"{address}, " if address else ""
    where = f" ({n['location']})" if n.get("location") else ""
    text = f"{head}«{n['title']}»{where} в {n['start'].strftime('%H:%M')} — через {n['minutes']} мин."
    road = n.get("drive")
    if road is None:
        return text
    if n["minutes"] < road:
        return f"{text} Дорога займёт около {road} мин — не успеваете. Предупредить, чтобы перенесли?"
    return f"{text} Дорога займёт около {road} мин — пора выходить."


def nudges(day: str = "") -> list[dict]:
    """Что наблюдатель сказал первым за день: время и текст. Мерка из пункта 20 — «ни одного лишнего»; чтобы её
    применить, надо видеть, что именно он сказал, а не только число."""
    from . import events

    day = day or dt.date.today().isoformat()
    return [{"at": str(e.get("ts", ""))[11:16], "text": e.get("text", "")} for e in events.read(day) if e.get("kind") == "nudge"]


def load(path: Path = STATE) -> dict:
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def save(sent: dict, path: Path = STATE) -> None:
    """Помним сказанное и после перезапуска демона: иначе каждый перезапуск повторял бы то же напоминание."""
    keep = {k: v for k, v in sent.items() if time.time() - float(v) < 86400}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(keep, ensure_ascii=False), encoding="utf-8")
        path.chmod(0o600)
    except OSError:
        pass


async def tick(fetch: Callable[[dt.datetime, dt.datetime], list[dict]],
               deliver: Callable[[str], Awaitable[None]], cfg: dict, now: dt.datetime | None = None,
               path: Path = STATE, travel: Callable[[str], float | None] | None = None) -> list[str]:
    """Один круг наблюдения. Возвращает сказанные фразы (для проверки и журнала)."""
    opts = cfg.get("observer") or {}
    if not opts.get("enabled", True):
        return []
    now = now or dt.datetime.now().astimezone()
    lead = float(opts.get("lead_minutes") or 20)
    sent = load(path)
    said = []
    # Календарь берётся по сети: из потока, а не из цикла событий демона (Р-33).
    loop = asyncio.get_running_loop()
    reach = LOOKAHEAD_MIN if travel and opts.get("travel", True) else lead + 1
    items = await loop.run_in_executor(None, fetch, now, now + dt.timedelta(minutes=reach))
    drive: dict = {}
    if reach > lead + 1:
        # Дорога считается по сети, и считать её для всего, что слышно в ближайшие три часа, незачем: нужны
        # только события с местом, о которых ещё не говорили.
        asks = {key(e): e["location"] for e in items if e.get("location") and not e.get("all_day") and key(e) not in sent}
        drive = await loop.run_in_executor(None, lambda: {k: m for k, v in asks.items() if (m := travel(v)) is not None})
    for n in plan(items, now, sent, lead, drive):
        text = line(n, str((cfg.get("user") or {}).get("address_as") or ""))
        sent[n["key"]] = time.time()      # сначала помечаем: сбой доставки не должен превратиться в спам раз в минуту
        save(sent, path)
        await deliver(text)
        said.append(text)
    return said
