"""Настоящий звонок: Джарвис набирает номер и говорит в трубку.

**Почему это вообще было отложено.** Telnyx устроен событиями: оператор шлёт «набрали», «сняли
трубку», «положили» на HTTPS-адрес, и только получив «сняли трубку», можно заговорить. Адрес
должен быть виден из интернета, а у нас правило: наружу не смотрит ничего, только 127.0.0.1.

**Почему это правило больше не мешает.** Туннель Cloudflare — соединение, которое наша машина
открывает **сама, наружу**. Порт на ней не слушает никто, кроме 127.0.0.1; маршрутизатор не
трогается; адрес живёт, пока живёт туннель. То есть защита остаётся ровно той же, а публичный
адрес появляется. Это не обход правила, а способ его соблюсти.

    cloudflared tunnel --url http://127.0.0.1:8787   →   https://что-то.trycloudflare.com

Адрес у быстрого туннеля каждый раз новый, поэтому мы не вписываем его никуда руками: подняли
туннель — сами же сказали Telnyx, куда слать события (`PATCH /call_control_applications/…`).

**Чего здесь нарочно нет.** Ни одного открытого порта на внешнем интерфейсе, ни одной записи
ключа вне связки, ни одного звонка без потолка по времени и без проверки префикса.

Что нужно от человека один раз: `sudo dnf install cloudflared`, купить номер в портале Telnyx
(~$1/мес), положить ключ в связку и поставить потолок трат.

    secret-tool store --label 'JustDay: telnyx' service justday key telnyx
    justday config set phone.telnyx.from +1XXXXXXXXXX
    justday config set phone.telnyx.app_id XXXXXXXX
"""
from __future__ import annotations

import base64
import contextlib
import http.server
import json
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import ClassVar

from . import config, providers

API = "https://api.telnyx.com/v2"
TIMEOUT = 20

# Платные справочные: минута там стоит не центы, а десятки центов, и смысл звонка другой.
# Набирать их ассистенту нельзя вовсе — это не настройка, а запрет.
PREMIUM = ("900", "901", "902", "803", "806", "807", "905", "907")
# Разговор «вы сегодня открыты?» дольше полутора минут не бывает. Потолок стоит затем, что
# худший случай — это шестьдесят центов, а не незамеченный час в цикле.
MAX_SECONDS = 90
# Событие звонка — крошечный JSON. Тело больше этого — не от Telnyx; читать его до конца значит дать любому,
# кто нашёл адрес туннеля, забивать память демона.
MAX_BODY = 64 * 1024
# Подпись Telnyx вместе с меткой времени; старше — повтор чужого перехваченного события.
TOLERANCE_S = 300


def key() -> str:
    return providers.secret_get("telnyx")


def settings() -> dict:
    return (config.load().get("phone") or {}).get("telnyx") or {}


def ready() -> tuple[bool, str]:
    """Можно ли звонить и чего не хватает — словами, а не булевым нулём."""
    if not key():
        return False, ("нет ключа: secret-tool store --label 'JustDay: telnyx' "
                       "service justday key telnyx")
    s = settings()
    if not s.get("from"):
        return False, "нет своего номера: justday config set phone.telnyx.from +1XXXXXXXXXX"
    if not s.get("app_id"):
        return False, "нет приложения Call Control: justday config set phone.telnyx.app_id XXXX"
    if not s.get("public_key"):
        return False, ("нет публичного ключа вебхуков: портал Telnyx → Keys & Credentials → Public Key, затем "
                       "justday config set phone.telnyx.public_key КЛЮЧ (без него события звонка нечем проверить)")
    import shutil
    if not shutil.which("cloudflared"):
        return False, "нет cloudflared: sudo dnf install cloudflared (нужен для адреса событий)"
    return True, ""


def _api(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{API}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {key()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode() or "{}").get("data") or {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Telnyx {e.code}: {e.read().decode(errors='replace')[:300]}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise RuntimeError(f"Telnyx недоступен: {e}") from e


def check_number(to: str) -> str:
    """Проверить номер и отказать там, где звонок стоит дорого или бессмыслен."""
    num = re.sub(r"[^\d+]", "", str(to or ""))
    if not num.startswith("+") or len(num) < 8:
        raise RuntimeError(f"номер не в международном виде: {to!r} (нужно +34…, +1…)")
    tail = num[1:]
    for code in PREMIUM:
        # Префикс платной справочной идёт сразу за кодом страны, длина кода разная — ищем в начале.
        if re.match(rf"\d{{1,3}}{code}", tail):
            raise RuntimeError(f"{num} — платная справочная ({code}): такие ассистент не набирает")
    return num


def verify(public_key: str, signature: str, timestamp: str, body: bytes, now: float | None = None) -> bool:
    """Подпись события Telnyx (Ed25519 по «метка|тело»). Любая неясность — «нет»: этот адрес виден всему интернету.

    Без проверки любой, кто узнал адрес туннеля, подставлял свой `call_control_id` — а он уходит в запросы к
    Telnyx с нашим ключом (Р-7 ревизии)."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        if abs((time.time() if now is None else now) - int(timestamp)) > TOLERANCE_S:
            return False
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key)).verify(
            base64.b64decode(signature), timestamp.encode() + b"|" + body)
        return True
    except Exception:
        return False


class _Hook(http.server.BaseHTTPRequestHandler):
    """Слушает только 127.0.0.1. Наружу его выводит туннель, а не открытый интерфейс."""

    said: ClassVar[dict] = {}
    public_key: ClassVar[str] = ""

    def _refuse(self, code: int) -> None:
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:          # имя с большой буквы задано базовым классом, не нами
        try:
            length = int(self.headers.get("Content-Length") or "")
        except ValueError:
            return self._refuse(411)    # без длины тела не читаем: «до конца соединения» — это бесконечность
        if not 0 <= length <= MAX_BODY:
            return self._refuse(413)
        raw = self.rfile.read(length)
        if not verify(_Hook.public_key, self.headers.get("telnyx-signature-ed25519") or "",
                      self.headers.get("telnyx-timestamp") or "", raw):
            return self._refuse(403)
        try:
            event = json.loads(raw.decode() or "{}")
        except ValueError:
            event = {}
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
        data = (event.get("data") or {}).get("payload") or {}
        kind = (event.get("data") or {}).get("event_type") or ""
        ccid = data.get("call_control_id") or ""
        # Только звонок, который создали мы сами: чужой ccid не получит от нас ни одного запроса к Telnyx.
        job = _Hook.said.get(ccid) if ccid else None
        if not job:
            return
        if kind == "call.answered":
            job["answered"] = time.time()
            with contextlib.suppress(RuntimeError):
                _api("POST", f"/calls/{ccid}/actions/speak",
                     {"payload": job["text"], "voice": job.get("voice", "female"),
                      "language": job.get("language", "ru-RU")})
        elif kind in ("call.speak.ended", "call.hangup"):
            job["done"] = True
            if kind != "call.hangup":
                with contextlib.suppress(RuntimeError):
                    _api("POST", f"/calls/{ccid}/actions/hangup", {})

    def log_message(self, *a) -> None:      # тишина: события звонка не должны засорять журнал
        return


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _tunnel(port: int, wait: float = 25.0) -> tuple[subprocess.Popen, str]:
    """Поднять быстрый туннель и вернуть выданный адрес.

    Адрес Cloudflare печатает в свой же вывод — другого способа узнать его у быстрого туннеля нет,
    поэтому читаем вывод, а не гадаем.
    """
    p = subprocess.Popen(["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        line = p.stdout.readline() if p.stdout else ""
        if not line and p.poll() is not None:
            break
        hit = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line or "")
        if hit:
            return p, hit.group(0)
    p.terminate()
    raise RuntimeError("туннель не поднялся: cloudflared не назвал адрес за отведённое время")


def call(to: str, text: str, *, seconds: int = MAX_SECONDS) -> dict:
    """Позвонить и сказать. Возвращает, чем кончилось, — молча не оставляет никогда.

    Порядок: поднять местный слушатель на 127.0.0.1 → вывести его туннелем → сказать Telnyx,
    куда слать события → набрать → дождаться «сняли трубку» → сказать → положить трубку.
    """
    # Номер проверяем первым, до всякой настройки: «эту цифру не набирать» — запрет, а не
    # следствие того, что ключ не положен. Иначе на платной справочной человек увидел бы
    # «нет ключа», положил ключ и только тогда узнал настоящую причину.
    try:
        num = check_number(to)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    ok, why = ready()
    if not ok:
        return {"ok": False, "error": why}
    text = str(text or "").strip()
    if not text:
        return {"ok": False, "error": "нечего говорить"}
    s = settings()
    port = _free_port()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), _Hook)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tun = None
    job = {"text": text[:3000], "voice": s.get("voice", "female"),
           "language": s.get("language", "ru-RU"), "answered": 0.0, "done": False}
    _Hook.said = {}
    _Hook.public_key = str(s.get("public_key") or "")
    try:
        tun, url = _tunnel(port)
        _api("PATCH", f"/call_control_applications/{s['app_id']}",
             {"webhook_event_url": url, "webhook_api_version": "2"})
        got = _api("POST", "/calls", {"connection_id": str(s["app_id"]), "to": num,
                                      "from": s["from"], "timeout_secs": 30})
        ccid = got.get("call_control_id") or ""
        _Hook.said = {ccid: job}
        limit = max(10, min(MAX_SECONDS, int(seconds)))
        deadline = time.monotonic() + limit + 35      # +35 на гудки до ответа
        while time.monotonic() < deadline and not job["done"]:
            if job["answered"] and time.time() - job["answered"] > limit:
                with contextlib.suppress(RuntimeError):
                    _api("POST", f"/calls/{ccid}/actions/hangup", {})
                break
            time.sleep(0.4)
        return {"ok": bool(job["answered"]), "to": num, "call_id": ccid,
                "answered": bool(job["answered"]),
                "note": "" if job["answered"] else "не сняли трубку"}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    finally:
        _Hook.said = {}
        srv.shutdown()
        if tun is not None:
            tun.terminate()
