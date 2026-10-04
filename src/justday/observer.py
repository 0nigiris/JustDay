"""Наблюдатель: Джарвис пишет первым (пункт 20 плана, ступени 2–3).

Раз в минуту смотрит на календарь и решает, надо ли вмешаться. Правило вмешательства важнее самого
наблюдателя, поэтому оно узкое и по умолчанию молчит: пишет только о встрече, до начала которой
осталось не больше `observer.lead_minutes` (20), и один раз о каждой. Письма от незнакомых, события
на весь день и уже начавшееся — не повод.

Чего здесь нет нарочно. Звонка: он стоит денег, а деньги без его слова не тратятся. Вопроса «успеете
ли», пока не известно, где он (ступень 4 плана). Канал наружу — уведомление, Telegram и голос, если он
за компьютером; всё это бесплатно.

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


def key(item: dict) -> str:
    return f"{item['start']}|{item['title']}"


def plan(items: list[dict], now: dt.datetime, sent: dict, lead_minutes: float) -> list[dict]:
    """Какие из событий стоит объявить сейчас: ещё не начались, начнутся в пределах `lead_minutes`, о них не говорили."""
    out = []
    for e in items:
        if e.get("all_day"):
            continue
        start = dt.datetime.fromisoformat(e["start"])
        left = (start - now).total_seconds() / 60
        if left <= 0 or left > lead_minutes or key(e) in sent:
            continue
        out.append({"key": key(e), "title": e["title"], "start": start, "minutes": max(1, round(left)),
                    "location": e.get("location", "")})
    out.sort(key=lambda n: n["start"])
    return out[:MAX_PER_TICK]


def line(n: dict, address: str = "") -> str:
    """Одна фраза, как сказал бы человек: без «уведомление» и без «событие календаря»."""
    head = f"{address}, " if address else ""
    where = f" ({n['location']})" if n.get("location") else ""
    return f"{head}«{n['title']}»{where} в {n['start'].strftime('%H:%M')} — через {n['minutes']} мин."


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
               path: Path = STATE) -> list[str]:
    """Один круг наблюдения. Возвращает сказанные фразы (для проверки и журнала)."""
    opts = cfg.get("observer") or {}
    if not opts.get("enabled", True):
        return []
    now = now or dt.datetime.now().astimezone()
    lead = float(opts.get("lead_minutes") or 20)
    sent = load(path)
    said = []
    # Календарь берётся по сети: из потока, а не из цикла событий демона (Р-33).
    items = await asyncio.get_running_loop().run_in_executor(None, fetch, now, now + dt.timedelta(minutes=lead + 1))
    for n in plan(items, now, sent, lead):
        text = line(n, str((cfg.get("user") or {}).get("address_as") or ""))
        sent[n["key"]] = time.time()      # сначала помечаем: сбой доставки не должен превратиться в спам раз в минуту
        save(sent, path)
        await deliver(text)
        said.append(text)
    return said
