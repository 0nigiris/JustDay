"""Тишина по расписанию («спиздить у мака», пункт 30): в школе, на работе, ночью ассистент не говорит вслух.

Расписание — список в config.toml:

    [[focus.schedule]]
    name = "Школа"
    days = "пн-пт"          # пн-пт | пн,ср,пт | каждый день (по умолчанию)
    from = "08:30"
    to = "15:00"

Окно через полночь («23:00»–«07:00») относится к дню, в который началось."""
from __future__ import annotations

from datetime import datetime

DAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
EN = {"mon": "пн", "tue": "вт", "wed": "ср", "thu": "чт", "fri": "пт", "sat": "сб", "sun": "вс"}


def _days(spec) -> set[int]:
    """Номера дней недели (0 = понедельник) из «пн-пт», «пн,ср», списка или пустоты (= каждый день)."""
    if not spec or str(spec).strip().lower() in ("каждый день", "ежедневно", "daily", "*"):
        return set(range(7))
    out: set[int] = set()
    items = spec if isinstance(spec, list) else str(spec).lower().split(",")
    for item in items:
        item = EN.get(str(item).strip().lower(), str(item).strip().lower())
        a, _, b = item.partition("-")
        a, b = EN.get(a, a), EN.get(b, b)
        if a in DAYS and not b:
            out.add(DAYS.index(a))
        elif a in DAYS and b in DAYS:
            i, j = DAYS.index(a), DAYS.index(b)
            out |= {(i + k) % 7 for k in range((j - i) % 7 + 1)}
    return out


def _minutes(hhmm) -> int | None:
    try:
        h, m = str(hhmm).split(":")
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def current(schedule: list[dict], now: datetime | None = None) -> dict | None:
    """Окно тишины, которое идёт сейчас: {"name", "until"} («until» — «HH:MM» конца) или None."""
    now = now or datetime.now()
    minute = now.hour * 60 + now.minute
    for slot in schedule or []:
        start, end = _minutes(slot.get("from")), _minutes(slot.get("to"))
        days = _days(slot.get("days"))
        if start is None or end is None or not days:
            continue  # битая запись не должна ни включать тишину навсегда, ни ронять голос
        if start <= end:
            on = now.weekday() in days and start <= minute < end
        else:  # через полночь: вечерняя часть — в день начала, утренняя — в следующий
            on = (now.weekday() in days and minute >= start) or ((now.weekday() - 1) % 7 in days and minute < end)
        if on:
            return {"name": str(slot.get("name") or "фокус"), "until": f"{end // 60:02d}:{end % 60:02d}"}
    return None


def active(schedule: list[dict], now: datetime | None = None) -> str:
    """Название окна тишины, которое идёт сейчас, или «» — тишины нет."""
    cur = current(schedule, now)
    return cur["name"] if cur else ""
