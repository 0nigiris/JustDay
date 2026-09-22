"""Timers, alarms and reminders — the small promises an assistant is expected to keep.

Everything lives in one JSON file, so a restart of the daemon (or of the machine) never loses a
morning alarm. The daemon holds a single sleeping task that wakes for whichever is due first.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timedelta

from . import config, numerals

FILE = config.STATE_DIR / "reminders.json"

UNITS = {"сек": 1, "секунд": 1, "минут": 60, "мин": 60, "час": 3600, "часов": 3600, "часа": 3600,
         "second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "h": 3600, "m": 60, "s": 1}

# «на 10 минут», «через полтора часа», «на 1 час 30 минут»
_WORD_NUM = {"полминуты": 30, "полчаса": 1800, "полтора часа": 5400, "полторы минуты": 90,
             "час": 3600, "часик": 3600, "минуту": 60, "минутку": 60, "минуточку": 60, "секунду": 1}
_SPAN = re.compile(r"(\d+(?:[.,]\d+)?)\s*(сек\w*|мин\w*|час\w*|second\w*|sec\b|minute\w*|min\b|hour\w*|\bh\b|\bm\b|\bs\b)", re.I)
_AT = re.compile(r"\b(?:в|к|на|at)\s+([01]?\d|2[0-3])[:.]([0-5]\d)\b"
                 r"|\b(?:в|к|на|at)\s+([01]?\d|2[0-3])\s*(?:час\w*|o'?clock|(?=\s*(?:утра|вечера|дня|ночи|am|pm)))", re.I)
_DAYPART = re.compile(r"\b(утра|вечера|дня|ночи|am|pm)\b", re.I)

TIMER_WORDS = re.compile(r"\b(таймер\w*|timers?)\b", re.I)
ALARM_WORDS = re.compile(r"\b(будильник\w*|разбуди\w*|подъ[ёе]м|alarms?|wake me)\b", re.I)
REMIND_WORDS = re.compile(r"\b(напомн\w*|напоминани\w*|remind\w*)\b", re.I)
CANCEL_WORDS = re.compile(r"\b(отмени|убери|удали|выключи|сбрось|останови|cancel|stop|delete)\b", re.I)
LEFT_WORDS = re.compile(r"\b(сколько|остал\w+|how (much|long)|left)\b", re.I)


def _load() -> list[dict]:
    try:
        got = json.loads(FILE.read_text(encoding="utf-8"))
        return got if isinstance(got, list) else []
    except (OSError, ValueError):
        return []


def _save(items: list[dict]) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def items(include_done: bool = False) -> list[dict]:
    """Everything still waiting, soonest first."""
    got = [r for r in _load() if include_done or not r.get("done")]
    return sorted(got, key=lambda r: r["at"])


def add(kind: str, at: float, label: str = "", repeat: str = "") -> dict:
    """kind: timer (a span from now) | alarm (a time of day) | reminder (either, with a note)."""
    rec = {"id": uuid.uuid4().hex[:8], "kind": kind, "at": float(at), "label": label.strip(),
           "repeat": repeat, "created": time.time(), "done": False}
    got = _load()
    got.append(rec)
    _save(got)
    return rec


def cancel(which: str = "") -> list[dict]:
    """Cancel one by id, all of a kind ("таймер"/"будильник"), or everything when `which` is empty."""
    got, gone = [], []
    kind = "timer" if TIMER_WORDS.search(which) else "alarm" if ALARM_WORDS.search(which) else ""
    for r in _load():
        hit = (not which and not r.get("done")) or r["id"] == which or (kind and r["kind"] == kind and not r.get("done"))
        (gone if hit else got).append(r)
    _save(got)
    return gone


def mark_done(rec_id: str) -> dict | None:
    """A reminder that has rung: gone, or moved to the next day when it repeats."""
    got = _load()
    out = None
    for r in got:
        if r["id"] != rec_id:
            continue
        if r.get("repeat") == "daily":
            r["at"] = float(r["at"]) + 86400
            out = r
        elif r.get("repeat") == "weekdays":
            nxt = datetime.fromtimestamp(r["at"]) + timedelta(days=1)
            while nxt.weekday() >= 5:
                nxt += timedelta(days=1)
            r["at"] = nxt.timestamp()
            out = r
        else:
            r["done"] = True
    _save([r for r in got if not r.get("done") or time.time() - r["at"] < 86400])
    return out


def next_due() -> dict | None:
    got = items()
    return got[0] if got else None


def parse_span(text: str) -> float | None:
    """«на 10 минут», «через полтора часа», «1 час 30 минут», «90 сек» → seconds."""
    low = text.lower()
    if not re.search(r"\d", low):  # «полтора часа», «минутку» — only when no figure says otherwise
        for word, secs in _WORD_NUM.items():
            if re.search(rf"\b{word}\b", low):
                return float(secs)
    total = 0.0
    for value, unit in re.findall(r"(\d+(?:[.,]\d+)?)\s*([hms])(?![a-zA-Zа-яё])", low):  # 10m, 90s, 1h30m
        total += float(value.replace(",", ".")) * {"h": 3600, "m": 60, "s": 1}[unit.lower()]
    if total:
        return total
    for value, unit in _SPAN.findall(low):
        mult = next((v for k, v in UNITS.items() if unit.lower().startswith(k)), None)
        if mult:
            total += float(value.replace(",", ".")) * mult
    return total or None


def parse_time(text: str) -> float | None:
    """«в 7:30», «к 21:00», «в 7 часов» → the next moment that clock shows."""
    m = _AT.search(text)
    if not m:
        return None
    hour = int(m[1] if m[1] else m[3])
    minute = int(m[2] or 0)
    part = _DAYPART.search(text[m.end():m.end() + 12])
    if (part and part.group(1).lower() in ("вечера", "pm") and hour < 12) or (part and part.group(1).lower() == "дня" and hour < 12):
        hour += 12
    elif part and part.group(1).lower() == "ночи" and hour == 12:
        hour = 0
    now = datetime.now()
    when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if when <= now:
        when += timedelta(days=1)
    return when.timestamp()


def parse(text: str) -> dict | None:
    """One spoken line → what to do: {action: set|cancel|list, ...}. None when it is not about time at all."""
    low = text.strip().lower()
    if not low:
        return None
    wants_timer, wants_alarm, wants_remind = TIMER_WORDS.search(low), ALARM_WORDS.search(low), REMIND_WORDS.search(low)
    if not (wants_timer or wants_alarm or wants_remind):
        return None
    if CANCEL_WORDS.search(low):
        return {"action": "cancel", "which": low}
    if LEFT_WORDS.search(low):
        return {"action": "list"}
    at = parse_time(low)
    span = None if at else parse_span(low)
    if at is None and span is None:
        return None
    label = _label(text)
    kind = "alarm" if wants_alarm else "timer" if wants_timer else "reminder"
    repeat = "daily" if re.search(r"\b(кажд\w+ (день|утро)|ежедневно|every day|daily)\b", low) else ""
    return {"action": "set", "kind": kind, "at": at or time.time() + (span or 0), "label": label,
            "span": span, "repeat": repeat}


_LABEL_CUT = re.compile(
    r"^(джарвис|justday|пожалуйста|поставь|постав|заведи|засеки|засекай|установи|сделай|включи|"
    r"напомни|напоминание|разбуди( меня)?|будильник|таймер|мне|на|через|в|к|set|start|a|an|the|remind( me)?|timer|alarm|wake me( up)?)\b",
    re.I)
_LABEL_STRIP = re.compile(r"\b(на|через|в|к|at|in|for)?\s*\d+(?:[.,]\d+)?\s*(сек\w*|мин\w*|час\w*|second\w*|minute\w*|hour\w*)\b|"
                          r"\b(?:в|к|на|at)\s+\d{1,2}(?:[:.]\d{2})?\s*(?:утра|вечера|дня|ночи|am|pm|час\w*)?\b|"
                          r"\b(полчаса|полтора часа|полторы минуты|полминуты|часик|час|минуточку|минутку|минуту|секунду)\b", re.I)


def _label(text: str) -> str:
    """What the reminder is about: everything that is not the command and not the time."""
    rest = _LABEL_STRIP.sub(" ", text)
    for _ in range(6):
        stripped = _LABEL_CUT.sub("", rest.strip(), count=1)
        if stripped == rest.strip():
            break
        rest = stripped
    rest = re.sub(r"^\W*(что|чтобы|про|о|об|about|to|that)\b", "", rest.strip(), flags=re.I)
    return re.sub(r"\s+", " ", rest).strip(" ,.;:—-")


def phrase(rec: dict) -> str:
    """What the assistant says when it rings."""
    label = rec.get("label") or ""
    if rec["kind"] == "alarm":
        when = datetime.fromtimestamp(rec["at"])
        return f"{numerals.clock(when.hour, when.minute)}. {label}".strip(". ") or numerals.clock(when.hour, when.minute)
    return label or ("Таймер" if rec["kind"] == "timer" else "Напоминание")


def left(rec: dict) -> str:
    """«осталось две минуты» / «через полтора часа» for the island and for speech."""
    return numerals.duration(max(0, int(rec["at"] - time.time())))
