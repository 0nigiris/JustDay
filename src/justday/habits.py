"""What the user usually asks for — read back out of the event log, so «как обычно» has an answer.

Nothing new is recorded for this: every phrase already goes through events.jsonl. The point is the
hour of the day. «Включи как обычно» at nine in the evening and at nine in the morning mean two
different playlists, and the log knows which is which."""
from __future__ import annotations

import difflib
import json
import re
from collections import Counter
from datetime import datetime

from . import config

FILLER = re.compile(r"\b(джарвис|justday|пожалуйста|плиз|давай|ка|ну|мне|там|сейчас|сэр|jarvis|please|the|now)\b")
NEAR_HOURS = 2  # «как обычно» means «around this time», not «at this minute»


def _clean(text: str) -> str:
    text = FILLER.sub(" ", text.lower().replace("ё", "е"))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s+-]", " ", text)).strip()


def _lines(limit: int) -> list[dict]:
    try:
        with config.EVENTS_FILE.open(encoding="utf-8") as f:
            raw = f.readlines()[-limit:]
    except OSError:
        return []
    out = []
    for line in raw:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def requests(limit: int = 20000) -> list[tuple[str, int, str]]:
    """Every request heard or typed, as (text, hour, day) — newest last."""
    out = []
    for rec in _lines(limit):
        if rec.get("kind") not in ("heard", "request"):
            continue
        text = _clean(rec.get("text", ""))
        if len(text) < 3 or len(text) > 80:
            continue
        try:
            when = datetime.fromisoformat(rec["ts"])
        except (KeyError, ValueError):
            continue
        out.append((text, when.hour, when.date().isoformat()))
    return out


def summary(hour: int | None = None, top: int = 8) -> dict:
    """What is usually asked around this hour, and what is asked most often at all."""
    hour = datetime.now().hour if hour is None else hour
    all_reqs = requests()
    near = Counter()
    ever = Counter()
    days = set()
    for text, h, day in all_reqs:
        ever[text] += 1
        days.add(day)
        if min((h - hour) % 24, (hour - h) % 24) <= NEAR_HOURS:
            near[text] += 1
    return {"hour": hour, "days_logged": len(days),
            "around_this_hour": _shape(near, top), "most_asked": _shape(ever, top)}


def _shape(counted: Counter, top: int) -> list[dict]:
    """«запусти дельтарун» and «запустите дельтарун» are one habit, not two."""
    merged: list[list] = []
    for text, n in counted.most_common():
        twin = next((m for m in merged if difflib.SequenceMatcher(None, m[0], text).ratio() > 0.82), None)
        if twin:
            twin[1] += n
        else:
            merged.append([text, n])
    merged.sort(key=lambda m: -m[1])
    return [{"text": t, "times": n} for t, n in merged[:top] if n > 1]
