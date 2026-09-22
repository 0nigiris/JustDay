"""The weather line on the island — Open-Meteo, free and without a key.

Only the city name (and then its coordinates) ever leaves the computer, and the coordinates are
remembered so the geocoder is asked once per city."""
from __future__ import annotations

import json

from . import events
from .i18n import lang, t

WMO = {0: ("Ясно", "sun"), 1: ("Малооблачно", "cloud-sun"), 2: ("Переменная облачность", "cloud-sun"), 3: ("Пасмурно", "cloud"),
       45: ("Туман", "cloud-fog"), 48: ("Туман", "cloud-fog"), 51: ("Морось", "cloud-rain"), 53: ("Морось", "cloud-rain"),
       55: ("Морось", "cloud-rain"), 61: ("Дождь", "cloud-rain"), 63: ("Дождь", "cloud-rain"), 65: ("Ливень", "cloud-rain"),
       71: ("Снег", "cloud-snow"), 73: ("Снег", "cloud-snow"), 75: ("Снегопад", "cloud-snow"), 80: ("Ливень", "cloud-rain"),
       81: ("Ливень", "cloud-rain"), 82: ("Ливень", "cloud-rain"), 85: ("Снег", "cloud-snow"), 86: ("Снег", "cloud-snow"),
       95: ("Гроза", "cloud-lightning"), 96: ("Гроза", "cloud-lightning"), 99: ("Гроза", "cloud-lightning")}


def fetch_weather(city: str) -> dict | None:
    """Current weather from Open-Meteo (free, no key). Only the city name / coordinates leave the computer."""
    import urllib.parse
    import urllib.request

    state = events.load_state()
    geo = state.get("weather_geo") or {}
    if geo.get("query") != city:
        url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({"name": city, "count": 1, "language": lang()})
        with urllib.request.urlopen(url, timeout=10) as r:
            found = (json.load(r).get("results") or [None])[0]
        if not found:
            return None
        geo = {"query": city, "lat": found["latitude"], "lon": found["longitude"], "name": found.get("name", city)}
        events.save_state(weather_geo=geo)
    url = ("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(
        {"latitude": geo["lat"], "longitude": geo["lon"], "current": "temperature_2m,weather_code,is_day",
         "daily": "temperature_2m_max,temperature_2m_min", "forecast_days": 1, "timezone": "auto"}))
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.load(r)
    cur, daily = data["current"], data.get("daily", {})
    text, icon = WMO.get(int(cur["weather_code"]), ("", "cloud"))
    text = t(text)
    if icon == "sun" and not cur.get("is_day", 1):
        icon = "moon"
    return {"city": geo["name"], "temp": round(cur["temperature_2m"]), "text": text, "icon": icon,
            "max": round((daily.get("temperature_2m_max") or [cur["temperature_2m"]])[0]),
            "min": round((daily.get("temperature_2m_min") or [cur["temperature_2m"]])[0])}
