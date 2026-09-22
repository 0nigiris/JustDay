"""Desktop notifications: reading them off the bus, and opening the app one came from.

A notification says which app sent it in words a human picked («Telegram Desktop»), so finding the
desktop entry behind it is a small matching problem of its own."""
from __future__ import annotations

import logging
import re

from . import desktop

log = logging.getLogger("justday.daemon")


NOTIFY_RX = re.compile(r'string "(?P<app>.*?)"\n\s*uint32 \d+\n\s*string "(?P<icon>.*?)"\n\s*string "(?P<summary>.*?)"\n'
                       r'\s*string "(?P<body>.*?)"\n\s*array \[', re.S)
DESKTOP_RX = re.compile(r'string "desktop-entry"\n\s*variant\s+string "(.*?)"')


def parse_notification(raw: str) -> dict | None:
    """One `dbus-monitor` Notify call → {app, icon, summary, body}."""
    m = NOTIFY_RX.search(raw)
    if not m:
        return None
    d = DESKTOP_RX.search(raw)
    unq = lambda s: s.replace('\\"', '"')  # noqa: E731
    return {"app": unq(m["app"]), "icon": (d.group(1) if d else "") or m["icon"], "summary": unq(m["summary"]),
            "desktop": d.group(1) if d else "", "body": re.sub(r"<[^>]+>", "", unq(m["body"]))[:4000]}


# parts of a desktop id or an app name that match half the desktop: never search windows by these
NOISE = {"desktop", "app", "client", "gui", "gtk", "qt", "org", "com", "io", "net", "www", "free", "linux", "flatpak"}


def notification_terms(app: str, desktop_id: str) -> list[str]:
    """Window-search terms for a notification, most telling first: `org.telegram.desktop` + `Telegram Desktop`
    → org.telegram.desktop, telegram, telegram desktop. Plain `desktop` would match half the windows open."""
    terms: list[str] = []
    if desktop_id:
        terms.append(desktop_id.lower())
        parts = [p for p in desktop_id.lower().split(".") if p and p not in NOISE]
        if parts:
            terms.append(parts[-1])
    if app:
        terms.append(app.lower())
        word = app.lower().split()[0] if app.split() else ""
        if word and word not in NOISE:
            terms.append(word)
    out: list[str] = []
    for term in terms:  # keep the order, drop repeats and terms too short to mean anything
        if len(term) > 2 and term not in out:
            out.append(term)
    return out


def open_notification_app(app: str, desktop_id: str) -> str:
    """A tap on a notification on the island: bring its app forward (or start it). The exact chat opens only when
    Plasma's own popup is clicked — the island only watches notifications, it cannot press their buttons."""

    terms = notification_terms(app, desktop_id)
    for term in terms:
        if desktop.windows("focus", term):
            log.info("notification: focused a window matching %r", term)
            return "focused"
    # no window: Telegram and Discord hide in the tray, and starting them again does nothing.
    # Activating their tray icon is exactly what a click on it does — the window comes back.
    flat = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())  # noqa: E731
    keys = [flat(t) for t in terms if flat(t)]
    for item in desktop.tray_items():
        hay = flat(item["id"]) + " " + flat(item["title"])
        if any(k in hay for k in keys) and desktop.tray_activate(item):
            log.info("notification: activated the tray icon of %s", item["id"] or item["service"])
            return "tray"
    # still nothing: start the app from its desktop entry
    apps = desktop.list_apps()
    hit = next((a for a in apps if desktop_id and a["id"] == desktop_id), None)
    if not hit:  # a name like "Telegram Desktop" scores below an exact hit — take the best of the terms
        best = None
        for term in terms:
            for a in desktop.find_apps(term, 1):
                if a.get("score", 0) > (best or {}).get("score", 0):
                    best = a
        hit = best if best and best.get("score", 0) >= 0.6 else None
    if hit:
        desktop.launch_app_id(hit["id"])
        log.info("notification: launched %s", hit["id"])
        return "launched"
    log.info("notification: no app for app=%r desktop=%r", app, desktop_id)
    return "not found"
