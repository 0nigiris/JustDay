"""Запись встреч в Google Календарь («Джарвис, у меня в пятницу в 15:00 встреча»).

Чтение идёт по секретной ICS-ссылке (calendar_lane) и записать через неё нельзя, поэтому запись — отдельный
вход через OAuth. Права берём самые узкие: `calendar.events` (создавать события), без доступа к настройкам и
спискам календарей. Нашему коду достаточно создавать; менять и удалять чужие события он не умеет и не должен.

Секреты (файл клиента Google и токен) лежат только в связке ключей. Вход идёт через 127.0.0.1: страницу
согласия открывает сам Google, пароль до нас не доходит.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import http.server
import json
import secrets
import threading
import urllib.parse
import urllib.request
import webbrowser

from . import providers

SCOPE = "https://www.googleapis.com/auth/calendar.events"
AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


def _client() -> dict:
    raw = providers.secret_get("gcal_client")
    if not raw:
        raise RuntimeError("Нет файла клиента Google: `justday calendar login --client ФАЙЛ.json`")
    j = json.loads(raw)
    return j.get("installed") or j.get("web") or j


def _post(url: str, data: dict) -> dict:
    req = urllib.request.Request(url, urllib.parse.urlencode(data).encode(), method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def connected() -> bool:
    return bool(providers.secret_get("gcal_token"))


def login(client_json: str | None = None) -> dict:
    """Один раз: открыть страницу согласия Google и принять код на локальном адресе."""
    if client_json:
        json.loads(client_json)  # битый файл не должен попасть в связку ключей
        providers.secret_set("gcal_client", client_json)
    c = _client()
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    got: dict = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h3>Готово. Это окно можно закрыть.</h3>".encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    redirect = f"http://127.0.0.1:{srv.server_port}"
    url = AUTH + "?" + urllib.parse.urlencode({
        "client_id": c["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
        "access_type": "offline", "prompt": "consent"})
    print("Откройте в браузере, если он не открылся сам:\n" + url, flush=True)
    webbrowser.open(url)
    t = threading.Thread(target=srv.handle_request, daemon=True)
    t.start()
    t.join(300)
    srv.server_close()
    if got.get("state") != state or "code" not in got:
        return {"ok": False, "error": got.get("error", "вход не завершён за 5 минут")}
    tok = _post(TOKEN, {"code": got["code"], "client_id": c["client_id"], "client_secret": c.get("client_secret", ""),
                        "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier})
    if "refresh_token" not in tok:
        return {"ok": False, "error": "Google не выдал постоянный доступ"}
    providers.secret_set("gcal_token", json.dumps({"refresh_token": tok["refresh_token"]}))
    return {"ok": True}


def _access() -> str:
    c = _client()
    refresh = json.loads(providers.secret_get("gcal_token") or "{}").get("refresh_token")
    if not refresh:
        raise RuntimeError("Не выполнен вход: `justday calendar login`")
    return _post(TOKEN, {"client_id": c["client_id"], "client_secret": c.get("client_secret", ""),
                         "refresh_token": refresh, "grant_type": "refresh_token"})["access_token"]


def parse_start(text: str) -> dt.datetime:
    """«2026-11-07 15:00» или ISO; местный часовой пояс. Разбор живой речи делает мозг, не этот код."""
    when = dt.datetime.fromisoformat(text.strip().replace("T", " "))
    return when.astimezone() if when.tzinfo else when.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)


def preview(title: str, start: dt.datetime, minutes: int = 60) -> dict:
    end = start + dt.timedelta(minutes=minutes)
    return {"title": title.strip(), "start": start.isoformat(timespec="minutes"), "end": end.isoformat(timespec="minutes")}


def add(title: str, start: dt.datetime, minutes: int = 60) -> dict:
    """Создать событие. Вызывать только после «да» человека; повтор того же названия в то же время не плодим."""
    p = preview(title, start, minutes)
    if not p["title"]:
        return {"ok": False, "error": "пустое название"}
    token = _access()
    h = {"Authorization": f"Bearer {token}"}
    q = urllib.parse.urlencode({"timeMin": start.isoformat(), "timeMax": (start + dt.timedelta(minutes=1)).isoformat(),
                                "singleEvents": "true", "q": p["title"]})
    with urllib.request.urlopen(urllib.request.Request(f"{API}?{q}", headers=h), timeout=20) as r:
        if any(e.get("summary") == p["title"] for e in json.load(r).get("items", [])):
            return {"ok": True, "duplicate": True, **p}
    # Смещение уже в самой дате, поэтому timeZone не шлём: str(tzinfo) — не название пояса из базы IANA.
    end = start + dt.timedelta(minutes=minutes)
    body = json.dumps({"summary": p["title"], "start": {"dateTime": start.isoformat()},
                       "end": {"dateTime": end.isoformat()}}).encode()
    req = urllib.request.Request(API, body, {**h, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return {"ok": True, "id": json.load(r).get("id"), **p}
