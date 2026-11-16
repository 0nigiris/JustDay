"""Школьный Moodle (Aules): что нового — ближайшие сроки и непрочитанные уведомления.

Ходим официальным API мобильного приложения Moodle (`login/token.php` → `webservice/rest/server.php`),
а не разбором страниц: вёрстку Aules меняют, а API приложения у них обязан работать. Сайт, логин и
пароль лежат в связке (`service justday-school key site|login|password`) и никуда, кроме самого
сайта школы, не уходят.
"""
import json
import subprocess
import time
import urllib.parse
import urllib.request

TIMEOUT = 20


def _secret(key: str) -> str:
    try:
        r = subprocess.run(["secret-tool", "lookup", "service", "justday-school", "key", key],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def base(site: str) -> str:
    """В AULES.txt лежит адрес из строки браузера — бывает с /login/index.php, без https, со слешем."""
    site = site.strip()
    if "://" not in site:
        site = "https://" + site
    for tail in ("/login", "/my", "/course", "/index.php"):
        if tail in site:
            site = site[:site.index(tail)]
    return site.rstrip("/")


def _post(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data, doseq=True).encode()
    with urllib.request.urlopen(urllib.request.Request(url, body), timeout=TIMEOUT) as r:
        out = json.loads(r.read().decode() or "null")
    if isinstance(out, dict) and (out.get("exception") or out.get("error")):
        raise RuntimeError(out.get("message") or out.get("error") or out.get("errorcode"))
    return out


def news(now: float | None = None) -> dict:
    site, login, pw = _secret("site"), _secret("login"), _secret("password")
    if not (site and login and pw):
        return {"ok": False, "error": "нет сайта, логина или пароля в связке (service justday-school)"}
    root = base(site)
    try:
        token = _post(f"{root}/login/token.php",
                      {"username": login, "password": pw, "service": "moodle_mobile_app"}).get("token")
        if not token:
            return {"ok": False, "error": "сайт не выдал токен: вход для приложения Moodle выключен?"}

        def ws(fn: str, **args) -> dict:
            return _post(f"{root}/webservice/rest/server.php",
                         {"wstoken": token, "wsfunction": fn, "moodlewsrestformat": "json", **args})

        me = ws("core_webservice_get_site_info")
        events = ws("core_calendar_get_action_events_by_timesort",
                    timesortfrom=int(now or time.time()), limitnum=10).get("events", [])
        try:  # всплывающие уведомления — отдельный плагин, на сайте его могут выключить
            notes = ws("message_popup_get_popup_notifications", useridto=me["userid"],
                       newestfirst=1, limit=10).get("notifications", [])
        except RuntimeError:
            notes = []
    except (OSError, ValueError, RuntimeError) as e:
        return {"ok": False, "error": f"Aules не ответил: {e}"}
    return {
        "ok": True,
        "deadlines": [{"what": e.get("name", ""), "course": (e.get("course") or {}).get("fullname", ""),
                       "when": time.strftime("%d.%m %H:%M", time.localtime(e.get("timesort", 0))),
                       "url": e.get("url", "")} for e in events],
        "unread": [{"what": n.get("subject", ""),
                    "when": time.strftime("%d.%m %H:%M", time.localtime(n.get("timecreated", 0)))}
                   for n in notes if not n.get("read")],
    }
