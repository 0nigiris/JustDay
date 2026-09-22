"""Private calendar lane: "что у меня сегодня?" answered on this computer from iCal feeds.

Google Calendar → Settings → your calendar → "Secret address in iCal format" (read-only link, no OAuth).
Any other .ics URL (Nextcloud, Outlook, Yandex) works the same. URLs are secrets → desktop keyring.
Events are formatted locally without any model; nothing goes to the cloud brain.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import time
import urllib.request

from . import events, providers
from .i18n import lang, t

CAL_WORDS = re.compile(r"\b(календар\w*|расписани\w*|встреч\w*|созвон\w*|планы? на|что у меня (сегодня|завтра|на неделе|на завтра)|"
                       r"calendar|schedule|meetings?|appointments?|what do i have (today|tomorrow|this week))", re.I)
_cache: dict[str, tuple[float, bytes]] = {}


def parse_urls(raw: str) -> list[str]:
    return [u for u in re.split(r"\s+", raw) if u.startswith(("http://", "https://", "webcal://"))]


def urls() -> list[str]:
    return parse_urls(providers.secret_get("calendar"))


def setup(raw: str) -> dict:
    """Check every link before it goes to the keyring, so a typo is never saved as a "connected" calendar."""
    import icalendar

    links = parse_urls(raw)
    if not links:
        return {"ok": False, "error": "нужна ссылка http(s):// или webcal://"}
    for u in links:
        try:
            icalendar.Calendar.from_ical(_fetch(u))
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}
    merged = list(dict.fromkeys([*urls(), *links]))  # a new link is added to the ones already connected
    providers.secret_set("calendar", " ".join(merged))
    return {"ok": True, "today": len(day(0)), "calendars": len(merged)}


def forget() -> dict:
    subprocess.run(["secret-tool", "clear", *providers.SECRET_ATTRS, "key", "calendar"], check=False)
    _cache.clear()
    return {"ok": True}


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
            out.append({"title": str(ev.get("SUMMARY", t("Без названия"))), "all_day": all_day,
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
    when_t = t(when)
    if not items:
        line = t("{when} в календаре ничего нет.", when=when_t)
        return line[0].upper() + line[1:]
    parts = []
    for e in items[:6]:
        if e["all_day"]:
            parts.append(t("весь день — {title}", title=e["title"]))
        else:
            parts.append(t("в {time} — {title}", time=dt.datetime.fromisoformat(e["start"]).strftime("%H:%M"), title=e["title"]))
    more = t(" И ещё {n}.", n=len(items) - 6) if len(items) > 6 else ""
    n = len(items)
    word = "событие" if n % 10 == 1 and n % 100 != 11 else "события" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "событий"
    if lang() == "en":
        word = "event" if n == 1 else "events"
    head = t("{when} {n} {word}: ", when=when_t, n=n, word=word)
    return head[0].upper() + head[1:] + "; ".join(parts) + "." + more


def handle(text: str) -> tuple[str, dict] | None:
    """Voice request → (spoken reply, island card) or None if it is not about the calendar / no calendar set up."""
    if not CAL_WORDS.search(text) or not urls():
        return None
    low = text.lower()
    offset, when = (1, "завтра") if ("завтра" in low or "tomorrow" in low) else (0, "сегодня")
    if "недел" in low or "week" in low:
        local = dt.datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        items = between(local, local + dt.timedelta(days=7))
        when = "на этой неделе"
    else:
        items = day(offset)
    events.emit("calendar", count=len(items))  # no titles in the journal
    return spoken(items, when), {"type": "calendar", "when": t(when), "items": items[:8]}


if __name__ == "__main__":
    print(json.dumps(day(0), ensure_ascii=False, indent=1))
