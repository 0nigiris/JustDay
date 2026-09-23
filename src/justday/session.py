"""«Я ушёл» / «я вернулся»: close the day's windows, and put them back exactly as they were.

The computer is also a server: leaving it on with twenty windows open is the normal thing to do, and
closing them one by one to free the memory is the annoying thing. So the open applications are written
down first, then asked to close the way a click on their × asks — they save, they ask their questions —
and one command later they are all back.

Nothing is killed: what refuses to close stays open and is reported.
"""
from __future__ import annotations

import json
import logging
import time

from . import config, desktop

log = logging.getLogger("justday")

FILE = config.STATE_DIR / "session.json"
# The desktop's own furniture: not applications, and closing them would take the session down.
SYSTEM = {"quickshell", "kwin_wayland", "plasmashell", "xwaylandvideobridge", "krunner", "kded6", "polkit-kde-authentication-agent-1"}


def _apps() -> list[dict]:
    """Open windows that belong to real applications, one entry per application."""
    seen: dict[str, dict] = {}
    for w in desktop.windows("list"):
        cls = (w.get("app") or "").strip()
        if not cls or cls.lower() in SYSTEM:
            continue
        hit = next((a for a in desktop.find_apps(cls.split(".")[-1], 1)), None)
        seen.setdefault(cls.lower(), {"app": cls, "title": w.get("title", ""),
                                      "id": hit["id"] if hit else "", "name": hit["name"] if hit else cls})
    return list(seen.values())


def saved() -> dict:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save() -> dict:
    """Write down what is open right now (and keep the previous list until something is saved again)."""
    apps = _apps()
    FILE.parent.mkdir(parents=True, exist_ok=True)
    rec = {"at": time.time(), "apps": apps}
    FILE.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec


def close(keep: list[str] | None = None) -> dict:
    """Save the list, then ask every application to close — as a click on its × would."""
    keep_l = [k.lower() for k in (keep or []) + config.load()["session"]["keep"]]
    rec = save()
    closed, left = [], []
    for app in rec["apps"]:
        if any(k in app["app"].lower() or k in app["name"].lower() for k in keep_l):
            continue
        if desktop.windows("close", app["app"]):
            closed.append(app["name"])
        else:
            left.append(app["name"])
    log.info("session: closed %s, left %s", closed, left)
    return {"ok": True, "closed": closed, "still_open": left, "saved": len(rec["apps"])}


def restore() -> dict:
    """Open again everything that was written down — skipping what is already running."""
    rec = saved()
    if not rec.get("apps"):
        return {"ok": False, "error": "nothing was saved"}
    running = {w.get("app", "").lower() for w in desktop.windows("list")}
    started, skipped, unknown = [], [], []
    for app in rec["apps"]:
        if app["app"].lower() in running:
            skipped.append(app["name"])
        elif app["id"]:
            desktop.launch_app_id(app["id"])
            started.append(app["name"])
            time.sleep(0.3)  # a dozen gtk-launch calls at once make the desktop stutter
        else:
            unknown.append(app["name"])
    return {"ok": True, "started": started, "already_open": skipped, "unknown": unknown,
            "at": time.strftime("%H:%M", time.localtime(rec.get("at", time.time())))}
