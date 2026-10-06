"""Desktop notifications: reading them off the bus, and opening the app one came from.

A notification says which app sent it in words a human picked («Telegram Desktop»), so finding the
desktop entry behind it is a small matching problem of its own."""
from __future__ import annotations

import logging
import re
import subprocess
from datetime import datetime, timedelta

from . import desktop, kde

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

    desktop_id = str(desktop_id or "").strip()
    if desktop_id.endswith(".desktop"):
        desktop_id = desktop_id[: -len(".desktop")]
    # Icon= theme names sometimes arrive where desktop-entry should be — keep as search term only.
    if "/" in desktop_id or desktop_id.startswith("file:"):
        desktop_id = ""
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


# ───────────── чьи всплывашки показывать ─────────────
#
# Уведомления и так приходят на остров: демон подслушивает шину и рисует их своим шрифтом и своими
# цветами. Но плазма в это же время показывает свою всплывашку — и человек видит одно и то же
# дважды, вторым разом в чужом оформлении.
#
# Выключается это её же «не беспокоить»: всплывашек нет, история остаётся, а программы как звали
# Notify, так и зовут — значит, остров по-прежнему всё слышит. Отдельного «отключить всплывашки»
# у плазмы нет, поэтому пользуемся тем, что есть.
QUIET_YEARS = 50


def system_popups(on: bool | None = None) -> dict:
    """Показывает ли плазма свои всплывашки. on=None — только узнать."""
    if on is None:
        return {"ok": True, "popups": not _quiet_now()}
    if on:
        value = ""                       # пустая дата — «не беспокоить» выключено
    else:
        until = datetime.now() + timedelta(days=365 * QUIET_YEARS)
        value = until.strftime("%Y,%-m,%-d,%-H,%-M,%-S.000")
    try:
        subprocess.run([kde.KWRITE, "--file", "plasmanotifyrc", "--group", "DoNotDisturb",
                        "--key", "Until", value], capture_output=True, timeout=5, check=False)
        # «Не беспокоить» у плазмы пропускает срочные уведомления — и это не прихоть, а задумка:
        # запись экрана и разговор по видеосвязи человек обязан видеть всегда. Но «сохранено в
        # Screencast_…webm» срочным считается тоже, и синяя плашка выскакивает поверх всего. Здесь
        # мы отключаем именно это послабление, а не сами уведомления: история цела, остров слышит.
        subprocess.run([kde.KWRITE, "--file", "plasmanotifyrc", "--group", "Notifications",
                        "--key", "CriticalInDndMode", "false" if not on else "true"],
                       capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "popups": bool(on)}


def app_popups(app: str, on: bool) -> dict:
    """Всплывашки одной программы. История при этом остаётся: прячем показ, а не запись.

    Нужно там, где «не беспокоить» бессильно: запись экрана плазма показывает всегда и нарочно, и
    спорить с этим правилом целиком не стоит — а вот заткнуть одну программу, которая каждый раз
    сообщает, куда она сохранила файл, можно и нужно.
    """
    ident = str(app or "").strip()
    if not ident:
        return {"ok": False, "error": "нечего прятать: пустое имя программы"}
    try:
        subprocess.run([kde.KWRITE, "--file", "plasmanotifyrc",
                        "--group", "Applications", "--group", ident,
                        "--key", "ShowPopups", "true" if on else "false"],
                       capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "app": ident, "popups": bool(on)}


def _quiet_now() -> bool:
    try:
        raw = subprocess.run([kde.KREAD, "--file", "plasmanotifyrc", "--group", "DoNotDisturb",
                              "--key", "Until"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return False
    parts = raw.split(",")
    if len(parts) < 3:
        return False
    try:
        until = datetime(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return False
    return until > datetime.now()


# ───────────── системный OSD плазмы (громкость / яркость / раскладка) ─────────────
#
# Остров рисует свой HUD по island.show_osd. Плазма при этом всё равно показывает свой OSD —
# получается два одинаковых попапа. Отдельного D-Bus inhibit (типа osdProgressInhibit) в Plasma 6
# нет: plasmashell смотрит plasmarc [OSD] Enabled (то же «Display visual feedback for status
# changes» в Workspace Behavior) через KConfigWatcher — запись липкая и подхватывается без
# перезапуска. Дополнительно глушим plasmaparc VolumeOsd/MuteOsd/…, чтобы AudioShortcutsService
# даже не звал org.kde.osdService.
#
# Правило: JustDay show_osd включён → Plasma OSD выкл. show_osd выкл → Plasma OSD снова вкл,
# чтобы человек не остался без индикатора. То же применяет установщик и `justday popups island`.

# Keys under plasmaparc [General] that gate volume-related Plasma OSDs (plasma-pa GlobalConfig).
_PLASMA_VOLUME_OSD_KEYS = (
    "VolumeOsd",
    "MuteOsd",
    "MicrophoneSensitivityOsd",
    "PushToTalkOsd",
    "MutedMicrophoneReminderOsd",
    "DefaultOutputDeviceOsd",
)


def _kwrite(file: str, group: str, key: str, value: str) -> None:
    try:
        subprocess.run([kde.KWRITE, "--file", file, "--group", group, "--key", key, value],
                       capture_output=True, timeout=5, check=False)
    except OSError:
        pass


def _kread(file: str, group: str, key: str) -> str:
    try:
        return subprocess.run([kde.KREAD, "--file", file, "--group", group, "--key", key],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except OSError:
        return ""


def plasma_osd(on: bool | None = None) -> dict:
    """Показывает ли плазма свой volume/brightness/keyboard OSD. on=None — только узнать."""
    if on is None:
        raw = ""
        try:
            raw = _kread("plasmarc", "OSD", "Enabled")
        except (OSError, subprocess.SubprocessError):
            pass
        # Empty / missing = Plasma default (enabled).
        enabled = raw.lower() not in ("false", "0", "no", "off")
        return {"ok": True, "osd": enabled}
    try:
        _kwrite("plasmarc", "OSD", "Enabled", "true" if on else "false")
        # Extra gate inside osd.cpp for layout changes (still blocked by Enabled=false, but keeps
        # System Settings / future callers consistent when Enabled is toggled elsewhere).
        _kwrite("plasmarc", "OSD", "kbdLayoutChangedEnabled", "true" if on else "false")
        for key in _PLASMA_VOLUME_OSD_KEYS:
            _kwrite("plasmaparc", "General", key, "true" if on else "false")
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": str(e), "osd": bool(on)}
    return {"ok": True, "osd": bool(on)}


def sync_plasma_osd(show_osd: bool | None = None, system_popups: bool | None = None) -> dict:
    """Mute Plasma OSD when JustDay owns the HUD (island.show_osd).

    Call from installer / `justday popups island|system` / settings reload so it sticks.
    `system_popups` is accepted for those call sites (island mode pairs with show_osd on
    install) but mute itself follows show_osd: on → Plasma off; explicit false → Plasma back
    so volume keys still have an indicator.
    """
    try:
        from . import config as cfgmod
        island = cfgmod.load().get("island") or {}
    except Exception:
        island = {}
    if show_osd is None:
        show_osd = island.get("show_osd", True)
    # system_popups kept so popups/install call sites stay explicit; mute is show_osd-driven.
    _ = system_popups if system_popups is not None else island.get("system_popups", False)
    return plasma_osd(show_osd is False)  # Plasma on only when JustDay OSD is off
