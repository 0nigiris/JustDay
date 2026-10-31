"""Присмотр: Джарвис замечает, что человек засиделся в игре, и мягко спрашивает про дело.

Он сам попросил: «зашёл в Roblox — домашка сделана? скинь фото». Правило узкое и по умолчанию
тихое: одно напоминание в день на программу, и только когда она в фокусе непрерывно дольше
`after_minutes`. Свернул игру и вернулся через минуту — отсчёт идёт заново. Слежка за содержимым
окон и скриншоты здесь не нужны: хватает названия программы, которое и так знает остров.

Окна и доставка передаются снаружи (как в observer.py), чтобы правило проверялось без KWin и бота.
"""
from __future__ import annotations

import datetime as dt
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from . import config

STATE = config.STATE_DIR / "guardian.json"


def load(path: Path = STATE) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(data: dict, path: Path = STATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def watched(windows: list[dict], apps: list[str]) -> str:
    """Какая из следимых программ сейчас в фокусе (пусто — никакая)."""
    for w in windows or []:
        if isinstance(w, dict) and w.get("active") and not w.get("minimized"):
            hay = f"{w.get('app', '')} {w.get('title', '')}".lower()
            for a in apps:
                if a.lower() in hay:
                    return a
    return ""


async def tick(windows: list[dict], deliver: Callable[[str], Awaitable[None]], cfg: dict,
               now: float | None = None, path: Path = STATE) -> str:
    """Один круг (раз в минуту). Возвращает сказанную фразу или пустую строку."""
    opts = cfg.get("watch") or {}
    if not opts.get("enabled", True):
        return ""
    now = now or time.time()
    day = dt.date.fromtimestamp(now).isoformat()
    st = load(path)
    app = watched(windows, [str(a) for a in opts.get("apps") or []])
    since = st.get("since") or {}
    if not app:
        if since:
            save({**st, "since": {}}, path)
        return ""
    since.setdefault(app, now)
    st["since"] = since
    quiet = st.get("told", {}).get(app) == day
    if quiet or now - since[app] < 60 * float(opts.get("after_minutes") or 10):
        save(st, path)
        return ""
    st.setdefault("told", {})[app] = day      # сначала помечаем: сбой доставки не должен стать спамом раз в минуту
    save(st, path)
    who = str((cfg.get("user") or {}).get("address_as") or "")
    text = str(opts.get("question") or "Уже давно в игре. Домашка сделана? Скинь фото, если да.")
    text = f"{who.capitalize()}, {text[0].lower()}{text[1:]}" if who else text
    await deliver(text)
    return text


def done(cfg: dict, now: float | None = None, path: Path = STATE) -> list[str]:
    """Дело на сегодня сделано (фото принято): до завтра про него не спрашивать."""
    day = dt.date.fromtimestamp(now or time.time()).isoformat()
    apps = [str(a) for a in (cfg.get("watch") or {}).get("apps") or []]
    st = load(path)
    st.setdefault("told", {}).update({a: day for a in apps})
    save(st, path)
    return apps
