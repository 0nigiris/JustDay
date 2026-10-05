"""Где он сейчас и сколько ехать до встречи (пункт 20 плана, ступень 4).

Откуда позиция. Только то, что он сам отдал боту в Telegram: «Поделиться геопозицией → транслировать».
Телефон шлёт новые координаты в чат, демон кладёт последние в один файл (0600) и ничего больше не хранит —
ни трек, ни историю. Позиция старше `FRESH_S` считается неизвестной: человек мог закрыть трансляцию, и
«вы в дороге» по вчерашней точке — хуже молчания.

Куда уходят данные. Два бесплатных сервиса OpenStreetMap, без аккаунтов и ключей: Nominatim переводит
адрес из события в координаты (уходит только текст места), OSRM считает дорогу (уходят две точки). Это
единственное, что покидает машину; выключается `observer.travel = false`. Дорога считается на машине:
публичный OSRM других профилей не даёт, поэтому для пешехода оценка пессимистична."""
from __future__ import annotations

import functools
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import config

STATE = config.STATE_DIR / "location.json"
FRESH_S = 15 * 60
UA = "JustDay/1.0 (personal assistant; contact: owner)"   # правило Nominatim: безымянные запросы блокируют


def remember(lat: float, lon: float, now: float | None = None, path: Path = STATE) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Сразу с правами 0600: write_text, а потом chmod оставляли окно, где координаты читал любой.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(json.dumps({"lat": lat, "lon": lon, "at": now or time.time()}))
    except OSError:
        pass


def here(now: float | None = None, path: Path = STATE) -> tuple[float, float] | None:
    """Последняя известная позиция или None, если её нет или она устарела."""
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
        if (now or time.time()) - float(got["at"]) > FRESH_S:
            return None
        return float(got["lat"]), float(got["lon"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _get(url: str, timeout: float = 6) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


@functools.lru_cache(maxsize=64)
def geocode(place: str) -> tuple[float, float] | None:
    """Адрес из события → координаты. Не нашлось или сеть упала — None (и это тоже запоминается до перезапуска)."""
    try:
        got = _get("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
            {"q": place, "format": "json", "limit": 1}))
        return (float(got[0]["lat"]), float(got[0]["lon"])) if got else None
    except Exception:
        return None


def drive_minutes(a: tuple[float, float], b: tuple[float, float]) -> float | None:
    try:
        got = _get(f"https://router.project-osrm.org/route/v1/driving/{a[1]},{a[0]};{b[1]},{b[0]}?overview=false")
        return float(got["routes"][0]["duration"]) / 60
    except Exception:
        return None


_ROUTES: dict[tuple, tuple[float, float | None]] = {}


def minutes_to(place: str, now: float | None = None) -> float | None:
    """Сколько ехать отсюда до `place`; None — позиции нет, места не нашли или сервис не ответил.

    Ответ живёт пять минут: наблюдатель спрашивает раз в минуту, а публичный OSRM — общий сервис,
    который не стоит дёргать чаще, чем меняется ответ."""
    now = now or time.time()
    pos = here(now)
    if not pos or not place.strip():
        return None
    dest = geocode(place.strip())
    if not dest:
        return None
    key = (round(pos[0], 3), round(pos[1], 3), dest)
    hit = _ROUTES.get(key)
    if hit and now - hit[0] < 300:
        return hit[1]
    got = drive_minutes(pos, dest)
    _ROUTES[key] = (now, got)
    return got
