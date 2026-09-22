"""The first «привет» of the day, answered with the day itself: weather, calendar, mail, what is still open.

The model is not asked: everything here is either already in hand (the weather the island polls) or one
short request away, and a greeting that takes four seconds to answer is not a greeting. Once a day —
the second hello is just a hello, and the brain answers it in its own voice."""
from __future__ import annotations

import datetime as dt
import logging
import re
import time

from . import calendar_lane, events, reminders
from .i18n import lang, t

log = logging.getLogger("justday")

HELLO = re.compile(
    r"^(привет|приветствую|здравствуй|здравствуйте|здорово|хай|доброе утро|с добрым утром|утро доброе|"
    r"добрый день|добрый вечер|доброго утра|"
    r"hello|hi|hey|good morning|morning|good day|good evening)$")
NOISE = re.compile(r"\b(джарвис|justday|сэр|дружище|брат|jarvis|sir|ну|эй|там|же|hey|there|дорогой)\b")


def wanted(text: str) -> bool:
    """A greeting and nothing else — «привет, поставь музыку» is a request, not a good morning."""
    clean = NOISE.sub(" ", text.lower().replace("ё", "е"))
    clean = re.sub(r"[^\w\s]", " ", clean)
    return bool(HELLO.fullmatch(re.sub(r"\s+", " ", clean).strip()))


def due() -> bool:
    """Only the first greeting of the day gets the briefing (and only after a night, not after a nap)."""
    last = float(events.load_state().get("briefing_at", 0))
    return dt.date.fromtimestamp(last) < dt.date.today() if last else True


def _hello(cfg: dict) -> str:
    hour = dt.datetime.now().hour
    name = cfg["user"].get("address_as", "")
    if lang() == "en":
        part = "Good morning" if 4 <= hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    else:
        part = "Доброе утро" if 4 <= hour < 12 else "Добрый день" if hour < 18 else "Добрый вечер"
    return f"{part}, {name}." if name else f"{part}."


def _weather_line(w: dict | None) -> str:
    if not w:
        return ""
    # the figures stay figures: the speech normalizer says them as words, the island shows them as digits
    return t("{city}: {temp}°, {text}, днём до {max}°.", city=w["city"], temp=f"{w['temp']:+d}",
             text=w["text"].lower(), max=w["max"])


def _calendar_line() -> str:
    if not calendar_lane.urls():
        return ""
    today = [e for e in calendar_lane.day(0) if not e["all_day"]]
    now = dt.datetime.now().astimezone()
    ahead = [e for e in today if dt.datetime.fromisoformat(e["start"]) >= now]
    if not ahead:
        return t("В календаре на сегодня пусто.") if not today else ""
    first = ahead[0]
    when = dt.datetime.fromisoformat(first["start"]).strftime("%H:%M")
    line = t("В {time} — {title}.", time=when, title=first["title"])
    return line + (" " + t("Дальше сегодня ещё {n}.", n=len(ahead) - 1) if len(ahead) > 1 else "")


def _mail_line(cfg: dict) -> str:
    if not cfg["mail"]["address"]:
        return ""
    from . import mail as mail_mod

    n = mail_mod.count(cfg["mail"]["query"])
    return t("Важных писем: {n}.", n=n) if n else ""


def _open_line() -> str:
    """What was set for earlier and never happened — the thing worth hearing before the day starts."""
    now = time.time()
    late = [r for r in reminders.items() if r["at"] < now]
    if not late:
        return ""
    first = reminders.phrase(late[0])
    return t("Со вчера висит: {what}.", what=first) if len(late) == 1 else \
        t("Со вчера висит {n}, первое — {what}.", n=len(late), what=first)


def compose(cfg: dict, weather: dict | None) -> str:
    """One phrase for the whole morning. Anything that fails (no network, no mail) simply stays out of it."""
    parts = [_hello(cfg)]
    for source in (lambda: _weather_line(weather), _calendar_line, lambda: _mail_line(cfg), _open_line):
        try:
            line = source()
        except Exception as e:
            log.info("briefing: %s skipped (%s)", getattr(source, "__name__", "part"), type(e).__name__)
            continue
        if line:
            parts.append(line)
    events.save_state(briefing_at=time.time())
    return " ".join(parts)
