"""Чем оплачен разговор: токены и деньги по журналам сессий мозга.

Claude Code пишет каждую свою сессию в ~/.claude/projects/<путь>/<id>.jsonl, и в каждом
ответе модели есть usage. Отсюда видно главное число — сколько контекста перечитывается
на каждом шаге: именно оно, а не длина ответа, определяет счёт.
"""
from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from pathlib import Path

from .brain import BRAIN_DIR

# $ за миллион токенов: вход, запись в кэш, чтение из кэша, выход.
PRICES = {
    "opus": (15.0, 18.75, 1.5, 75.0),
    "sonnet": (3.0, 3.75, 0.3, 15.0),
    "haiku": (1.0, 1.25, 0.1, 5.0),
}
DEFAULT_PRICE = PRICES["sonnet"]


def wake_report(days: int = 3) -> dict:
    """Кто будил ассистента и сколько раз впустую.

    Ложное срабатывание видно по паре событий: разбудили — и никто не заговорил.
    Разбивка по источникам отвечает на главный вопрос: это слово пробуждения,
    имя, услышанное в речи, или случайно задетая кнопка."""
    since = time.time() - days * 86400
    by_source: dict[str, dict[str, int]] = {}
    waiting = ""
    for record in _events(since):
        kind = record.get("kind")
        if kind == "listen_start" and not record.get("followup"):
            waiting = str(record.get("source") or "?")
            row = by_source.setdefault(waiting, {"woke": 0, "empty": 0})
            row["woke"] += 1
        elif kind in ("listen_empty", "listen_cancelled") and waiting:
            by_source[waiting]["empty"] += 1
            waiting = ""
        elif kind == "heard":
            waiting = ""
    total = {"woke": sum(r["woke"] for r in by_source.values()),
             "empty": sum(r["empty"] for r in by_source.values())}
    return {"days": days, "sources": by_source, "total": total}


def _events(since: float) -> list[dict]:
    from . import config

    out = []
    try:
        lines = config.EVENTS_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    edge = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(since))
    for line in lines:
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if str(record.get("ts", "")) >= edge:
            out.append(record)
    return out


def spaced(n: int) -> str:
    """12345 → «12 345»: в отчёте важны порядки, а не цифры подряд."""
    return f"{n:,}".replace(",", "\u202f")


def sessions_dir() -> Path:
    """Где Claude Code держит журналы сессий мозга."""
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(BRAIN_DIR))


def _price(model: str) -> tuple[float, float, float, float]:
    for name, price in PRICES.items():
        if name in (model or ""):
            return price
    return DEFAULT_PRICE


def _cost(model: str, u: dict) -> float:
    inp, write, read, out = _price(model)
    return (u.get("input_tokens", 0) * inp + u.get("cache_creation_input_tokens", 0) * write
            + u.get("cache_read_input_tokens", 0) * read + u.get("output_tokens", 0) * out) / 1e6


def report(days: int = 7) -> dict:
    """Расход по дням плюс стартовый контекст последней сессии."""
    since = time.time() - days * 86400
    first_day = time.strftime("%Y-%m-%d", time.localtime(since))
    by_day: dict[str, dict] = defaultdict(lambda: {"steps": 0, "context": 0, "write": 0, "read": 0, "out": 0, "usd": 0.0})
    start_context, start_day = 0, ""
    for path in sorted(sessions_dir().glob("*.jsonl"), key=lambda p: p.stat().st_mtime):
        if path.stat().st_mtime < since:
            continue
        seen: set[str] = set()
        first = True
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            message = record.get("message") or {}
            u = message.get("usage")
            request = record.get("requestId")
            if not u or not request or request in seen:
                continue
            seen.add(request)
            context = (u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                       + u.get("cache_read_input_tokens", 0))
            if not context:
                continue
            day = str(record.get("timestamp", ""))[:10]
            if day < first_day:  # старая сессия, дописанная сегодня: её прошлые дни здесь не нужны
                continue
            row = by_day[day]
            row["steps"] += 1
            row["context"] += context
            row["write"] += u.get("cache_creation_input_tokens", 0)
            row["read"] += u.get("cache_read_input_tokens", 0)
            row["out"] += u.get("output_tokens", 0)
            row["usd"] += _cost(message.get("model", ""), u)
            if first:  # первый запрос сессии — это и есть её стартовый контекст
                first = False
                if day >= start_day:
                    start_context, start_day = context, day
    days_out = [{"day": day, **row, "per_step": round(row["context"] / max(1, row["steps"]))}
                for day, row in sorted(by_day.items())]
    total = {key: sum(d[key] for d in days_out) for key in ("steps", "context", "write", "read", "out")}
    total["usd"] = round(sum(d["usd"] for d in days_out), 2)
    total["per_step"] = round(total["context"] / max(1, total["steps"]))
    return {"days": days_out, "total": total, "start_context": start_context, "start_day": start_day}
