"""Private calendar lane: "что у меня сегодня?" answered on this computer from iCal feeds.

Google Calendar → Settings → your calendar → "Secret address in iCal format" (read-only link, no OAuth).
Any other .ics URL (Nextcloud, Outlook, Yandex) works the same. URLs are secrets → desktop keyring.
Events are formatted locally without any model; nothing goes to the cloud brain.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.request

from . import config, events, providers

CAL_WORDS = re.compile(r"\b(календар\w*|расписани\w*|встреч\w*|созвон\w*|планы? на|что у меня (сегодня|завтра|на неделе|на завтра))", re.I)
_cache: dict[str, tuple[float, bytes]] = {}


def urls() -> list[str]:
    raw = providers.secret_get("calendar")
    return [u for u in re.split(r"\s+", raw) if u.startswith(("http://", "https://", "webcal://"))]


def _fetch(url: str) -> bytes:
    url = "https://" + url[len("webcal://"):] if url.startswith("webcal://") else url
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "JustDay"}), timeout=20) as r:
        data = r.read()
    _cache[url] = (time.time(), data)
    return data


def between(start: dt.datetime, end: dt.datetime) -> list[dict]:
    import icalendar
    import recurring_ical_events

    local = dt.datetime.now().astimezone().tzinfo
    out = []
    for url in urls():
        cal = icalendar.Calendar.from_ical(_fetch(url))
        name = str(cal.get("X-WR-CALNAME", ""))
        for ev in recurring_ical_events.of(cal).between(start, end):
            s, e = ev.get("DTSTART").dt, (ev.get("DTEND") or ev.get("DTSTART")).dt
            all_day = not isinstance(s, dt.datetime)
            if not all_day:
                s = (s if s.tzinfo else s.replace(tzinfo=local)).astimezone(local)
                e = (e if e.tzinfo else e.replace(tzinfo=local)).astimezone(local)
            out.append({"title": str(ev.get("SUMMARY", "Без названия")), "all_day": all_day,
                        "start": s.isoformat(), "end": e.isoformat(), "location": str(ev.get("LOCATION", "") or ""),
                        "calendar": name})
    out.sort(key=lambda x: (not x["all_day"], x["start"]))
    return out


def day(offset: int = 0) -> list[dict]:
    local = dt.datetime.now().astimezone()
    start = local.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=offset)
    return between(start, start + dt.timedelta(days=1))


def upcoming(hours: float = 2) -> dict | None:
    now = dt.datetime.now().astimezone()
    for e in between(now, now + dt.timedelta(hours=hours)):
        if not e["all_day"] and dt.datetime.fromisoformat(e["start"]) >= now:
            return e
    return None


def spoken(items: list[dict], when: str) -> str:
    if not items:
        return f"{when.capitalize()} в календаре ничего нет."
    parts = []
    for e in items[:6]:
        if e["all_day"]:
            parts.append(f"весь день — {e['title']}")
        else:
            parts.append(f"в {dt.datetime.fromisoformat(e['start']).strftime('%H:%M')} — {e['title']}")
    more = f" И ещё {len(items) - 6}." if len(items) > 6 else ""
    n = len(items)
    word = "событие" if n % 10 == 1 and n % 100 != 11 else "события" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "событий"
    return f"{when.capitalize()} {n} {word}: " + "; ".join(parts) + "." + more


def handle(text: str) -> tuple[str, dict] | None:
    """Voice request → (spoken reply, island card) or None if it is not about the calendar / no calendar set up."""
    if not CAL_WORDS.search(text) or not urls():
        return None
    t = text.lower()
    offset, when = (1, "завтра") if "завтра" in t else (0, "сегодня")
    if "недел" in t:
        local = dt.datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        items = between(local, local + dt.timedelta(days=7))
        when = "на этой неделе"
    else:
        items = day(offset)
    events.emit("calendar", count=len(items))  # no titles in the journal
    return spoken(items, when), {"type": "calendar", "when": when, "items": items[:8]}


if __name__ == "__main__":
    print(json.dumps(day(0), ensure_ascii=False, indent=1))
